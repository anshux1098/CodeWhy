from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings
from app.services.ingest.git_probe import (
    CommandRunner,
    FileHistory,
    Revert,
    collect_class_constants,
    constant_history,
    default_branch,
    default_runner,
    detect_reverts,
    find_package_directory,
    iter_python_files,
    read_file_history,
    read_history,
    revert_map,
)

DEFAULT_CANDIDATES = ("urllib3/urllib3", "psf/requests")
CLONE_ROOT = ROOT / "data" / "clones"
OUTPUT_PATH = ROOT / "review" / "target_probe.md"
TOP_FILES = 20
TOP_CLASS_CONSTANTS = 20
MIN_CLASS_COMMITS = 2
DETAIL_FILES = 5

FILE_DEFINITIONS = (
    ("commits", "commits that touched the file, read with `git log --follow` so renames are followed."),
    ("pr_linked", "of those commits, how many reference a pull request: `(#123)` in the subject, or a `Merge pull request #123` subject."),
    ("reverted", "commits touching this file whose SHA is the target of a revert somewhere in the repository history."),
    ("reverts_touching", "revert commits that themselves touched this file."),
    ("authors", "count of distinct author email addresses. Addresses are counted, never printed."),
    ("long_msgs", "commits whose body is at least 150 characters."),
    ("first .. last", "oldest and newest authored date among the file's commits."),
)

CLASS_DEFINITIONS = (
    (
        "commits touching line",
        "commits returned by `git log -G` for the indented defining line of the class attribute. "
        "An upper bound: it also counts the introduction, moves and reformatting, not only value changes.",
    ),
    (
        "with PR ref",
        "of those commits, how many reference a pull request, as defined above.",
    ),
)

SORT_NOTE = (
    "Sort key: `reverted + reverts_touching` descending, then `pr_linked` descending. This is an "
    "ordering to put the busiest files first, not a quality ranking or a recommendation."
)


@dataclass
class TargetProbe:
    repo: str
    status: str = "ok"
    files: list[FileHistory] = field(default_factory=list)
    class_constants: list = field(default_factory=list)
    constants_found: int = 0
    notes: list[str] = field(default_factory=list)
    reverts: list[Revert] = field(default_factory=list)


def probe_repository(
    repo: str,
    *,
    runner: CommandRunner = default_runner,
    clone_root: Path = CLONE_ROOT,
) -> TargetProbe:
    probe = TargetProbe(repo=repo)
    _, _, name = repo.partition("/")
    package_dir = find_package_directory(clone_root / repo.replace("/", "__"), name)
    if package_dir is None:
        probe.status = "failed"
        probe.notes.append(f"{repo}: no local clone or package directory found")
        return probe

    path = clone_root / repo.replace("/", "__")
    branch = default_branch(path, runner=runner)
    all_commits = read_history(path, branch, runner=runner)
    all_reverts = detect_reverts(all_commits)
    targets = revert_map(all_commits)
    probe.reverts = all_reverts
    probe.notes.append(f"{repo}: {len(all_commits)} commits, {len(all_reverts)} reverts")

    summaries: list[FileHistory] = []
    for python_file in iter_python_files(package_dir):
        relative = python_file.relative_to(path).as_posix()
        try:
            commits = read_file_history(path, relative, branch, runner=runner)
        except Exception as exc:
            probe.notes.append(f"{repo}: {relative} skipped: {exc.__class__.__name__}")
            continue
        summaries.append(
            summarise(relative, commits, revert_targets=targets, all_reverts=all_reverts)
        )
    probe.files = sorted(summaries, key=lambda h: (-h.revert_pressure, -h.pr_linked, h.path))[:TOP_FILES]

    constants = collect_class_constants(package_dir, path)
    probe.constants_found = len(constants)
    histories = []
    for constant in constants:
        try:
            histories.append(constant_history(path, constant, runner=runner))
        except Exception as exc:
            probe.notes.append(f"{repo}: {constant.name} skipped: {exc.__class__.__name__}")
    probe.class_constants = sorted(
        (h for h in histories if h.commits >= MIN_CLASS_COMMITS),
        key=lambda h: (-h.commits, h.name),
    )[:TOP_CLASS_CONSTANTS]
    probe.notes.append(
        f"{repo}: {probe.constants_found} class-level constants found, "
        f"{len(probe.class_constants)} shown with at least {MIN_CLASS_COMMITS} commits"
    )
    return probe


def summarise(
    relative: str,
    commits: Sequence,
    *,
    revert_targets: dict[str, Revert],
    all_reverts: Sequence[Revert],
) -> FileHistory:
    from app.services.ingest.git_probe import summarise_file

    return summarise_file(
        relative,
        commits,
        revert_targets=revert_targets,
        all_reverts=all_reverts,
    )


def render_files_table(probe: TargetProbe) -> str:
    header = (
        "| repo | file | commits | pr_linked | reverted | reverts_touching | authors | "
        "long_msgs | first | last |"
    )
    divider = "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    rows = [
        f"| {probe.repo} | {h.path} | {h.commits} | {h.pr_linked} | {h.reverted} | "
        f"{h.reverts_touching} | {h.authors} | {h.long_messages} | "
        f"{(h.first_commit_at or 'n/a')[:10]} | {(h.last_commit_at or 'n/a')[:10]} |"
        for h in probe.files
    ]
    if not rows:
        return "\n".join([header, divider])
    return "\n".join([header, divider, *rows])


def render_class_table(probe: TargetProbe) -> str:
    header = "| repo | class constant | file | current value | commits touching line | with PR ref | first | last |"
    divider = "| --- | --- | --- | --- | --- | --- | --- | --- |"
    rows = [
        f"| {probe.repo} | {h.name} | {h.path} | {h.truncated_value} | {h.commits} | "
        f"{h.with_pull_request} | {(h.first_commit_at or 'n/a')[:10]} | "
        f"{(h.last_commit_at or 'n/a')[:10]} |"
        for h in probe.class_constants
    ]
    if not rows:
        return "\n".join([header, divider])
    return "\n".join([header, divider, *rows])


def render_revert_detail(probe: TargetProbe, targets: dict[str, Revert]) -> str:
    header = "| repo | file | reverted commit date | short sha | reverted subject | PR | revert date | revert short sha | revert subject |"
    divider = "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    rows: list[str] = []
    for history in probe.files[:DETAIL_FILES]:
        for commit in history.reverted_commits:
            revert = targets.get(commit.sha)
            if revert is None:
                continue
            rows.append(
                f"| {probe.repo} | {history.path} | {commit.authored_at[:10]} | {commit.sha[:7]} | "
                f"{commit.subject[:60]} | {'yes' if '(#' in commit.subject else 'no'} | "
                f"{revert.authored_at[:10]} | {revert.sha[:7]} | {revert.subject[:60]} |"
            )
    if not rows:
        return "\n".join([header, divider])
    return "\n".join([header, divider, *rows])


def build_report(probes: Sequence[TargetProbe], targets: dict[str, dict[str, Revert]]) -> str:
    parts = [
        "# Demo target probe",
        "",
        "Generated by `scripts/probe_targets.py`. Every number was measured from the existing full",
        "clones using plain `git`. Nothing is estimated or hand-written.",
        "",
        "Target code is never imported or executed: Python files are read as text and parsed with `ast`.",
        "",
        SORT_NOTE,
        "",
        f"## Files, top {TOP_FILES} per repository",
        "",
        *[render_files_table(probe) for probe in probes],
        "",
        "### File column definitions",
        "",
        *[f"- **{name}**: {text}" for name, text in FILE_DEFINITIONS],
        "",
        f"## Class-level constants, top {TOP_CLASS_CONSTANTS} per repository, at least {MIN_CLASS_COMMITS} commits",
        "",
        *[render_class_table(probe) for probe in probes],
        "",
        "### Class constant column definitions",
        "",
        *[f"- **{name}**: {text}" for name, text in CLASS_DEFINITIONS],
        "",
        f"## Reverted commits for the top {DETAIL_FILES} files per repository",
        "",
        "Each row is one candidate supersession chain: a commit that changed the file, and the",
        "revert that undid it.",
        "",
        *[render_revert_detail(probe, targets.get(probe.repo, {})) for probe in probes],
        "",
        "## Notes",
        "",
    ]
    parts.extend(f"- {note}" for probe in probes for note in probe.notes)
    parts.extend(["", "No recommendation is produced here; the targets are chosen by hand.", ""])
    return "\n".join(parts)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Probe files and class constants as demo targets.")
    parser.add_argument("repos", nargs="*", help="owner/name repositories; defaults to urllib3 and requests")
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    args = parser.parse_args(argv)

    repos = tuple(args.repos) or DEFAULT_CANDIDATES
    Settings()

    probes: list[TargetProbe] = []
    targets: dict[str, dict[str, Revert]] = {}
    for repo in repos:
        print(f"probing {repo} ...", file=sys.stderr)
        probe = probe_repository(repo)
        probes.append(probe)
        if probe.reverts:
            targets[repo] = {
                revert.target_sha: revert for revert in probe.reverts if revert.target_sha
            }

    print(render_files_table(probes[0]) if probes else "")
    for probe in probes[1:]:
        print()
        print(render_files_table(probe))
    print()
    print(SORT_NOTE)
    print()
    for probe in probes:
        print(render_class_table(probe))
        print()
    print("Notes")
    for note in (note for probe in probes for note in probe.notes):
        print(f"- {note}")
    print()
    print("No recommendation is produced here; the targets are chosen by hand.")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_report(probes, targets), encoding="utf-8")
    print(f"wrote {output}")
    return 0 if all(probe.status == "ok" for probe in probes) else 1


if __name__ == "__main__":
    raise SystemExit(main())