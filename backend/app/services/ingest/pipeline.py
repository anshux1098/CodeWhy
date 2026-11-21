from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from app.config import Settings
from app.services.ingest.connectors import detect_incident_from_source
from app.services.ingest.git_collect import (
    collect_documents,
    collect_file_commits,
    extract_issue_numbers,
)
from app.services.ingest.github_objects import (
    IngestionStopped,
    build_discussions_query,
    build_issue_or_pull_request_query,
    build_preflight_query,
    build_recent_merged_query,
    chunked,
    normalise_discussion,
    normalise_resolved,
    parse_aliased,
    resolve_kind,
)
from app.services.ingest.github_client import LOW_REMAINING_THRESHOLD
from app.services.ingest.git_probe import (
    clone_repository,
    default_branch,
    parse_slug,
    read_history,
)
from app.services.ingest.targets import IngestTargets
from app.services.noise import label_repository_noise
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
) -> tuple[list[Any], set[int], list[int]]:
    seen: dict[str, Any] = {}
    pull_requests: set[int] = set()
    numbers: set[int] = set()
    commit_rows: list[dict[str, Any]] = []
    file_rows: list[tuple[str, dict[str, Any]]] = []
    for relative in targets.all_files():
        commits = collect_file_commits(clone, relative, branch, repo=repo)
        for commit in commits:
            seen[commit.sha] = commit
            pull_requests.update(commit.pull_requests)
            numbers.update(commit.pull_requests)
            numbers.update(commit.closing)
            numbers.update(commit.mentions)
            commit_rows.append(commit.as_row())
            file_rows.append(
                (
                    commit.sha,
                    {
                        "path": relative,
                        "old_path": None,
                        "status": "M",
                        "diff": commit.diff,
                        "diff_truncated": commit.diff_truncated,
                    },
                )
            )
    if hasattr(cache, "put_commits_and_files_batch"):
        cache.put_commits_and_files_batch(repo, commit_rows, file_rows)
    else:
        for row in commit_rows:
            cache.put_commit(repo, row)
        for sha, frow in file_rows:
            cache.put_commit_file(sha, frow)
    return list(seen.values()), pull_requests, sorted(numbers)


@dataclass
class FetchOutcome:
    """What one batch of reference lookups actually resolved to, split by kind.

    A number named by `Fixes: #5` may turn out to be an issue while `(#41)` is a pull
    request, so the caller cannot infer the kind from how it asked.
    """

    stored: int = 0
    fetched: int = 0
    fetched_pull_requests: int = 0
    fetched_issues: int = 0
    cost: int = 0


def fetch_references(
    client: Any,
    owner: str,
    name: str,
    numbers: Sequence[int],
    cache: SqliteCache,
    repo: str,
    run_id: str,
    *,
    refresh: bool,
) -> FetchOutcome:
    """Resolve numbers that may be either a pull request or an issue, in one query per batch."""
    outcome = FetchOutcome()
    cost = 0
    pending = [
        number
        for number in numbers
        if refresh or not cache.has_raw("pr", repo, str(number)) and not cache.has_raw("issue", repo, str(number))
    ]
    batches = [list(b) for b in chunked(pending)]
    if not batches:
        return outcome

    def _query_batch(batch_nums: list[int]):
        _guard_rate_limit(client)
        payload = client.query(
            build_issue_or_pull_request_query(batch_nums),
            {"owner": owner, "name": name},
            tolerate_unresolved=True,
        )
        return batch_nums, parse_aliased(payload, "n", batch_nums)

    if len(batches) > 1 and getattr(client, "supports_concurrency", False):
        with ThreadPoolExecutor(max_workers=min(3, len(batches))) as pool:
            batch_results = list(pool.map(_query_batch, batches))
    else:
        batch_results = [_query_batch(b) for b in batches]

    for _batch, result in batch_results:
        cost += result.cost
        for node in result.items.values():
            kind = resolve_kind(node)
            outcome.fetched_issues += kind == "issue"
            outcome.fetched_pull_requests += kind == "pr"
        outcome.fetched += len(result.items)
        for number, node in result.items.items():
            kind = resolve_kind(node)
            normalised = normalise_resolved(node)
            if cache.put_raw(kind, repo, str(number), normalised):
                outcome.stored += 1
            if kind == "pr":
                inc = detect_incident_from_source(
                    repo=repo,
                    source_id=f"pr:{repo}#{number}",
                    title=str(normalised.get("title") or ""),
                    body=str(normalised.get("body") or ""),
                    source_url=f"https://github.com/{repo}/pull/{number}",
                )
                if inc is not None:
                    cache.put_raw("incident", repo, inc.key, {
                        "id": inc.id,
                        "key": inc.key,
                        "severity": inc.severity,
                        "title": inc.title,
                        "source_id": inc.source_id,
                        "source_url": inc.source_url,
                    })
        for number in result.missing:
            cache.record_missing(run_id, repo, "reference", number, "resolved to neither an issue nor a pull request")
    outcome.cost = cost
    return outcome


def preflight_repository(client: Any, owner: str, name: str) -> dict[str, Any]:
    """Run a lightweight GraphQL preflight check before cloning."""
    try:
        payload = client.query(build_preflight_query(), {"owner": owner, "name": name})
        repo_node = ((payload.get("data") or {}).get("repository") or {})
        disk_kb = repo_node.get("diskUsage")
        size_mb = round(float(disk_kb) / 1024.0, 2) if isinstance(disk_kb, (int, float)) else None
        return {
            "exists": bool(repo_node),
            "size_hint_mb": size_mb,
            "has_discussions": bool(repo_node.get("hasDiscussionsEnabled")),
            "default_branch": (repo_node.get("defaultBranchRef") or {}).get("name"),
        }
    except Exception as exc:  # noqa: BLE001 - preflight is advisory, never fatal in tests/mocks
        logger.debug("Preflight check skipped for %s/%s: %s", owner, name, exc)
        return {"exists": True, "size_hint_mb": None, "has_discussions": False, "default_branch": None}


def fetch_discussions(
    client: Any,
    owner: str,
    name: str,
    cache: SqliteCache,
    repo: str,
    *,
    limit: int = 20,
) -> int:
    """Fetch recent GitHub Discussions if enabled on the repository."""
    try:
        payload = client.query(
            build_discussions_query(limit),
            {"owner": owner, "name": name, "first": limit, "after": None},
        )
    except Exception as exc:  # noqa: BLE001 - Discussions may be disabled or unsupported by mock
        logger.debug("Discussions fetch skipped for %s: %s", repo, exc)
        return 0
    repo_node = ((payload.get("data") or {}).get("repository") or {})
    nodes = ((repo_node.get("discussions") or {}).get("nodes") or [])
    stored = 0
    for node in nodes:
        if not isinstance(node, dict) or not node.get("number"):
            continue
        norm = normalise_discussion(node)
        if cache.put_raw("discussion", repo, str(norm["number"]), norm):
            stored += 1
    return stored


def _guard_rate_limit(client: Any) -> None:
    snapshot = getattr(client, "rate_limit", None)
    if snapshot is not None and snapshot.remaining < LOW_REMAINING_THRESHOLD:
        raise IngestionStopped(
            f"rate limit too low to continue: {snapshot.describe()}. "
            "Everything fetched so far is committed to the cache; rerun to resume."
        )


def recent_merged_numbers(client: Any, owner: str, name: str, count: int) -> list[int]:
    numbers: list[int] = []
    cursor: Optional[str] = None
    while len(numbers) < count:
        first = min(100, count - len(numbers))
        variables: dict[str, Any] = {"owner": owner, "name": name, "first": first, "after": cursor}
        payload = client.query(
            build_recent_merged_query(first, cursor),
            variables,
        )
        repository = ((payload.get("data") or {}).get("repository") or {})
        connection = repository.get("pullRequests") or {}
        page_numbers = [node.get("number") for node in (connection.get("nodes") or []) if node.get("number")]
        numbers.extend(page_numbers)
        page_info = connection.get("pageInfo")
        # A server that does not paginate (or a test mock) replies with a
        # single page and no pageInfo; take what it gave and stop.
        if not isinstance(page_info, dict) or not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
        if not cursor:
            break
    return numbers


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
    noise: dict[str, Any] = field(default_factory=dict)

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
            "noise": self.noise,
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
    fast_clone: bool = False,
    on_progress: Optional[Callable[[str, int, int, str], None]] = None,
) -> IngestSummary:
    def _emit(stage: str, current: int, total: int, message: str) -> None:
        if on_progress is not None:
            try:
                on_progress(stage, current, total, message)
            except Exception:  # noqa: BLE001
                pass

    owner, name = parse_slug(repo)
    effective_prs = max_prs if max_prs is not None else settings.max_ingestion_prs
    effective_issues = max_issues if max_issues is not None else settings.max_ingestion_issues

    summary = IngestSummary(
        repo=repo,
        run_id=uuid.uuid4().hex,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    cache.start_run(summary.run_id, repo)

    _emit("cloning", 10, 100, f"Checking and cloning {owner}/{name}...")
    dest_clone = clone_root / f"{owner}__{name}"
    preflight: dict[str, Any] = {"exists": True, "size_hint_mb": None, "has_discussions": False, "default_branch": None}
    if not dest_clone.exists():
        preflight = preflight_repository(client, owner, name)
    clone = clone_repository(
        repo,
        clone_root,
        size_limit_mb=settings.max_repo_size_mb,
        size_hint_mb=preflight.get("size_hint_mb"),
        fast_clone=fast_clone,
    )
    branch = default_branch(clone)
    summary.notes.append(f"clone branch {branch}")

    _emit("commits", 25, 100, f"Collecting git history across {len(targets.all_files())} target files...")
    target_commits, target_prs, all_numbers = collect_target_commits(clone, branch, targets, cache, repo)
    summary.commits = len(target_commits)
    try:
        summary.commit_files = cache.count_commit_files(repo)
    except TypeError:
        summary.commit_files = cache.count_commit_files()
    logger.info("collected %d commits across %d target files", len(target_commits), len(targets.all_files()))

    history = read_history(clone, branch)
    head_sha = history[0].sha if history else ""
    documents = collect_documents(clone, targets.dirs, head_sha=head_sha)
    for document in documents:
        cache.put_raw("doc", repo, document.path, document.__dict__)
    summary.documents = len(documents)
    summary.documents_truncated = sum(1 for document in documents if document.truncated)

    # Stage 3B: Persist config_keys & config_value_changes from target files
    try:
        from app.services.config_keys import (
            build_config_value_history,
            extract_config_keys_from_source,
        )

        all_cfg_keys = []
        for rel_path in targets.all_files():
            full_path = clone / rel_path
            if not full_path.is_file():
                continue
            try:
                src_text = full_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            all_cfg_keys.extend(extract_config_keys_from_source(src_text, rel_path, repo))

        if all_cfg_keys:
            cache.put_config_keys([k.as_dict() for k in all_cfg_keys])
            commit_meta_by_sha = {
                c["sha"]: c for c in cache.iter_commits(repo) if c.get("sha")
            }
            cf_by_path: dict[str, list[dict[str, Any]]] = {}
            for cf in cache.iter_commit_files(repo):
                p = cf.get("path")
                if not p:
                    continue
                sha = cf.get("sha") or ""
                meta = commit_meta_by_sha.get(sha, {})
                cf_by_path.setdefault(p, []).append({
                    "sha": sha,
                    "diff": cf.get("diff") or "",
                    "authored_at": meta.get("authored_at"),
                    "author_name": meta.get("author_name"),
                })

            all_changes = []
            for key_ent in all_cfg_keys:
                file_cfs = cf_by_path.get(key_ent.file_path, [])
                if file_cfs:
                    all_changes.extend(
                        build_config_value_history(
                            repo=repo,
                            key_name=key_ent.name,
                            file_path=key_ent.file_path,
                            commit_files=file_cfs,
                        )
                    )
            if all_changes:
                cache.put_config_value_changes([c.as_dict() for c in all_changes])
    except Exception as exc:  # noqa: BLE001 - config key persistence should never abort ingest
        logger.debug("Config key extraction skipped for %s: %s", repo, exc)

    try:
        _emit("pull_requests", 45, 100, "Fetching target and recent pull requests from GitHub...")
        targets_outcome = fetch_references(
            client, owner, name, sorted(all_numbers), cache, repo, summary.run_id, refresh=refresh
        )
        summary.graphql_cost += targets_outcome.cost
        summary.pull_requests_fetched += targets_outcome.fetched_pull_requests
        summary.issues_fetched += targets_outcome.fetched_issues

        recent = recent_merged_numbers(client, owner, name, effective_prs)
        skipped = max(0, len(recent) - effective_prs)
        if skipped:
            cache.record_skip(
                summary.run_id, repo, "pull_request", "max_ingestion_prs", skipped, effective_prs
            )
            summary.skips.append(
                {"kind": "pull_request", "reason": "max_ingestion_prs", "bound": effective_prs, "count": skipped}
            )
        recent_numbers = recent[:effective_prs]
        recency_outcome = fetch_references(
            client, owner, name, recent_numbers, cache, repo, summary.run_id, refresh=refresh
        )
        summary.graphql_cost += recency_outcome.cost
        summary.pull_requests_fetched += recency_outcome.fetched_pull_requests
        summary.issues_fetched += recency_outcome.fetched_issues

        _emit("issues", 60, 100, "Fetching linked issues and discussions...")
        recent_issues = issue_numbers_from_cache(cache, repo, sorted(all_numbers) + recent_numbers)
        # A pull request body can name another pull request, and that number is a
        # pull request, not an issue. Drop any number already stored as a PR so it
        # is never entered in `missing` as an issue that never existed.
        recent_issues = {number for number in recent_issues if not cache.has_raw("pr", repo, str(number))}
        issue_list = sorted(recent_issues)[:effective_issues]
        if len(recent_issues) > effective_issues:
            dropped = len(recent_issues) - effective_issues
            cache.record_skip(
                summary.run_id, repo, "issue", "max_ingestion_issues", dropped, effective_issues
            )
            summary.skips.append(
                {"kind": "issue", "reason": "max_ingestion_issues", "bound": effective_issues, "count": dropped}
            )
        for number in sorted(recent_issues)[effective_issues:]:
            cache.record_missing(summary.run_id, repo, "issue", number, "over the max_ingestion_issues bound")
        issue_outcome = fetch_references(
            client, owner, name, issue_list, cache, repo, summary.run_id, refresh=refresh
        )
        summary.graphql_cost += issue_outcome.cost
        summary.pull_requests_fetched += issue_outcome.fetched_pull_requests
        summary.issues_fetched += issue_outcome.fetched_issues

        if preflight.get("has_discussions"):
            fetch_discussions(client, owner, name, cache, repo, limit=20)
    except IngestionStopped as stopped:
        summary.status = "stopped_rate_limit"
        summary.notes.append(str(stopped))
        cache.record_skip(summary.run_id, repo, "ingest", "rate_limit", 0)
        summary.skips.append({"kind": "ingest", "reason": "rate_limit", "count": 0})

    summary.noise = label_repository_noise(cache, repo)
    logger.info(
        "labelled noise: %d of %d pull requests flagged",
        summary.noise.get("noisy", 0), summary.noise.get("assessed", 0),
    )

    summary.pull_requests = cache.count_kind("pr", repo)
    summary.issues = cache.count_kind("issue", repo)
    summary.documents = cache.count_kind("doc", repo)
    summary.finished_at = datetime.now(timezone.utc).isoformat()
    cache.finish_run(summary.run_id, repo, summary.status, summary.graphql_cost, summary.as_dict())
    return summary