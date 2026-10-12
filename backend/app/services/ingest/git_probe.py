from __future__ import annotations

import ast
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

GITHUB_CLONE_BASE = "https://github.com"
GIT_TIMEOUT_SECONDS = 1800
RECORD_START = "\x02"
RECORD_END = "\x03"
FIELD_SEP = "\x1f"
HISTORY_FORMAT = f"{RECORD_START}%H{FIELD_SEP}%aI{FIELD_SEP}%s{FIELD_SEP}%b{RECORD_END}"
SKIP_DIRECTORIES = frozenset({"test", "tests", "docs", "doc", "examples", "example", "benchmarks", "scripts", "build", "dist", "vendor", "__pycache__"})
SKIP_FILENAMES = frozenset({"setup.py", "conftest.py"})
REVERT_SUBJECT_PREFIX = "Revert "
REVERT_BODY_MARKER = "This reverts commit "
VALUE_DISPLAY_LIMIT = 40
TOP_CONSTANTS = 25
TOP_REVERTS = 10
MIN_CONSTANT_COMMITS = 2
COMMAND_TIMEOUT_SECONDS = 300

METRIC_DEFINITIONS: tuple[tuple[str, str], ...] = (
    (
        "total commits",
        "every commit reachable from the default branch after a full clone.",
    ),
    (
        "reverts",
        "a commit whose subject starts with `Revert `, or whose body contains "
        "`This reverts commit <sha>`. Counted across the whole history, not a recent window.",
    ),
    (
        "reverts touching .py",
        "of those reverts, how many changed at least one `.py` file.",
    ),
    (
        "constants found",
        "module-level UPPER_CASE assignments and annotated assignments in `.py` files under the "
        "main package directory, whose value is a Python literal. `tests/`, `docs/`, "
        "`examples/`, `setup.py` and lowercase names are skipped, as are nested assignments.",
    ),
    (
        "commits touching line",
        "commits returned by `git log -G` for the constant's defining line. This is an upper "
        "bound: it also counts the introduction, file moves and reformatting, not only value changes.",
    ),
    (
        "with PR ref",
        "of those commits, how many reference a pull request, meaning `(#123)` in the subject or "
        "a `Merge pull request #123` subject.",
    ),
)


class GitProbeError(RuntimeError):
    pass


class InvalidRepositoryError(GitProbeError):
    pass


class RepositoryTooLargeError(GitProbeError):
    pass


@dataclass(frozen=True)
class Commit:
    sha: str
    authored_at: str
    subject: str
    body: str
    files: tuple[str, ...] = ()


@dataclass(frozen=True)
class Revert:
    sha: str
    authored_at: str
    subject: str
    target_sha: Optional[str]
    target_subject: Optional[str]
    touches_python: bool

    @property
    def short_sha(self) -> str:
        return self.sha[:7]


@dataclass(frozen=True)
class Constant:
    name: str
    path: str
    value: str

    @property
    def truncated_value(self) -> str:
        return self.value[:VALUE_DISPLAY_LIMIT]


@dataclass(frozen=True)
class ConstantHistory:
    name: str
    path: str
    value: str
    commits: int
    with_pull_request: int
    first_commit_at: Optional[str]
    last_commit_at: Optional[str]

    @property
    def truncated_value(self) -> str:
        return self.value[:VALUE_DISPLAY_LIMIT]


@dataclass
class RepoProbe:
    repo: str
    default_branch: str = ""
    total_commits: int = 0
    revert_count: int = 0
    python_revert_count: int = 0
    reverts: list[Revert] = field(default_factory=list)
    constants_found: int = 0
    constant_histories: list[ConstantHistory] = field(default_factory=list)
    status: str = "ok"
    notes: list[str] = field(default_factory=list)

    @property
    def reverts_touching_python(self) -> int:
        return self.python_revert_count


CommandRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess]


def git_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GIT_ASKPASS"] = "echo"
    return environment


def default_runner(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(args),
        cwd=str(cwd),
        env=git_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=COMMAND_TIMEOUT_SECONDS,
        check=False,
    )


def clone_url(repo: str) -> str:
    owner, name = parse_slug(repo)
    return f"{GITHUB_CLONE_BASE}/{owner}/{name}"


def parse_slug(repo: str) -> tuple[str, str]:
    parts = str(repo).strip().strip("/").split("/")
    if len(parts) != 2 or not all(parts):
        raise InvalidRepositoryError(
            f"{repo!r} is not in owner/name form; only GitHub repositories are supported"
        )
    return parts[0], parts[1]


def directory_size_bytes(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            candidate = Path(root) / name
            try:
                total += candidate.stat().st_size
            except OSError:
                continue
    return total


def clone_repository(
    repo: str,
    destination_root: Path,
    *,
    runner: CommandRunner = default_runner,
    size_limit_mb: Optional[int] = None,
    size_hint_mb: Optional[float] = None,
) -> Path:
    owner, name = parse_slug(repo)
    if size_limit_mb is not None and size_hint_mb is not None and size_hint_mb > size_limit_mb:
        raise RepositoryTooLargeError(
            f"{repo} is about {size_hint_mb:.0f} MB, over the {size_limit_mb} MB limit; not cloning"
        )
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = destination_root / f"{owner}__{name}"
    if destination.exists():
        return destination
    command = [
        "git",
        "-c",
        "submodule.recurse=false",
        "-c",
        "core.hooksPath=",
        "clone",
        "--no-recurse-submodules",
        f"{GITHUB_CLONE_BASE}/{owner}/{name}",
        str(destination),
    ]
    result = runner(command, Path.cwd())
    if result.returncode != 0:
        raise GitProbeError(
            f"cloning {owner}/{name} failed with exit code {result.returncode}: "
            f"{(result.stderr or '').strip()[:200]}"
        )
    if size_limit_mb is not None:
        measured_mb = directory_size_bytes(destination) / (1024 * 1024)
        if measured_mb > size_limit_mb:
            raise RepositoryTooLargeError(
                f"{repo} cloned to {measured_mb:.0f} MB, over the {size_limit_mb} MB limit"
            )
    return destination


def read_history(path: Path, branch: str, *, runner: CommandRunner = default_runner) -> list[Commit]:
    result = runner(
        ["git", "log", f"--format={HISTORY_FORMAT}", "--name-only", branch],
        path,
    )
    if result.returncode != 0:
        raise GitProbeError(f"git log failed: {(result.stderr or '').strip()[:200]}")
    return parse_history(result.stdout or "")


def parse_history(raw: str) -> list[Commit]:
    commits: list[Commit] = []
    for chunk in raw.split(RECORD_START):
        if not chunk.strip():
            continue
        header, _, remainder = chunk.partition(RECORD_END)
        fields = header.split(FIELD_SEP)
        if len(fields) < 4:
            continue
        sha, authored_at, subject, body = fields[0], fields[1], fields[2], FIELD_SEP.join(fields[3:])
        files = tuple(line.strip() for line in remainder.splitlines() if line.strip())
        commits.append(
            Commit(sha=sha, authored_at=authored_at, subject=subject, body=body, files=files)
        )
    return commits


def is_revert(commit: Commit) -> bool:
    if commit.subject.strip().startswith(REVERT_SUBJECT_PREFIX):
        return True
    return REVERT_BODY_MARKER in commit.body


def revert_target_sha(commit: Commit) -> Optional[str]:
    if REVERT_BODY_MARKER not in commit.body:
        return None
    tail = commit.body.split(REVERT_BODY_MARKER, 1)[1].strip()
    words = tail.split()
    if not words:
        return None
    return words[0].rstrip(".") or None


def detect_reverts(commits: Iterable[Commit]) -> list[Revert]:
    known = {commit.sha: commit for commit in commits}
    reverts: list[Revert] = []
    for commit in commits:
        if not is_revert(commit):
            continue
        target_sha = revert_target_sha(commit)
        target = known.get(target_sha) if target_sha else None
        reverts.append(
            Revert(
                sha=commit.sha,
                authored_at=commit.authored_at,
                subject=commit.subject,
                target_sha=target_sha,
                target_subject=target.subject if target else None,
                touches_python=any(name.endswith(".py") for name in commit.files),
            )
        )
    return reverts


def default_branch(path: Path, *, runner: CommandRunner = default_runner) -> str:
    result = runner(["git", "rev-parse", "--abbrev-ref", "HEAD"], path)
    if result.returncode != 0 or not (result.stdout or "").strip():
        raise GitProbeError("could not determine the default branch")
    return (result.stdout or "").strip()


def find_package_directory(root: Path, repo_name: str) -> Optional[Path]:
    package_name = repo_name.replace("-", "_").lower()
    candidates = [root / "src" / package_name, root / package_name]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    try:
        entries = sorted(entry for entry in root.iterdir() if entry.is_dir())
    except OSError:
        return None
    for entry in entries:
        if entry.name.lower() == package_name:
            return entry
    return None


def iter_python_files(package_dir: Path) -> Iterable[Path]:
    for path in sorted(package_dir.rglob("*.py")):
        parts = {part.lower() for part in path.parts}
        if parts & SKIP_DIRECTORIES:
            continue
        if path.name in SKIP_FILENAMES:
            continue
        yield path


def is_upper_constant(name: str) -> bool:
    return name.isupper() and name.strip("_") != ""


def assigned_names(node: ast.stmt) -> list[str]:
    if isinstance(node, ast.Assign):
        names: list[str] = []
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.append(target.id)
        return names
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def literal_value(node: Optional[ast.expr]) -> Optional[str]:
    if node is None:
        return None
    try:
        return repr(ast.literal_eval(node))
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return None


def extract_constants(source: str, relative_path: str) -> list[Constant]:
    tree = ast.parse(source)
    found: list[Constant] = []
    for node in tree.body:
        names = assigned_names(node)
        if not names:
            continue
        value = literal_value(getattr(node, "value", None))
        if value is None:
            continue
        for name in names:
            if is_upper_constant(name):
                found.append(Constant(name=name, path=relative_path, value=value))
    return found


def collect_constants(package_dir: Path, root: Path) -> list[Constant]:
    constants: list[Constant] = []
    for path in iter_python_files(package_dir):
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            relative = path.as_posix()
        constants.extend(extract_constants(source, relative))
    return constants


def has_pull_request_reference(subject: str) -> bool:
    text = subject or ""
    if "Merge pull request #" in text:
        return True
    return "(#" in text and ")" in text


def constant_history(
    path: Path,
    constant: Constant,
    *,
    runner: CommandRunner = default_runner,
) -> ConstantHistory:
    pattern = f"^{constant.name}\\s*(:[^=]+)?="
    result = runner(
        [
            "git",
            "log",
            "--perl-regexp",
            "-G",
            pattern,
            "--format=%H%x09%aI%x09%s",
            "--",
            constant.path,
        ],
        path,
    )
    if result.returncode != 0:
        raise GitProbeError(
            f"git log -G failed for {constant.name}: {(result.stderr or '').strip()[:200]}"
        )
    rows = [line for line in (result.stdout or "").splitlines() if line.strip()]
    dates: list[str] = []
    with_reference = 0
    for row in rows:
        parts = row.split("\t")
        if len(parts) < 3:
            continue
        dates.append(parts[1])
        if has_pull_request_reference(parts[2]):
            with_reference += 1
    return ConstantHistory(
        name=constant.name,
        path=constant.path,
        value=constant.value,
        commits=len(rows),
        with_pull_request=with_reference,
        first_commit_at=min(dates) if dates else None,
        last_commit_at=max(dates) if dates else None,
    )