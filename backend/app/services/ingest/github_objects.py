from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

BATCH_LIMIT = 20

@dataclass
class FetchResult:
    items: dict[int, dict[str, Any]] = field(default_factory=dict)
    missing: list[int] = field(default_factory=list)
    cost: int = 0
    requests: int = 0


def chunked(values: Sequence[int], size: int = BATCH_LIMIT) -> Iterable[Sequence[int]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def build_recent_merged_query(count: int) -> str:
    return (
        "query CodeWhyRecent($owner: String!, $name: String!, $count: Int!) {\n"
        "  rateLimit { cost remaining resetAt }\n"
        "  repository(owner: $owner, name: $name) {\n"
        "    pullRequests(states: MERGED, first: $count, "
        "orderBy: {field: CREATED_AT, direction: DESC}) { nodes { number } }\n"
        "  }\n"
        "}\n"
    )


def build_issue_or_pull_request_query(numbers: Sequence[int]) -> str:
    aliases = "\n".join(
        f"    n{number}: issueOrPullRequest(number: {number}) {{ ...CodeWhyIssueOrPullRequest }}"
        for number in numbers
    )
    return (
        "query CodeWhyNumbers($owner: String!, $name: String!) {\n"
        "  rateLimit { cost remaining resetAt }\n"
        "  repository(owner: $owner, name: $name) {\n"
        f"{aliases}\n"
        "  }\n"
        "}\n"
        "fragment CodeWhyIssueOrPullRequest on IssueOrPullRequest {\n"
        "  __typename\n"
        "  ... on PullRequest {\n"
        "    number title body state merged mergedAt closedAt\n"
        "    author { login }\n"
        "    baseRefName\n"
        "    mergeCommit { oid }\n"
        "    reviews(first: 100) { totalCount pageInfo { hasNextPage } nodes { author { login } state body submittedAt } }\n"
        "    reviewThreads(first: 100) { totalCount pageInfo { hasNextPage } nodes { isResolved comments(first: 20) { nodes { author { login } body path createdAt } } } }\n"
        "    comments(first: 100) { totalCount pageInfo { hasNextPage } nodes { author { login } body createdAt } }\n"
        "    commits(first: 100) { totalCount pageInfo { hasNextPage } nodes { commit { oid messageHeadline } } }\n"
        "    files(first: 100) { totalCount pageInfo { hasNextPage } nodes { path } }\n"
        "    closingIssuesReferences(first: 20) { totalCount nodes { number } }\n"
        "  }\n"
        "  ... on Issue {\n"
        "    number title body state closedAt\n"
        "    author { login }\n"
        "    labels(first: 20) { nodes { name } }\n"
        "    comments(first: 30) { totalCount pageInfo { hasNextPage } nodes { author { login } body createdAt } }\n"
        "  }\n"
        "}\n"
    )


def _truncated(connection: Any) -> bool:
    if not isinstance(connection, dict):
        return False
    page_info = connection.get("pageInfo") or {}
    if page_info.get("hasNextPage"):
        return True
    total = connection.get("totalCount")
    nodes = connection.get("nodes")
    if isinstance(total, int) and isinstance(nodes, list) and len(nodes) < total:
        return True
    return False


def normalise_pull_request(node: dict[str, Any]) -> dict[str, Any]:
    reviews = node.get("reviews") or {}
    review_threads = node.get("reviewThreads") or {}
    comments = node.get("comments") or {}
    commits = node.get("commits") or {}
    files = node.get("files") or {}
    closing = node.get("closingIssuesReferences") or {}
    thread_comments = []
    for thread in (review_threads.get("nodes") or []):
        for comment in ((thread.get("comments") or {}).get("nodes") or []):
            thread_comments.append(
                {
                    "author": (comment.get("author") or {}).get("login"),
                    "body": comment.get("body"),
                    "path": comment.get("path"),
                    "createdAt": comment.get("createdAt"),
                }
            )
    return {
        "number": node.get("number"),
        "title": node.get("title"),
        "body": node.get("body"),
        "state": node.get("state"),
        "merged": bool(node.get("merged")),
        "mergedAt": node.get("mergedAt"),
        "closedAt": node.get("closedAt"),
        "author": (node.get("author") or {}).get("login"),
        "base_branch": node.get("baseRefName"),
        "merge_commit": (node.get("mergeCommit") or {}).get("oid"),
        "reviews": [
            {
                "author": (review.get("author") or {}).get("login"),
                "state": review.get("state"),
                "body": review.get("body"),
                "submittedAt": review.get("submittedAt"),
            }
            for review in (reviews.get("nodes") or [])
        ],
        "review_thread_comments": thread_comments,
        "comments": [
            {
                "author": (comment.get("author") or {}).get("login"),
                "body": comment.get("body"),
                "createdAt": comment.get("createdAt"),
            }
            for comment in (comments.get("nodes") or [])
        ],
        "commits": [
            {"sha": (entry.get("commit") or {}).get("oid"), "headline": (entry.get("commit") or {}).get("messageHeadline")}
            for entry in (commits.get("nodes") or [])
        ],
        "files": [entry.get("path") for entry in (files.get("nodes") or [])],
        "closing_issue_numbers": [entry.get("number") for entry in (closing.get("nodes") or [])],
        "truncated": any(
            _truncated(connection)
            for connection in (reviews, review_threads, comments, commits, files, closing)
        ),
    }


def normalise_issue(node: dict[str, Any]) -> dict[str, Any]:
    labels = node.get("labels") or {}
    comments = node.get("comments") or {}
    return {
        "number": node.get("number"),
        "title": node.get("title"),
        "body": node.get("body"),
        "state": node.get("state"),
        "closedAt": node.get("closedAt"),
        "author": (node.get("author") or {}).get("login"),
        "labels": [entry.get("name") for entry in (labels.get("nodes") or [])],
        "comments": [
            {
                "author": (comment.get("author") or {}).get("login"),
                "body": comment.get("body"),
                "createdAt": comment.get("createdAt"),
            }
            for comment in (comments.get("nodes") or [])
        ],
        "comments_truncated": _truncated(comments),
    }


def parse_aliased(payload: dict[str, Any], prefix: str, numbers: Sequence[int]) -> FetchResult:
    result = FetchResult()
    repository = ((payload.get("data") or {}) if isinstance(payload.get("data"), dict) else {}).get(
        "repository"
    )
    rate = ((payload.get("data") or {}) if isinstance(payload.get("data"), dict) else {}).get(
        "rateLimit"
    )
    if isinstance(rate, dict):
        result.cost = int(rate.get("cost") or 0)
    result.requests = 1
    if not isinstance(repository, dict):
        return result
    for number in numbers:
        node = repository.get(f"{prefix}{number}")
        if isinstance(node, dict):
            result.items[number] = node
        else:
            result.missing.append(number)
    return result


KIND_BY_TYPENAME = {"PullRequest": "pr", "Issue": "issue"}


def resolve_kind(node: dict[str, Any]) -> str:
    """Return the cache kind for a resolved object: `pr` or `issue`."""
    typename = node.get("__typename")
    if isinstance(typename, str) and typename in KIND_BY_TYPENAME:
        return KIND_BY_TYPENAME[typename]
    return "pr" if "merged" in node else "issue"


def normalise_resolved(node: dict[str, Any]) -> dict[str, Any]:
    return normalise_pull_request(node) if resolve_kind(node) == "pr" else normalise_issue(node)


class IngestionStopped(RuntimeError):
    pass