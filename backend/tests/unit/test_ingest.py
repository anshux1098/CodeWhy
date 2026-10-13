from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Optional

import httpx
import pytest

from app.config import Settings
from app.services.ingest.git_collect import (
    DIFF_CAP_BYTES,
    collect_documents,
    collect_file_commits,
    extract_issue_numbers,
    extract_pull_request_numbers,
    extract_references,
)
from app.services.ingest.github_objects import (
    IngestionStopped,
    build_issue_or_pull_request_query,
    chunked,
    normalise_issue,
    normalise_pull_request,
    parse_aliased,
)
from app.services.ingest.pipeline import build_plan, run_ingest
from app.services.ingest.targets import IngestTargets, load_targets, require_matching_repo
from app.stores.sqlite_cache import SqliteCache, stable_id

TARGETS = IngestTargets(
    repo="acme/netclient",
    files=["pkg/config.py"],
    dirs=["docs/"],
    config_keys=[{"file": "pkg/config.py", "name": "MAX_RETRIES"}],
)


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)


def build_clone(root: Path, repo_name: str = "netclient") -> Path:
    clone_root = root / "clones"
    clone = clone_root / f"acme__{repo_name}"
    (clone / "pkg").mkdir(parents=True, exist_ok=True)
    (clone / "docs").mkdir(parents=True, exist_ok=True)
    (clone / "tests").mkdir(parents=True, exist_ok=True)
    (clone / "pkg" / "config.py").write_text("MAX_RETRIES = 3\n", encoding="utf-8")
    (clone / "docs" / "design.md").write_text("# Design\n\nLong term rationale here.\n", encoding="utf-8")
    (clone / "CHANGES.rst").write_text("Changelog\n", encoding="utf-8")
    (clone / "README.md").write_text("# Readme\n", encoding="utf-8")
    (clone / "tests" / "test_config.py").write_text("SECRET = 1\n", encoding="utf-8")
    (clone / "binary.bin").write_bytes(b"\x00\x01\x02")
    git(clone, "init", "-q", "-b", "main")
    git(clone, "config", "user.email", "dev@example.invalid")
    git(clone, "config", "user.name", "Dev Person")
    git(clone, "add", "-A")
    git(clone, "commit", "-qm", "initial commit")
    (clone / "pkg" / "config.py").write_text("MAX_RETRIES = 6\n", encoding="utf-8")
    git(clone, "commit", "-qam", "Raise the retry cap (#41)")
    return clone_root


class FakeClient:
    def __init__(self, *, remaining: int = 5000, cost: int = 25) -> None:
        from app.services.ingest.github_client import RateLimitSnapshot

        self.rate_limit = RateLimitSnapshot(cost=cost, limit=5000, remaining=remaining, reset_at=None)
        self.set_remaining(remaining)
        self.queries: list[str] = []
        self.pull_requests: dict[int, dict[str, Any]] = {}
        self.issues: dict[int, dict[str, Any]] = {}
        self.recent: list[int] = []

    def set_remaining(self, remaining: int) -> None:
        from dataclasses import replace

        self.rate_limit = replace(self.rate_limit, remaining=remaining)

    def query(
        self,
        document: str,
        variables: Optional[dict[str, Any]] = None,
        tolerate_unresolved: bool = False,
    ) -> dict[str, Any]:
        self.queries.append(document)
        if "pullRequests(states: MERGED" in document:
            numbers = self.recent
            return {
                "data": {
                    "rateLimit": {"cost": 1, "remaining": 4999, "resetAt": None},
                    "repository": {"pullRequests": {"nodes": [{"number": n} for n in numbers]}},
                }
            }
        prefix = "n" if "CodeWhyNumbers" in document else "pr"
        repository = {}
        for number in sorted({*self.pull_requests, *self.issues}):
            key = f"{prefix}{number}"
            if f"{key}:" not in document:
                continue
            if number in self.pull_requests:
                repository[key] = {**self.pull_requests[number], "__typename": "PullRequest"}
            else:
                repository[key] = {**self.issues[number], "__typename": "Issue"}
        return {
            "data": {
                "rateLimit": {"cost": 25, "remaining": 4900, "resetAt": None},
                "repository": repository,
            }
        }


def pull_request_node(number: int, **overrides: Any) -> dict[str, Any]:
    node = {
        "number": number,
        "title": f"Change {number}",
        "body": f"Body for {number}",
        "state": "MERGED",
        "merged": True,
        "mergedAt": "2024-02-11T09:20:00Z",
        "closedAt": "2024-02-11T09:20:00Z",
        "author": {"login": "priya"},
        "baseRefName": "main",
        "mergeCommit": {"oid": "a" * 40},
        "reviews": {
            "totalCount": 1,
            "pageInfo": {"hasNextPage": False},
            "nodes": [{"author": {"login": "marco"}, "state": "APPROVED", "body": "ok", "submittedAt": "2024-02-11"}],
        },
        "reviewThreads": {
            "totalCount": 1,
            "pageInfo": {"hasNextPage": False},
            "nodes": [
                {
                    "isResolved": False,
                    "comments": {
                        "nodes": [
                            {"author": {"login": "lena"}, "body": "why?", "path": "pkg/config.py", "createdAt": "2024-02-11"}
                        ]
                    },
                }
            ],
        },
        "comments": {
            "totalCount": 1,
            "pageInfo": {"hasNextPage": False},
            "nodes": [{"author": {"login": "tom"}, "body": "merged", "createdAt": "2024-02-11"}],
        },
        "commits": {
            "totalCount": 1,
            "pageInfo": {"hasNextPage": False},
            "nodes": [{"commit": {"oid": "a" * 40, "messageHeadline": "headline"}}],
        },
        "files": {
            "totalCount": 1,
            "pageInfo": {"hasNextPage": False},
            "nodes": [{"path": "pkg/config.py"}],
        },
        "closingIssuesReferences": {"totalCount": 1, "nodes": [{"number": 12}]},
    }
    node.update(overrides)
    return node


def settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, github_token="ghp_test_token_value", **overrides)


# Pull request and issue number extraction


def test_pull_request_number_from_a_parenthesised_suffix() -> None:
    assert extract_pull_request_numbers("Raise the retry cap (#41)") == [41]


def test_pull_request_number_from_a_merge_subject() -> None:
    assert extract_pull_request_numbers("Merge pull request #77 from acme/feature") == [77]


def test_several_pull_request_numbers_are_deduplicated() -> None:
    assert extract_pull_request_numbers("Merge pull request #7 from acme/x (#7)") == [7]


def test_an_issue_reference_is_not_a_pull_request_number() -> None:
    assert extract_pull_request_numbers("Fixes #5") == []


def test_a_bare_number_is_not_a_pull_request_number() -> None:
    assert extract_pull_request_numbers("bump to 6") == []


def test_issue_numbers_are_extracted_from_bodies() -> None:
    assert extract_issue_numbers("Closes #5 and relates to #7") == [5, 7]


# GraphQL shape


def test_batches_never_exceed_twenty() -> None:
    batches = list(chunked(list(range(1, 46))))
    assert all(len(batch) <= 20 for batch in batches)
    assert sum(len(batch) for batch in batches) == 45


def test_queries_use_one_alias_per_number() -> None:
    query = build_issue_or_pull_request_query([11, 12])
    assert "n11: issueOrPullRequest(number: 11)" in query
    assert "n12: issueOrPullRequest(number: 12)" in query
    assert "pullRequest(number:" not in query
    assert "issue(number:" not in query


FRAGMENT_HEADER = "fragment CodeWhyIssueOrPullRequest on IssueOrPullRequest {"


def _fragment_sections() -> tuple[str, str, str]:
    """Return the interface level text, the PullRequest section and the Issue section."""
    fragment = build_issue_or_pull_request_query([1]).split(FRAGMENT_HEADER, 1)[1]
    pull_part = fragment.split("... on PullRequest {", 1)[1].split("... on Issue {", 1)[0]
    return fragment.split("... on ", 1)[0], pull_part, fragment.split("... on Issue {", 1)[1]


def test_only_typename_is_selected_directly_on_the_interface() -> None:
    """IssueOrPullRequest exposes no merged, labels or author fields, so they must be
    selected inside inline fragments. GitHub rejects the whole query otherwise, and a
    fake client cannot detect it."""
    interface_level, _, _ = _fragment_sections()
    selected = [line.strip() for line in interface_level.splitlines() if line.strip()]
    assert selected == ["__typename"]


def test_type_specific_fields_are_inside_their_own_inline_fragment() -> None:
    _, pull_part, issue_part = _fragment_sections()
    for field in ("merged", "mergedAt", "mergeCommit", "reviews", "reviewThreads", "files", "closingIssuesReferences"):
        assert field in pull_part, field
    for field in ("merged", "mergeCommit", "reviews", "closingIssuesReferences"):
        assert field not in issue_part, field
    assert "labels" in issue_part
    assert "labels" not in pull_part


def test_truncation_is_flagged_when_a_connection_has_more_pages() -> None:
    node = normalise_pull_request(
        pull_request_node(1, reviews={"totalCount": 300, "pageInfo": {"hasNextPage": True}, "nodes": []})
    )
    assert node["truncated"] is True


def test_truncation_is_not_flagged_when_everything_fit() -> None:
    assert normalise_pull_request(pull_request_node(1))["truncated"] is False


def test_review_thread_comments_are_flattened_with_their_path() -> None:
    node = normalise_pull_request(pull_request_node(1))
    assert node["review_thread_comments"][0]["path"] == "pkg/config.py"
    assert node["reviews"][0]["author"] == "marco"


def test_issue_normalisation_keeps_labels_and_flags_comment_truncation() -> None:
    issue = normalise_issue(
        {
            "number": 12,
            "title": "Broken",
            "body": "b",
            "state": "CLOSED",
            "closedAt": "2024-01-01T00:00:00Z",
            "author": {"login": "tom"},
            "labels": {"nodes": [{"name": "bug"}]},
            "comments": {"totalCount": 90, "pageInfo": {"hasNextPage": True}, "nodes": []},
        }
    )
    assert issue["labels"] == ["bug"]
    assert issue["comments_truncated"] is True


def test_missing_aliased_objects_are_reported() -> None:
    result = parse_aliased({"data": {"repository": {"pr1": {"number": 1}}, "rateLimit": {"cost": 3}}}, "pr", [1, 2])
    assert 1 in result.items
    assert result.missing == [2]
    assert result.cost == 3


# Git collection


def test_pull_request_numbers_are_collected_from_commits(tmp_path: Path) -> None:
    clone_root = build_clone(tmp_path)
    commits = collect_file_commits(clone_root / "acme__netclient", "pkg/config.py", "main")
    assert {number for commit in commits for number in commit.pull_requests} == {41}


def test_commits_never_capture_the_author_email(tmp_path: Path) -> None:
    clone_root = build_clone(tmp_path)
    commits = collect_file_commits(clone_root / "acme__netclient", "pkg/config.py", "main")
    rendered = json.dumps([commit.as_row() for commit in commits], default=str)
    assert "dev@example.invalid" not in rendered
    assert "@example.invalid" not in rendered
    assert "Dev Person" in rendered


def test_a_renamed_target_file_is_followed(tmp_path: Path) -> None:
    clone = build_clone(tmp_path) / "acme__netclient"
    git(clone, "mv", "pkg/config.py", "pkg/renamed.py")
    git(clone, "commit", "-qm", "Rename the config module (#55)")
    (clone / "pkg" / "renamed.py").write_text("MAX_RETRIES = 9\n", encoding="utf-8")
    git(clone, "commit", "-qam", "Raise again (#56)")
    commits = collect_file_commits(clone, "pkg/renamed.py", "main")
    subjects = [commit.subject for commit in commits]
    assert "Raise the retry cap (#41)" in subjects
    assert "Rename the config module (#55)" in subjects


def test_the_diff_cap_sets_the_truncated_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.ingest.git_collect as collector

    monkeypatch.setattr(collector, "DIFF_CAP_BYTES", 120)
    clone_root = build_clone(tmp_path)
    commits = collect_file_commits(clone_root / "acme__netclient", "pkg/config.py", "main")
    assert any(commit.diff_truncated for commit in commits)
    assert all(len(commit.diff.encode("utf-8")) <= 120 for commit in commits if commit.diff_truncated)


def test_documents_only_include_allowed_paths_and_respect_the_size_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.ingest.git_collect as collector

    clone = build_clone(tmp_path) / "acme__netclient"
    (clone / "docs" / "big.md").write_text("x" * (600 * 1024), encoding="utf-8")
    (clone / "docs" / "image.png").write_bytes(b"\x89PNG\r\n")
    (clone / "tests" / "notes.md").write_text("not scanned", encoding="utf-8")
    git(clone, "add", "-A")
    git(clone, "commit", "-qm", "docs")
    monkeypatch.setattr(collector, "DOC_MAX_BYTES", 1024)
    documents = collect_documents(clone, ["docs/"], head_sha="a" * 40)
    paths = {document.path for document in documents}
    assert "docs/design.md" in paths
    assert "docs/big.md" in paths
    assert "README.md" in paths
    assert "CHANGES.rst" in paths
    assert not any(path.endswith(".png") for path in paths)
    assert not any(path.startswith("tests/") for path in paths)
    big = next(document for document in documents if document.path == "docs/big.md")
    assert big.truncated is True
    assert len(big.content) <= 1024


# Targets validation


def test_targets_reject_a_repo_mismatch() -> None:
    with pytest.raises(ValueError) as excinfo:
        require_matching_repo(TARGETS, "other/repo")
    assert "must agree" in str(excinfo.value)


def test_targets_accept_a_matching_repo() -> None:
    require_matching_repo(TARGETS, "acme/netclient")


def test_targets_reject_a_config_key_outside_files() -> None:
    with pytest.raises(ValueError):
        IngestTargets(repo="a/b", config_keys=[{"file": "src/other.py", "name": "X"}])


def test_targets_reject_an_empty_target_set() -> None:
    with pytest.raises(ValueError):
        IngestTargets(repo="a/b")


def test_targets_reject_unknown_fields() -> None:
    with pytest.raises(ValueError):
        IngestTargets(repo="a/b", files=["a.py"], hardcoded=True)


def test_targets_file_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "t.json"
    path.write_text(json.dumps(TARGETS.model_dump()), encoding="utf-8")
    assert load_targets(path).repo == "acme/netclient"


def test_test_bed_targets_file_exists_and_is_marked_as_urllib3() -> None:
    loaded = load_targets(Path("targets/urllib3__urllib3.json"))
    assert loaded.repo == "urllib3/urllib3"
    assert "src/urllib3/connectionpool.py" in loaded.files


# Cache


def test_stable_ids_follow_the_documented_shapes() -> None:
    assert stable_id("pr", "a/b", "7") == "pr:a/b#7"
    assert stable_id("issue", "a/b", "7") == "issue:a/b#7"
    assert stable_id("commit", "a/b", "abc") == "commit:abc"
    assert stable_id("doc", "a/b", "docs/x.md") == "doc:a/b:docs/x.md"


def test_put_raw_is_idempotent_when_content_is_unchanged(tmp_path: Path) -> None:
    with SqliteCache(tmp_path / "c.sqlite3") as cache:
        assert cache.put_raw("pr", "a/b", "7", {"x": 1}) is True
        assert cache.put_raw("pr", "a/b", "7", {"x": 1}) is False
        assert cache.count_kind("pr", "a/b") == 1


def test_put_raw_rewrites_when_content_changes(tmp_path: Path) -> None:
    with SqliteCache(tmp_path / "c.sqlite3") as cache:
        cache.put_raw("pr", "a/b", "7", {"x": 1})
        assert cache.put_raw("pr", "a/b", "7", {"x": 2}) is True
        assert cache.get_raw("pr", "a/b", "7") == {"x": 2}
        assert cache.count_kind("pr", "a/b") == 1


def test_commits_are_inserted_once_per_sha(tmp_path: Path) -> None:
    with SqliteCache(tmp_path / "c.sqlite3") as cache:
        row = {"sha": "a" * 40, "subject": "s", "pull_requests": [1], "parent_shas": []}
        assert cache.put_commit("a/b", row) is True
        assert cache.put_commit("a/b", row) is False
        assert cache.count("commits", "a/b") == 1


def test_commit_files_are_upserted(tmp_path: Path) -> None:
    with SqliteCache(tmp_path / "c.sqlite3") as cache:
        cache.put_commit_file("a" * 40, {"path": "p.py", "status": "M", "diff": "x"})
        cache.put_commit_file("a" * 40, {"path": "p.py", "status": "M", "diff": "y", "diff_truncated": True})
        rows = cache.commit_files_for("p.py")
        assert len(rows) == 1
        assert rows[0]["diff_truncated"] == 1


# Pipeline


def test_ingesting_twice_creates_no_duplicates_and_fetches_nothing_cached(tmp_path: Path) -> None:
    clone_root = build_clone(tmp_path)
    client = FakeClient()
    client.pull_requests[41] = pull_request_node(41)
    client.issues[12] = {"number": 12, "title": "Broken", "body": "b", "state": "CLOSED", "labels": {"nodes": []}, "comments": {"totalCount": 0, "pageInfo": {"hasNextPage": False}, "nodes": []}}
    with SqliteCache(tmp_path / "c.sqlite3") as cache:
        first = run_ingest(
            "acme/netclient", TARGETS, settings(), cache=cache, clone_root=clone_root,
            client=client, max_prs=5, max_issues=5,
        )
        first_counts = (cache.count("commits", "acme/netclient"), cache.count_kind("pr", "acme/netclient"), cache.count_kind("issue", "acme/netclient"))
        detail_after_first = len([q for q in client.queries if "CodeWhyRecent" not in q])
        second = run_ingest(
            "acme/netclient", TARGETS, settings(), cache=cache, clone_root=clone_root,
            client=client, max_prs=5, max_issues=5,
        )
        second_counts = (cache.count("commits", "acme/netclient"), cache.count_kind("pr", "acme/netclient"), cache.count_kind("issue", "acme/netclient"))
        detail_after_second = len([q for q in client.queries if "CodeWhyRecent" not in q])
    assert first.status == "ok"
    assert second.status == "ok"
    assert first_counts == second_counts
    assert first_counts[1] == 1
    assert detail_after_first > 0
    assert detail_after_second == detail_after_first


def test_target_pull_requests_are_exempt_from_the_recency_bound(tmp_path: Path) -> None:
    clone_root = build_clone(tmp_path)
    client = FakeClient()
    client.pull_requests[41] = pull_request_node(41)
    client.recent = list(range(100, 110))
    for number in client.recent:
        client.pull_requests[number] = pull_request_node(number)
    with SqliteCache(tmp_path / "c.sqlite3") as cache:
        summary = run_ingest(
            "acme/netclient", TARGETS, settings(), cache=cache, clone_root=clone_root,
            client=client, max_prs=3, max_issues=5,
        )
        stored_target = cache.has_raw("pr", "acme/netclient", "41")
        stored_recent = cache.count_kind("pr", "acme/netclient")
        skips = [dict(row) for row in cache.skips("acme/netclient")]
    assert stored_target is True
    assert stored_recent == 4
    assert any(skip["kind"] == "pull_request" and skip["reason"] == "max_ingestion_prs" for skip in skips)
    assert summary.skips


def test_a_rate_limit_stop_leaves_a_consistent_cache_and_the_next_run_resumes(tmp_path: Path) -> None:
    clone_root = build_clone(tmp_path)
    client = FakeClient()
    client.set_remaining(10)
    client.pull_requests[41] = pull_request_node(41)
    with SqliteCache(tmp_path / "c.sqlite3") as cache:
        stopped = run_ingest(
            "acme/netclient", TARGETS, settings(), cache=cache, clone_root=clone_root,
            client=client, max_prs=5, max_issues=5,
        )
        commits_after_stop = cache.count("commits", "acme/netclient")
        runs = [dict(row) for row in cache.runs("acme/netclient")]
        client.set_remaining(5000)
        client.pull_requests[200] = pull_request_node(200)
        client.recent = [200]
        resumed = run_ingest(
            "acme/netclient", TARGETS, settings(), cache=cache, clone_root=clone_root,
            client=client, max_prs=5, max_issues=5,
        )
        assert cache.count("commits", "acme/netclient") == commits_after_stop
    assert stopped.status == "stopped_rate_limit"
    assert stopped.commits > 0
    assert any(run["status"] == "stopped_rate_limit" for run in runs)
    assert resumed.status == "ok"
    assert resumed.pull_requests >= 1


def test_no_email_reaches_the_cache_or_summary(tmp_path: Path) -> None:
    clone_root = build_clone(tmp_path)
    client = FakeClient()
    client.pull_requests[41] = pull_request_node(41)
    with SqliteCache(tmp_path / "c.sqlite3") as cache:
        summary = run_ingest(
            "acme/netclient", TARGETS, settings(), cache=cache, clone_root=clone_root,
            client=client, max_prs=2, max_issues=2,
        )
        blob = json.dumps(summary.as_dict(), default=str)
        for row in cache._connection.execute("SELECT * FROM commits"):
            blob += json.dumps({k: row[k] for k in row.keys()}, default=str)
        for row in cache._connection.execute("SELECT * FROM raw_objects"):
            blob += row["json"]
    assert "dev@example.invalid" not in blob
    assert "@example.invalid" not in blob


def test_dry_run_plan_makes_no_network_call(tmp_path: Path) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("dry run must not touch the network")

    plan = build_plan("acme/netclient", TARGETS, settings(), tmp_path / "clones", 0, 0)
    rendered = plan.render()
    assert "no network call" in rendered
    assert "pkg/config.py" in rendered
    del explode


def test_dry_run_cli_makes_no_network_call(tmp_path: Path) -> None:
    import sys

    from scripts import ingest as ingest_cli

    targets_path = tmp_path / "t.json"
    targets_path.write_text(json.dumps(TARGETS.model_dump()), encoding="utf-8")
    monkey = sys.modules.get("app.services.ingest.github_client")
    exit_code = ingest_cli.main(
        [
            "--repo", "acme/netclient",
            "--targets", str(targets_path),
            "--dry-run",
            "--database", str(tmp_path / "c.sqlite3"),
        ]
    )
    assert exit_code == 0
    assert monkey is not None


def test_documents_are_stored_under_stable_ids(tmp_path: Path) -> None:
    clone_root = build_clone(tmp_path)
    client = FakeClient()
    client.pull_requests[41] = pull_request_node(41)
    with SqliteCache(tmp_path / "c.sqlite3") as cache:
        run_ingest(
            "acme/netclient", TARGETS, settings(), cache=cache, clone_root=clone_root,
            client=client, max_prs=2, max_issues=2,
        )
        assert cache.has_raw("doc", "acme/netclient", "docs/design.md") is True
        assert cache.has_raw("doc", "acme/netclient", "README.md") is True
        assert cache.has_raw("doc", "acme/netclient", "tests/test_config.py") is False


def test_ingestion_rejects_a_targets_file_for_another_repo(tmp_path: Path) -> None:
    from scripts import ingest as ingest_cli

    targets_path = tmp_path / "t.json"
    targets_path.write_text(json.dumps(TARGETS.model_dump()), encoding="utf-8")
    exit_code = ingest_cli.main(
        ["--repo", "other/repo", "--targets", str(targets_path), "--dry-run"]
    )
    assert exit_code == 2


def test_url_and_size_refusals_still_hold(tmp_path: Path) -> None:
    from app.services.ingest.git_probe import (
        InvalidRepositoryError,
        RepositoryTooLargeError,
        clone_repository,
    )

    with pytest.raises(InvalidRepositoryError):
        clone_repository("not-a-repo", tmp_path / "clones")
    with pytest.raises(RepositoryTooLargeError):
        clone_repository(
            "acme/big", tmp_path / "clones",
            size_limit_mb=1, size_hint_mb=9000.0,
        )


def test_aliased_query_with_nothing_returned_is_not_an_error() -> None:
    result = parse_aliased({"data": {"repository": {}, "rateLimit": {"cost": 1}}}, "pr", [1])
    assert result.items == {}
    assert result.missing == [1]
    assert result.cost == 1

# Part A: every collected commit has a commit_files row with a diff


def test_every_collected_commit_has_a_commit_files_row_with_a_diff(tmp_path: Path) -> None:
    clone_root = build_clone(tmp_path)
    client = FakeClient()
    client.pull_requests[41] = pull_request_node(41)
    with SqliteCache(tmp_path / "c.sqlite3") as cache:
        run_ingest(
            "acme/netclient", TARGETS, settings(), cache=cache, clone_root=clone_root,
            client=client, max_prs=2, max_issues=2,
        )
        commits = [row["sha"] for row in cache._connection.execute("SELECT sha FROM commits")]
        assert commits
        for sha in commits:
            rows = cache._connection.execute(
                "SELECT path, diff, diff_truncated FROM commit_files WHERE sha = ?", (sha,)
            ).fetchall()
            assert rows, f"commit {sha} has no commit_files row"
            for row in rows:
                assert row["diff"], f"commit {sha} path {row['path']} stored an empty diff"


def test_commit_files_row_count_is_reported_as_rows_not_target_files(tmp_path: Path) -> None:
    clone_root = build_clone(tmp_path)
    client = FakeClient()
    client.pull_requests[41] = pull_request_node(41)
    with SqliteCache(tmp_path / "c.sqlite3") as cache:
        summary = run_ingest(
            "acme/netclient", TARGETS, settings(), cache=cache, clone_root=clone_root,
            client=client, max_prs=2, max_issues=2,
        )
        rows = cache._connection.execute("SELECT COUNT(*) AS n FROM commit_files").fetchone()["n"]
    assert summary.commit_files == rows
    assert summary.commit_files >= summary.commits


def test_skip_rows_record_the_bound_actually_used(tmp_path: Path) -> None:
    clone_root = build_clone(tmp_path)
    client = FakeClient()
    client.pull_requests[41] = pull_request_node(41)
    client.recent = list(range(100, 130))
    for number in client.recent:
        client.pull_requests[number] = pull_request_node(number)
    with SqliteCache(tmp_path / "c.sqlite3") as cache:
        run_ingest(
            "acme/netclient", TARGETS, settings(), cache=cache, clone_root=clone_root,
            client=client, max_prs=4, max_issues=7,
        )
        rows = [dict(row) for row in cache.skips("acme/netclient")]
    pr_row = next(row for row in rows if row["kind"] == "pull_request")
    assert pr_row["bound"] == 4


def test_numbers_that_resolve_to_neither_kind_are_recorded_missing(tmp_path: Path) -> None:
    clone_root = build_clone(tmp_path)
    client = FakeClient()
    client.pull_requests[41] = pull_request_node(41)
    with SqliteCache(tmp_path / "c.sqlite3") as cache:
        run_ingest(
            "acme/netclient", TARGETS, settings(), cache=cache, clone_root=clone_root,
            client=client, max_prs=2, max_issues=2,
        )
        missing = [dict(row) for row in cache.missing("acme/netclient")]
    assert all("neither" in row["reason"] or "no pull request" in row["reason"] for row in missing)


def test_a_number_stored_as_an_issue_is_counted_as_an_issue(tmp_path: Path) -> None:
    from app.services.ingest.pipeline import fetch_references

    client = FakeClient()
    client.issues[12] = {
        "number": 12, "title": "Broken", "body": "b", "state": "CLOSED",
        "labels": {"nodes": []},
        "comments": {"totalCount": 0, "pageInfo": {"hasNextPage": False}, "nodes": []},
    }
    with SqliteCache(tmp_path / "c.sqlite3") as cache:
        fetch_references(client, "acme", "netclient", [12], cache, "acme/netclient", "run1", refresh=False)
        assert cache.count_kind("issue", "acme/netclient") == 1
        assert cache.count_kind("pr", "acme/netclient") == 0
        assert cache.has_raw("issue", "acme/netclient", "12") is True


# Part A4: the issue reference regex


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Fixes #1234", [1234]),
        ("closes #7 and references #8", [7, 8]),
        ("a plain #42", [42]),
        ("version 1.2#3 is not a reference", []),
        ("hex colour #ff00ff is not a reference", []),
        ("n@pytest.mark.skipif has no reference", []),
        ("see path/to/file.py#12", []),
        ("word#9", []),
        ("`#77` inside inline code is ignored", []),
        ("```\n#88 inside a fenced block\n```", []),
        ("#1234567 is too long", []),
    ],
)
def test_issue_reference_extraction(text: str, expected: list[int]) -> None:
    assert extract_issue_numbers(text) == expected


# Part B: commit trailers


def test_fixes_trailer_is_a_closing_reference() -> None:
    references = extract_references("Body text\n\nFixes: #1234", "a/b")
    assert references.closing == [1234]


def test_closes_and_resolves_trailers_are_closing_references() -> None:
    assert extract_references("Closes: #1", "a/b").closing == [1]
    assert extract_references("Resolves: #2", "a/b").closing == [2]


def test_references_and_related_trailers_are_mentions() -> None:
    assert extract_references("References: #5", "a/b").mentions == [5]
    assert extract_references("Related: #6", "a/b").mentions == [6]


def test_pull_request_trailer_for_the_same_repository_yields_a_pull_request() -> None:
    references = extract_references(
        "Pull-request: https://github.com/a/b/pull/99\n", "a/b"
    )
    assert references.pull_requests == [99]


def test_pull_request_trailer_for_another_repository_is_ignored() -> None:
    references = extract_references(
        "Pull-request: https://github.com/other/repo/pull/99\n", "a/b"
    )
    assert references.pull_requests == []


def test_pull_request_sha_and_change_id_are_stored_as_trailers() -> None:
    references = extract_references(
        "Pull-request-sha: abc123\nChange-Id: Ideadbeefcafe\n", "a/b"
    )
    assert references.trailers["Change-Id"] == ["Ideadbeefcafe"]
    assert references.trailers["Pull-request-sha"] == ["abc123"]


def test_a_trailer_line_inside_the_body_is_not_a_trailer() -> None:
    message = "We thought about Fixes: #99 here.\n\nChange-Id: Iabc\n"
    references = extract_references(message, "a/b")
    assert references.closing == []
    assert references.trailers == {"Change-Id": ["Iabc"]}


def test_multiple_trailers_are_all_captured() -> None:
    references = extract_references(
        "Fixes: #1\nReferences: #2\nChange-Id: Iabc\n", "a/b"
    )
    assert references.closing == [1]
    assert references.mentions == [2]


def test_a_commit_with_no_trailers_yields_nothing() -> None:
    references = extract_references("Just a normal commit message\n\nWith a body.\n", "a/b")
    assert references.trailers == {}
    assert references.closing == []
    assert references.mentions == []


def test_trailers_reach_the_commit_row(tmp_path: Path) -> None:
    clone = build_clone(tmp_path) / "acme__netclient"
    (clone / "pkg" / "config.py").write_text("MAX_RETRIES = 9\n", encoding="utf-8")
    git(clone, "commit", "-qam", "Raise the cap\n\nBecause the mobile client times out.\n\nFixes: #77\nChange-Id: Iabc123")
    commits = collect_file_commits(clone, "pkg/config.py", "main", repo="acme/netclient")
    top = commits[0]
    assert top.closing == [77]
    assert top.trailers["Change-Id"] == ["Iabc123"]
    assert top.as_row()["trailers"]["Change-Id"] == ["Iabc123"]


def test_trailer_pull_request_is_stored_on_the_commit_row(tmp_path: Path) -> None:
    clone = build_clone(tmp_path) / "acme__netclient"
    (clone / "pkg" / "config.py").write_text("MAX_RETRIES = 9\n", encoding="utf-8")
    git(clone, "commit", "-qam", "Raise the cap\n\nPull-request: https://github.com/acme/netclient/pull/314")
    commits = collect_file_commits(clone, "pkg/config.py", "main", repo="acme/netclient")
    assert commits[0].pull_requests == [314]


def test_an_existing_cache_file_gains_the_new_columns(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "old.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        "CREATE TABLE commits ("
        "sha TEXT PRIMARY KEY, repo TEXT NOT NULL, authored_at TEXT, committed_at TEXT,"
        "author_name TEXT, subject TEXT, message TEXT, parent_shas TEXT, pull_requests TEXT);"
"CREATE TABLE skips ("
        "id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, repo TEXT NOT NULL, kind TEXT NOT NULL,"
        "reason TEXT NOT NULL, count INTEGER NOT NULL, created_at TEXT NOT NULL);"
    )
    connection.commit()
    connection.close()

    with SqliteCache(path) as cache:
        columns = {
            row["name"]
            for row in cache._connection.execute("PRAGMA table_info(commits)")
        }
        assert {"closing", "mentions", "trailers"} <= columns
        skip_columns = {row["name"] for row in cache._connection.execute("PRAGMA table_info(skips)")}
        assert "bound" in skip_columns
        cache.record_skip("run1", "acme/netclient", "pull_request", "max_ingestion_prs", 3, 4)
        stored = cache.skips("acme/netclient")[0]
        assert stored["bound"] == 4


# Part C: the read only cache inspector


def test_inspect_cache_reports_counts_without_writing(tmp_path: Path) -> None:
    from scripts.inspect_cache import inspect

    clone_root = build_clone(tmp_path)
    client = FakeClient()
    client.pull_requests[41] = pull_request_node(41)
    path = tmp_path / "c.sqlite3"
    with SqliteCache(path) as cache:
        run_ingest(
            "acme/netclient", TARGETS, settings(), cache=cache, clone_root=clone_root,
            client=client, max_prs=2, max_issues=2,
        )

    digest_before = hashlib.sha256(path.read_bytes()).hexdigest()
    with SqliteCache(path, read_only=True) as cache:
        schema_before = cache._connection.execute("PRAGMA schema_version").fetchone()[0]
        report = inspect(cache, "acme/netclient")
        schema_after = cache._connection.execute("PRAGMA schema_version").fetchone()[0]

    counts = report["counts"]
    assert counts["commits"] == 2
    assert counts["commit_files"] == cache_count_files(path)
    assert counts["commit_files_with_empty_diff"] == 0
    assert counts["pull_requests"] == 1
    assert counts["issues"] == 0
    # total_changes does not count DDL, so the file digest is the real check.
    assert schema_after == schema_before, "inspect must not change the schema"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest_before


def test_inspect_cache_does_not_create_or_migrate_the_file(tmp_path: Path) -> None:
    """A read only open must not add tables, so an old cache is left exactly as found."""
    import sqlite3

    from scripts.inspect_cache import inspect

    path = tmp_path / "old.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        "CREATE TABLE commits ("
        "sha TEXT PRIMARY KEY, repo TEXT NOT NULL, authored_at TEXT, committed_at TEXT,"
        "author_name TEXT, subject TEXT, message TEXT, parent_shas TEXT, pull_requests TEXT);"
        "INSERT INTO commits (sha, repo, subject) VALUES ('abc1234', 'acme/netclient', 'Fixes: #5');"
    )
    connection.commit()
    connection.close()
    digest_before = hashlib.sha256(path.read_bytes()).hexdigest()

    with SqliteCache(path, read_only=True) as cache:
        report = inspect(cache, "acme/netclient")

    tables = {
        row[0]
        for row in sqlite3.connect(path).execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "missing" not in tables, "inspect must not add tables"
    assert "commit_files" not in tables
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest_before
    assert report["counts"]["commits"] == 1
    assert report["missing_references"] == []


def cache_count_files(path: Path) -> int:
    import sqlite3

    connection = sqlite3.connect(path)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM commit_files").fetchone()[0])
    finally:
        connection.close()


def test_inspect_cache_can_filter_by_repo(tmp_path: Path) -> None:
    from scripts.inspect_cache import inspect

    clone_root = build_clone(tmp_path)
    client = FakeClient()
    client.pull_requests[41] = pull_request_node(41)
    path = tmp_path / "c.sqlite3"
    with SqliteCache(path) as cache:
        run_ingest(
            "acme/netclient", TARGETS, settings(), cache=cache, clone_root=clone_root,
            client=client, max_prs=2, max_issues=2,
        )

    with SqliteCache(path) as cache:
        assert inspect(cache, "other/repo")["counts"]["commits"] == 0
        assert inspect(cache, None)["counts"]["commits"] == 2


def test_inspect_cache_lists_paths_by_commit_count(tmp_path: Path) -> None:
    from scripts.inspect_cache import inspect

    clone_root = build_clone(tmp_path)
    client = FakeClient()
    client.pull_requests[41] = pull_request_node(41)
    with SqliteCache(tmp_path / "c.sqlite3") as cache:
        run_ingest(
            "acme/netclient", TARGETS, settings(), cache=cache, clone_root=clone_root,
            client=client, max_prs=2, max_issues=2,
        )
        report = inspect(cache, "acme/netclient")
    paths = [row["path"] for row in report["top_paths_by_commit_count"]]
    assert "pkg/config.py" in paths


def test_fetched_counters_split_pull_requests_from_issues(tmp_path: Path) -> None:
    """A batch may resolve to a mix, so the summary cannot infer the kind from the ask."""
    from app.services.ingest.pipeline import fetch_references

    client = FakeClient()
    client.pull_requests[41] = pull_request_node(41)
    client.issues[12] = {
        "number": 12, "title": "Broken", "body": "b", "state": "CLOSED",
        "labels": {"nodes": []},
        "comments": {"totalCount": 0, "pageInfo": {"hasNextPage": False}, "nodes": []},
    }
    with SqliteCache(tmp_path / "c.sqlite3") as cache:
        outcome = fetch_references(
            client, "acme", "netclient", [41, 12], cache, "acme/netclient", "run1", refresh=False
        )
    assert outcome.fetched == 2
    assert outcome.fetched_pull_requests == 1
    assert outcome.fetched_issues == 1
    assert outcome.stored == 2


def test_a_number_that_resolves_to_an_issue_is_not_counted_as_a_pull_request(tmp_path: Path) -> None:
    from app.services.ingest.pipeline import fetch_references

    client = FakeClient()
    client.issues[7] = {
        "number": 7, "title": "Docs", "body": "b", "state": "OPEN",
        "labels": {"nodes": []},
        "comments": {"totalCount": 0, "pageInfo": {"hasNextPage": False}, "nodes": []},
    }
    with SqliteCache(tmp_path / "c.sqlite3") as cache:
        outcome = fetch_references(
            client, "acme", "netclient", [7], cache, "acme/netclient", "run1", refresh=False
        )
    assert outcome.fetched_pull_requests == 0
    assert outcome.fetched_issues == 1
