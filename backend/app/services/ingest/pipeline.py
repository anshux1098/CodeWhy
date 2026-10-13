from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from app.config import Settings
from app.services.ingest.git_collect import (
    collect_documents,
    collect_file_commits,
    extract_issue_numbers,
)
from app.services.ingest.github_objects import (
    IngestionStopped,
    build_issue_query,
    build_pull_request_query,
    build_recent_merged_query,
    chunked,
    normalise_issue,
    normalise_pull_request,
    parse_aliased,
)
from app.services.ingest.github_client import LOW_REMAINING_THRESHOLD
from app.services.ingest.git_probe import (
    clone_repository,
    default_branch,
    parse_slug,
    read_history,
)
from app.services.ingest.targets import IngestTargets
from app.stores.sqlite_cache import SqliteCache

logger = logging.getLogger("codewhy.ingest")


@dataclass
class IngestPlan:
    repo: str
    clone_path: Path
    files: list[str]
    dirs: list[str]
    config_keys: list[str]
    max_prs: int
    max_issues: int
    expected_pull_request_requests: int
    expected_issue_requests: int
    rough_graphql_cost: int

    def render(self) -> str:
        lines = [
            f"repository            : {self.repo}",
            f"clone path            : {self.clone_path}",
            f"target files          : {len(self.files)}",
        ]
        lines += [f"  - {name}" for name in self.files]
        lines += [f"  - {key}" for key in self.config_keys]
        lines += [f"scan directories      : {', '.join(self.dirs) or 'none'}"]
        lines += [
            f"max recency pull reqs : {self.max_prs}",
            f"max recency issues    : {self.max_issues}",
            f"expected PR requests  : {self.expected_pull_request_requests} (batches of 20, target PRs are exempt)",
            f"expected issue reqs   : {self.expected_issue_requests} (batches of 20, target issues are exempt)",
            f"rough GraphQL cost    : ~{self.rough_graphql_cost} points",
            "no network call is made in a dry run",
        ]
        return "\n".join(lines)


def build_plan(
    repo: str,
    targets: IngestTargets,
    settings: Settings,
    clone_root: Path,
    target_pull_requests: int,
    target_issues: int,
) -> IngestPlan:
    owner, name = parse_slug(repo)
    files = targets.all_files()
    from app.services.ingest.github_objects import BATCH_LIMIT
    from math import ceil

    pr_requests = ceil((target_pull_requests + settings.max_ingestion_prs) / BATCH_LIMIT)
    issue_requests = ceil((target_issues + settings.max_ingestion_issues) / BATCH_LIMIT)
    return IngestPlan(
        repo=repo,
        clone_path=clone_root / f"{owner}__{name}",
        files=files,
        dirs=list(targets.dirs),
        config_keys=targets.config_key_names(),
        max_prs=settings.max_ingestion_prs,
        max_issues=settings.max_ingestion_issues,
        expected_pull_request_requests=pr_requests,
        expected_issue_requests=issue_requests,
        rough_graphql_cost=(pr_requests + issue_requests) * 20,
    )


def collect_target_commits(
    clone: Path,
    branch: str,
    targets: IngestTargets,
    cache: SqliteCache,
    repo: str,
) -> tuple[list[Any], set[int]]:
    seen: dict[str, Any] = {}
    pull_requests: set[int] = set()
    for relative in targets.all_files():
        commits = collect_file_commits(clone, relative, branch)
        for commit in commits:
            seen[commit.sha] = commit
            pull_requests.update(commit.pull_requests)
        for commit in commits:
            cache.put_commit(repo, commit.as_row())
            cache.put_commit_file(
                commit.sha,
                {
                    "path": relative,
                    "old_path": None,
                    "status": "M",
                    "diff": commit.diff,
                    "diff_truncated": commit.diff_truncated,
                },
            )
    return list(seen.values()), pull_requests


def fetch_pull_requests(
    client: Any,
    owner: str,
    name: str,
    numbers: Sequence[int],
    cache: SqliteCache,
    repo: str,
    *,
    refresh: bool,
) -> tuple[int, int, int]:
    stored = 0
    fetched = 0
    cost = 0
    pending = [
        number
        for number in numbers
        if refresh or not cache.has_raw("pr", repo, str(number))
    ]
    for batch in chunked(pending):
        _guard_rate_limit(client)
        result = parse_aliased(
            client.query(
                build_pull_request_query(list(batch)),
                {"owner": owner, "name": name},
                tolerate_unresolved=True,
            ),
            "pr",
            list(batch),
        )
        cost += result.cost
        fetched += len(result.items)
        for number, node in result.items.items():
            if cache.put_raw("pr", repo, str(number), normalise_pull_request(node)):
                stored += 1
    return stored, fetched, cost


def fetch_issues(
    client: Any,
    owner: str,
    name: str,
    numbers: Sequence[int],
    cache: SqliteCache,
    repo: str,
    *,
    refresh: bool,
) -> tuple[int, int, int]:
    stored = 0
    fetched = 0
    cost = 0
    pending = [
        number for number in numbers if refresh or not cache.has_raw("issue", repo, str(number))
    ]
    for batch in chunked(pending):
        _guard_rate_limit(client)
        result = parse_aliased(
            client.query(
                build_issue_query(list(batch)),
                {"owner": owner, "name": name},
                tolerate_unresolved=True,
            ),
            "issue",
            list(batch),
        )
        cost += result.cost
        fetched += len(result.items)
        for number, node in result.items.items():
            if cache.put_raw("issue", repo, str(number), normalise_issue(node)):
                stored += 1
    return stored, fetched, cost


def _guard_rate_limit(client: Any) -> None:
    snapshot = getattr(client, "rate_limit", None)
    if snapshot is not None and snapshot.remaining < LOW_REMAINING_THRESHOLD:
        raise IngestionStopped(
            f"rate limit too low to continue: {snapshot.describe()}. "
            "Everything fetched so far is committed to the cache; rerun to resume."
        )


def recent_merged_numbers(client: Any, owner: str, name: str, count: int) -> list[int]:
    payload = client.query(
        build_recent_merged_query(count),
        {"owner": owner, "name": name, "count": count},
    )
    repository = ((payload.get("data") or {}).get("repository") or {})
    connection = repository.get("pullRequests") or {}
    return [node.get("number") for node in (connection.get("nodes") or []) if node.get("number")]


def issue_numbers_from_cache(cache: SqliteCache, repo: str, pull_request_numbers: Sequence[int]) -> set[int]:
    numbers: set[int] = set()
    for number in pull_request_numbers:
        stored = cache.get_raw("pr", repo, str(number))
        if not isinstance(stored, dict):
            continue
        numbers.update(n for n in stored.get("closing_issue_numbers") or [] if n)
        numbers.update(extract_issue_numbers(stored.get("body") or ""))
    return numbers


@dataclass
class IngestSummary:
    repo: str = ""
    run_id: str = ""
    started_at: str = ""
    finished_at: str = ""
    status: str = "ok"
    graphql_cost: int = 0
    commits: int = 0
    commit_files: int = 0
    documents: int = 0
    documents_truncated: int = 0
    pull_requests: int = 0
    pull_requests_fetched: int = 0
    issues: int = 0
    issues_fetched: int = 0
    skips: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "graphql_cost": self.graphql_cost,
            "counts": {
                "commits": self.commits,
                "commit_files": self.commit_files,
                "documents": self.documents,
                "documents_truncated": self.documents_truncated,
                "pull_requests": self.pull_requests,
                "issues": self.issues,
            },
            "fetched_this_run": {
                "pull_requests": self.pull_requests_fetched,
                "issues": self.issues_fetched,
            },
            "skips": self.skips,
            "notes": self.notes,
        }


def run_ingest(
    repo: str,
    targets: IngestTargets,
    settings: Settings,
    *,
    cache: SqliteCache,
    clone_root: Path,
    client: Any,
    max_prs: Optional[int] = None,
    max_issues: Optional[int] = None,
    refresh: bool = False,
) -> IngestSummary:
    owner, name = parse_slug(repo)
    effective_prs = max_prs if max_prs is not None else settings.max_ingestion_prs
    effective_issues = max_issues if max_issues is not None else settings.max_ingestion_issues

    summary = IngestSummary(
        repo=repo,
        run_id=uuid.uuid4().hex,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    cache.start_run(summary.run_id, repo)

    clone = clone_repository(repo, clone_root, size_limit_mb=settings.max_repo_size_mb)
    branch = default_branch(clone)
    summary.notes.append(f"clone branch {branch}")

    target_commits, target_prs = collect_target_commits(clone, branch, targets, cache, repo)
    summary.commits = len(target_commits)
    summary.commit_files = len(targets.all_files())
    logger.info("collected %d commits across %d target files", len(target_commits), len(targets.all_files()))

    history = read_history(clone, branch)
    head_sha = history[0].sha if history else ""
    documents = collect_documents(clone, targets.dirs, head_sha=head_sha)
    for document in documents:
        cache.put_raw("doc", repo, document.path, document.__dict__)
    summary.documents = len(documents)
    summary.documents_truncated = sum(1 for document in documents if document.truncated)

    try:
        _, _, cost = fetch_pull_requests(
            client, owner, name, sorted(target_prs), cache, repo, refresh=refresh
        )
        summary.graphql_cost += cost

        target_issues = issue_numbers_from_cache(cache, repo, sorted(target_prs))
        _, _, cost = fetch_issues(client, owner, name, sorted(target_issues), cache, repo, refresh=refresh)
        summary.graphql_cost += cost

        recent = recent_merged_numbers(client, owner, name, effective_prs)
        skipped = max(0, len(recent) - effective_prs)
        if skipped:
            cache.record_skip(summary.run_id, repo, "pull_request", "max_ingestion_prs", skipped)
            summary.skips.append({"kind": "pull_request", "reason": "max_ingestion_prs", "count": skipped})
        recent_numbers = recent[:effective_prs]
        _, fetched, cost = fetch_pull_requests(
            client, owner, name, recent_numbers, cache, repo, refresh=refresh
        )
        summary.graphql_cost += cost

        recent_issues = issue_numbers_from_cache(cache, repo, recent_numbers)
        issue_list = sorted(recent_issues)[:effective_issues]
        if len(recent_issues) > effective_issues:
            dropped = len(recent_issues) - effective_issues
            cache.record_skip(summary.run_id, repo, "issue", "max_ingestion_issues", dropped)
            summary.skips.append({"kind": "issue", "reason": "max_ingestion_issues", "count": dropped})
        _, fetched_issues, cost = fetch_issues(
            client, owner, name, issue_list, cache, repo, refresh=refresh
        )
        summary.graphql_cost += cost
    except IngestionStopped as stopped:
        summary.status = "stopped_rate_limit"
        summary.notes.append(str(stopped))
        cache.record_skip(summary.run_id, repo, "ingest", "rate_limit", 0)
        summary.skips.append({"kind": "ingest", "reason": "rate_limit", "count": 0})

    summary.pull_requests = cache.count_kind("pr", repo)
    summary.issues = cache.count_kind("issue", repo)
    summary.documents = cache.count_kind("doc", repo)
    summary.finished_at = datetime.now(timezone.utc).isoformat()
    cache.finish_run(summary.run_id, repo, summary.status, summary.graphql_cost, summary.as_dict())
    return summary