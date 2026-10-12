from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings, SettingsError
from app.services.ingest.git_probe import (
    GIT_TIMEOUT_SECONDS,
    METRIC_DEFINITIONS,
    MIN_CONSTANT_COMMITS,
    TOP_CONSTANTS,
    CommandRunner,
    RepoProbe,
    collect_constants,
    constant_history,
    default_branch,
    default_runner,
    detect_reverts,
    directory_size_bytes,
    clone_repository,
    find_package_directory,
    read_history,
)
from app.services.ingest.github_client import GitHubError, GitHubGraphQLClient

DEFAULT_CANDIDATES = ("urllib3/urllib3", "psf/requests", "celery/celery")
CLONE_ROOT = ROOT / "data" / "clones"
OUTPUT_PATH = ROOT / "review" / "history_probe.md"

REPO_QUERY = """
query RepoDiskUsage($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    nameWithOwner
    diskUsage
  }
}
""".strip()


def size_hint_mb(repo: str) -> Optional[float]:
    owner, _, name = repo.partition("/")
    if not owner or not name:
        return None
    try:
        config = Settings()
        config.require_github()
        with GitHubGraphQLClient(config) as client:
            payload = client.query(REPO_QUERY, {"owner": owner, "name": name})
        repository = (payload.get("data") or {}).get("repository") or {}
        disk = repository.get("diskUsage")
        return float(disk) / 1024 if isinstance(disk, int) else None
    except (SettingsError, GitHubError, ValueError):
        return None


def probe_repository(
    repo: str,
    *,
    runner: CommandRunner = default_runner,
    max_repo_size_mb: Optional[int] = None,
    clone_root: Path = CLONE_ROOT,
) -> RepoProbe:
    probe = RepoProbe(repo=repo)
    try:
        path = clone_repository(
            repo,
            clone_root,
            runner=runner,
            size_limit_mb=max_repo_size_mb,
            size_hint_mb=size_hint_mb(repo) if max_repo_size_mb else None,
        )
    except Exception as exc:
        probe.status = "failed"
        probe.notes.append(f"{repo}: {exc.__class__.__name__}: {str(exc)[:160]}")
        return probe

    probe.notes.append(f"{repo}: cloned to {directory_size_bytes(path) / (1024 * 1024):.0f} MB")
    try:
        branch = default_branch(path, runner=runner)
        probe.default_branch = branch
        commits = read_history(path, branch, runner=runner)
        probe.total_commits = len(commits)
        probe.reverts = detect_reverts(commits)[:10]
        probe.notes.append(f"{repo}: {len(probe.reverts)} reverts shown, of the full history")
    except Exception as exc:
        probe.status = "failed"
        probe.notes.append(f"{repo}: history probe failed: {exc.__class__.__name__}: {str(exc)[:160]}")
        return probe

    _, _, name = repo.partition("/")
    package_dir = find_package_directory(path, name)
    if package_dir is None:
        probe.status = "failed"
        probe.notes.append(f"{repo}: no package directory found for {name}")
        return probe
    constants = collect_constants(package_dir, path)
    probe.constants_found = len(constants)
    histories = []
    for constant in constants:
        try:
            histories.append(constant_history(path, constant, runner=runner))
        except Exception as exc:
            probe.notes.append(f"{repo}: {constant.name} skipped: {exc.__class__.__name__}")
    probe.constant_histories = sorted(
        (h for h in histories if h.commits >= MIN_CONSTANT_COMMITS),
        key=lambda h: (-h.commits, h.name),
    )[:TOP_CONSTANTS]
    return probe


def render_revert_table(probes: Sequence[RepoProbe]) -> str:
    header = "| repo | branch | total commits | reverts | reverts touching .py | status |"
    divider = "| --- | --- | --- | --- | --- | --- |"
    rows = [
        f"| {p.repo} | {p.default_branch or 'n/a'} | {p.total_commits} | {len(p.reverts)} | "
        f"{p.reverts_touching_python} | {p.status} |"
        for p in probes
    ]
    return "\n".join([header, divider, *rows])


def render_recent_reverts_table(probe: RepoProbe) -> str:
    header = "| repo | date | short sha | subject | reverts |"
    divider = "| --- | --- | --- | --- | --- |"
    rows = [
        f"| {probe.repo} | {revert.authored_at} | {revert.short_sha} | "
        f"{revert.subject[:70]} | {revert.target_subject or 'target not in this repo'} |"
        for revert in probe.reverts
    ]
    if not rows:
        return "\n".join([header, divider, f"| {probe.repo} | n/a | n/a | no reverts found | n/a |"])
    return "\n".join([header, divider, *rows])


def render_constants_table(probes: Sequence[RepoProbe]) -> str:
    header = (
        "| repo | constant | file | current value | commits touching line | with PR ref | "
        "first commit | last commit |"
    )
    divider = "| --- | --- | --- | --- | --- | --- | --- | --- |"
    rows: list[str] = []
    for probe in probes:
        if not probe.constant_histories:
            rows.append(f"| {probe.repo} | n/a | n/a | n/a | 0 | 0 | n/a | n/a |")
            continue
        for history in probe.constant_histories:
            rows.append(
                f"| {probe.repo} | {history.name} | {history.path} | {history.truncated_value} | "
                f"{history.commits} | {history.with_pull_request} | "
                f"{(history.first_commit_at or 'n/a')[:10]} | {(history.last_commit_at or 'n/a')[:10]} |"
            )
    return "\n".join([header, divider, *rows])


def render_definitions() -> str:
    return "\n".join(f"- **{name}**: {text}" for name, text in METRIC_DEFINITIONS)


def build_report(probes: Sequence[RepoProbe]) -> str:
    parts = [
        "# History probe",
        "",
        "Generated by `scripts/probe_history.py`. Every number below was measured from a full",
        "clone of the repository using plain `git`. Nothing is estimated or hand-written.",
        "",
        "Target code is never imported or executed: Python files are read as text and parsed",
        "with `ast`.",
        "",
        "## Reverts and history size",
        "",
        render_revert_table(probes),
        "",
        f"Showing the {len(probes[0].reverts) if probes else 0} most recent reverts per repository.",
        "",
        "## Most recent reverts",
        "",
        *[render_recent_reverts_table(probe) for probe in probes],
        "",
        "## Constants with value history",
        "",
        f"Top {TOP_CONSTANTS} constants per repository by commit count, with at least "
        f"{MIN_CONSTANT_COMMITS} commits touching the defining line.",
        "",
        render_constants_table(probes),
        "",
        "## Constants found per repository",
        "",
    ]
    parts.extend(f"- {probe.repo}: {probe.constants_found}" for probe in probes)
    parts.extend(
        [
            "",
            "## Definitions",
            "",
            render_definitions(),
            "",
            "## Notes, failures and skips",
            "",
        ]
    )
    notes = [note for probe in probes for note in probe.notes]
    parts.extend(f"- {note}" for note in notes)
    parts.extend(["", "No ranking and no recommendation is produced here; the repository is chosen by hand.", ""])
    return "\n".join(parts)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe the full git history of candidate repositories."
    )
    parser.add_argument("repos", nargs="*", help="owner/name repositories; defaults to the three candidates")
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    parser.add_argument("--limit-mb", type=int, default=None, help="override MAX_REPO_SIZE_MB")
    args = parser.parse_args(argv)

    repos = tuple(args.repos) or DEFAULT_CANDIDATES
    config = Settings()
    limit = args.limit_mb if args.limit_mb is not None else config.max_repo_size_mb

    probes: list[RepoProbe] = []
    for repo in repos:
        print(f"probing {repo} ...", file=sys.stderr)
        probe = probe_repository(repo, max_repo_size_mb=limit)
        probes.append(probe)

    print(render_revert_table(probes))
    print()
    print(f"Total history scanned: {sum(p.total_commits for p in probes)} commits across {len(probes)} repositories.")
    print()
    print(render_constants_table(probes))
    print()
    print("Definitions")
    print(render_definitions())
    print()
    print("Notes, failures and skips")
    for note in (note for probe in probes for note in probe.notes):
        print(f"- {note}")
    print()
    print("No ranking is produced; the repository is chosen by hand.")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_report(probes), encoding="utf-8")
    print(f"wrote {output}")
    return 0 if all(probe.status == "ok" for probe in probes) else 1


if __name__ == "__main__":
    raise SystemExit(main())