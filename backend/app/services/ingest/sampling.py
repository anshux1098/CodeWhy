from __future__ import annotations

import posixpath
import statistics
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Optional, Sequence

STATED_REASON_MIN_CHARS = 200
STATED_REASON_PHRASES = (
    "because",
    "so that",
    "in order to",
    "to avoid",
    "due to",
    "otherwise",
    "trade-off",
)
REVERT_TITLE_PREFIX = "revert"
REVERT_BODY_MARKER = "this reverts commit"
CONFIG_SUFFIXES = (".toml", ".cfg", ".ini", ".yaml", ".yml", ".json")
CONFIG_DOTFILE_PREFIX = ".env"
CONFIG_STEMS = ("settings", "config", "constants", "defaults")
INCIDENT_LABELS = ("bug", "regression", "security", "crash")
INCIDENT_TITLE_MARKERS = ("outage", "incident", "regression", "crash", "deadlock")
LOCKFILE_NAMES = ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock")
LOCKFILE_SUFFIXES = ("-lock.json", ".lock")

COUNT_DEFINITIONS: tuple[tuple[str, str], ...] = (
    (
        "stated reason",
        f"body is at least {STATED_REASON_MIN_CHARS} characters, or contains one of: "
        + ", ".join(f"`{phrase}`" for phrase in STATED_REASON_PHRASES)
        + ". This is a heuristic, not a verified rationale.",
    ),
    (
        "revert",
        "title starts with `Revert`, or body contains `This reverts commit`.",
    ),
    (
        "config-touching",
        "the pull request changes at least one non-lockfile path matching `*.toml`, `*.cfg`, "
        "`*.ini`, `*.yaml`, `*.yml`, `*.json`, `.env*`, `settings*.py`, `config*.py`, "
        "`constants*.py` or `defaults*.py`. Counts pull requests that touch config files, "
        "not confirmed value changes. Lockfiles ending `-lock.json` or `.lock`, and the "
        "names `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `poetry.lock` and "
        "`Pipfile.lock`, are excluded.",
    ),
    (
        "incident-like link",
        "a closing issue carries a label containing `bug`, `regression`, `security` or "
        "`crash`, or its title contains `outage`, `incident`, `regression`, `crash` or "
        "`deadlock`.",
    ),
    (
        "with review",
        "the pull request has at least one review.",
    ),
    (
        "median body",
        "median length of the sampled pull request bodies, in characters.",
    ),
    (
        "sample window",
        "oldest and newest `mergedAt` inside the sample, so the span each row covers is "
        "visible next to the counts. Counts are rates over this window, not over the "
        "repository's whole history.",
    ),
)


def _body(text: Any) -> str:
    return text if isinstance(text, str) else ""


def has_stated_reason(body: Any) -> bool:
    text = _body(body)
    if len(text) >= STATED_REASON_MIN_CHARS:
        return True
    lowered = text.lower()
    return any(phrase in lowered for phrase in STATED_REASON_PHRASES)


def is_revert(title: Any, body: Any) -> bool:
    if _body(title).strip().lower().startswith(REVERT_TITLE_PREFIX):
        return True
    return REVERT_BODY_MARKER in _body(body).lower()


def is_lockfile(path: str) -> bool:
    name = posixpath.basename(str(path)).lower()
    return name in LOCKFILE_NAMES or name.endswith(LOCKFILE_SUFFIXES)


def is_config_path(path: str) -> bool:
    name = posixpath.basename(str(path)).lower()
    if name.startswith(CONFIG_DOTFILE_PREFIX):
        return True
    if any(name.endswith(suffix) for suffix in CONFIG_SUFFIXES):
        return True
    stem = name[:-3] if name.endswith(".py") else name
    return any(stem.startswith(prefix) for prefix in CONFIG_STEMS)


def touches_config(paths: Iterable[str]) -> bool:
    return any(is_config_path(path) and not is_lockfile(path) for path in paths)


def is_incident_like(title: Any, labels: Iterable[str]) -> bool:
    lowered_title = _body(title).lower()
    if any(marker in lowered_title for marker in INCIDENT_TITLE_MARKERS):
        return True
    lowered_labels = [str(label).lower() for label in labels]
    return any(candidate in label for label in lowered_labels for candidate in INCIDENT_LABELS)


def _label_names(issue: Mapping[str, Any]) -> list[str]:
    labels = issue.get("labels") or {}
    nodes = labels.get("nodes") if isinstance(labels, Mapping) else None
    if not isinstance(nodes, list):
        return []
    return [str(node.get("name", "")) for node in nodes if isinstance(node, Mapping)]


def _closing_issues(pull_request: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    references = pull_request.get("closingIssuesReferences") or {}
    nodes = references.get("nodes") if isinstance(references, Mapping) else None
    if not isinstance(nodes, list):
        return []
    return [node for node in nodes if isinstance(node, Mapping)]


def _changed_paths(pull_request: Mapping[str, Any]) -> list[str]:
    files = pull_request.get("files") or {}
    nodes = files.get("nodes") if isinstance(files, Mapping) else None
    if not isinstance(nodes, list):
        return []
    return [str(node.get("path", "")) for node in nodes if isinstance(node, Mapping)]


def _review_count(pull_request: Mapping[str, Any]) -> int:
    reviews = pull_request.get("reviews") or {}
    total = reviews.get("totalCount") if isinstance(reviews, Mapping) else None
    return int(total) if isinstance(total, int) else 0


def _merged_date(value: Any) -> Optional[date]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


@dataclass(frozen=True)
class RepoSample:
    repo: str
    status: str = "ok"
    sampled: int = 0
    merged_total: Optional[int] = None
    oldest_merged_at: Optional[date] = None
    newest_merged_at: Optional[date] = None
    stated_reason: int = 0
    reverts: int = 0
    config_touching: int = 0
    incident_like: int = 0
    with_review: int = 0
    median_body_chars: Optional[int] = None
    language: Optional[str] = None
    default_branch: Optional[str] = None
    disk_kb: Optional[int] = None


def summarise(repo: str, response_payload: Mapping[str, Any]) -> RepoSample:
    data = response_payload.get("data")
    if not isinstance(data, Mapping):
        return RepoSample(repo=repo, status="failed: response contained no data")
    repository = data.get("repository")
    if not isinstance(repository, Mapping) or repository.get("nameWithOwner") is None:
        return RepoSample(repo=repo, status="failed: repository not returned by the API")
    connection = repository.get("pullRequests") or {}
    nodes = connection.get("nodes") if isinstance(connection, Mapping) else None
    pull_requests = [node for node in (nodes or []) if isinstance(node, Mapping)]
    total = connection.get("totalCount") if isinstance(connection, Mapping) else None

    bodies = [_body(node.get("body")) for node in pull_requests]
    merged_dates = [parsed for parsed in (_merged_date(node.get("mergedAt")) for node in pull_requests) if parsed]

    language_node = repository.get("primaryLanguage") or {}
    language = language_node.get("name") if isinstance(language_node, Mapping) else None
    branch_node = repository.get("defaultBranchRef") or {}
    branch = branch_node.get("name") if isinstance(branch_node, Mapping) else None
    disk = repository.get("diskUsage")

    return RepoSample(
        repo=repo,
        status="ok",
        sampled=len(pull_requests),
        merged_total=int(total) if isinstance(total, int) else None,
        oldest_merged_at=min(merged_dates) if merged_dates else None,
        newest_merged_at=max(merged_dates) if merged_dates else None,
        stated_reason=sum(1 for body in bodies if has_stated_reason(body)),
        reverts=sum(1 for node in pull_requests if is_revert(node.get("title"), node.get("body"))),
        config_touching=sum(1 for node in pull_requests if touches_config(_changed_paths(node))),
        incident_like=sum(
            1
            for node in pull_requests
            if any(is_incident_like(issue.get("title"), _label_names(issue)) for issue in _closing_issues(node))
        ),
        with_review=sum(1 for node in pull_requests if _review_count(node) > 0),
        median_body_chars=int(statistics.median(len(body) for body in bodies)) if bodies else None,
        language=language,
        default_branch=branch,
        disk_kb=int(disk) if isinstance(disk, int) else None,
    )


def failure_row(repo: str, reason: str) -> RepoSample:
    return RepoSample(repo=repo, status=reason)


TABLE_COLUMNS: tuple[str, ...] = (
    "repo",
    "sampled",
    "window (oldest..newest)",
    "merged total",
    "stated reason",
    "reverts",
    "config-touching",
    "incident-like",
    "with review",
    "median body",
    "language",
    "branch",
    "disk KB",
    "status",
)


def _window(row: RepoSample) -> str:
    if row.oldest_merged_at is None or row.newest_merged_at is None:
        return "n/a"
    return f"{row.oldest_merged_at} .. {row.newest_merged_at}"


COLUMN_ATTRIBUTES: dict[str, str] = {
    "repo": "repo",
    "sampled": "sampled",
    "merged total": "merged_total",
    "stated reason": "stated_reason",
    "reverts": "reverts",
    "config-touching": "config_touching",
    "incident-like": "incident_like",
    "with review": "with_review",
    "median body": "median_body_chars",
    "language": "language",
    "branch": "default_branch",
    "disk KB": "disk_kb",
    "status": "status",
}


def _cell(row: RepoSample, column: str) -> str:
    if column == "repo":
        return row.repo
    if column == "window (oldest..newest)":
        return _window(row)
    if column == "merged total":
        return "n/a" if row.merged_total is None else str(row.merged_total)
    if column == "median body":
        return "n/a" if row.median_body_chars is None else str(row.median_body_chars)
    if column == "language":
        return row.language or "n/a"
    if column == "branch":
        return row.default_branch or "n/a"
    if column == "disk KB":
        return "n/a" if row.disk_kb is None else str(row.disk_kb)
    if column == "status":
        return row.status
    return str(getattr(row, COLUMN_ATTRIBUTES[column]))


def render_table(rows: Sequence[RepoSample]) -> str:
    header = "| " + " | ".join(TABLE_COLUMNS) + " |"
    divider = "| " + " | ".join("---" for _ in TABLE_COLUMNS) + " |"
    body = ["| " + " | ".join(_cell(row, column) for column in TABLE_COLUMNS) + " |" for row in rows]
    return "\n".join([header, divider, *body])


def render_definitions() -> str:
    return "\n".join(f"- **{name}**: {text}" for name, text in COUNT_DEFINITIONS)