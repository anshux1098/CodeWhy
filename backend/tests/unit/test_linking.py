from __future__ import annotations

from pathlib import Path
import pytest

from app.services.linking import (
    FileHistoryTracker,
    LinkRecord,
    extract_commit_pr_links,
    extract_containment_links,
    extract_document_supersession,
    extract_issue_links,
    extract_revert_links,
    get_module_for_path,
    make_link_id,
)
from app.stores.sqlite_cache import SqliteCache


def test_revert_commit_extraction_finds_target_sha() -> None:
    msg = (
        "Revert 'Add connection pool retry logic'\n\n"
        "This reverts commit 7b1c43d8a901eef234567890abcdef1234567890.\n"
        "The change caused unexpected timeouts under load."
    )
    links = extract_revert_links("a1b2c3d4e5f6", msg, "urllib3/urllib3")
    assert len(links) == 1
    link = links[0]
    assert link.rel_type == "REVERTS"
    assert link.source_id == "commit:a1b2c3d4e5f6"
    assert link.target_id == "commit:7b1c43d8a901eef234567890abcdef1234567890"
    assert link.is_direct is True
    assert link.derivation_method == "revert_message"
    assert link.confidence == 1.0


def test_revert_trailer_extraction() -> None:
    msg = "Roll back migration\n\nReverts: deadbeef123456\n"
    links = extract_revert_links("feedface9876", msg, "org/repo")
    assert len(links) == 1
    assert links[0].target_id == "commit:deadbeef123456"
    assert links[0].derivation_method == "revert_trailer"


def test_revert_extraction_ignores_self_reference_and_empty() -> None:
    assert extract_revert_links("1234567", "This reverts commit 1234567", "org/repo") == []
    assert extract_revert_links("1234567", "Regular commit with no reverts", "org/repo") == []


def test_commit_pr_extraction_from_squash_and_merge() -> None:
    squash_links = extract_commit_pr_links(
        "abc1234",
        "Fix socket leak on timeout (#892)",
        "Details inside",
        "org/repo",
    )
    assert len(squash_links) == 1
    assert squash_links[0].rel_type == "PART_OF"
    assert squash_links[0].target_id == "pr:org/repo#892"

    merge_links = extract_commit_pr_links(
        "def5678",
        "Merge pull request #1004 from contributor/branch",
        "",
        "org/repo",
        explicit_prs=[1004],
    )
    assert len(merge_links) == 1
    assert merge_links[0].target_id == "pr:org/repo#1004"


def test_issue_links_distinguishes_closing_from_mention() -> None:
    text = (
        "This patch addresses the memory leak.\n\n"
        "Fixes #145 and resolves #200.\n"
        "See also discussion in #305 for prior context.\n"
        "```python\n# This code comment #999 should be ignored\n```\n"
        "Also reference `var = #888` in inline code."
    )
    links = extract_issue_links("pr:org/repo#50", "PullRequest", text, "org/repo")
    
    closing_links = [l for l in links if l.is_direct]
    mention_links = [l for l in links if not l.is_direct]

    closing_targets = {l.target_id for l in closing_links}
    assert "issue:org/repo#145" in closing_targets
    assert "issue:org/repo#200" in closing_targets
    for l in closing_links:
        assert l.derivation_method == "closing_keyword"
        assert l.confidence == 1.0

    mention_targets = {l.target_id for l in mention_links}
    assert "issue:org/repo#305" in mention_targets
    for l in mention_links:
        assert l.derivation_method == "mention"
        assert l.confidence == 0.7

    # Fenced code and inline code references must be ignored
    all_targets = {l.target_id for l in links}
    assert "issue:org/repo#999" not in all_targets
    assert "issue:org/repo#888" not in all_targets


def test_document_supersession_adr() -> None:
    adr_content = (
        "# ADR 2: HTTP/1.1 Pipelining\n\n"
        "Date: 2021-03-15\n"
        "Status: Superseded by ADR-14\n\n"
        "We initially attempted HTTP pipelining..."
    )
    links = extract_document_supersession("docs/adr/0002.md", adr_content, "urllib3/urllib3")
    assert len(links) == 1
    link = links[0]
    assert link.rel_type == "SUPERSEDES"
    assert link.source_id == "doc:urllib3/urllib3:ADR-14"
    assert link.target_id == "doc:urllib3/urllib3:docs/adr/0002.md"
    assert link.derivation_method == "adr_status"
    assert link.confidence == 1.0


def test_file_rename_tracker_follows_chains() -> None:
    tracker = FileHistoryTracker()
    # File was renamed: v1/client.py -> v2/client.py -> src/client.py
    tracker.record_rename("v1/client.py", "v2/client.py")
    tracker.record_rename("v2/client.py", "src/client.py")

    assert tracker.canonical_path("v1/client.py") == "src/client.py"
    assert tracker.canonical_path("v2/client.py") == "src/client.py"
    assert tracker.canonical_path("src/client.py") == "src/client.py"

    assert tracker.all_historical_paths("src/client.py") == {
        "v1/client.py",
        "v2/client.py",
        "src/client.py",
    }


def test_file_rename_commit_links() -> None:
    tracker = FileHistoryTracker()
    commit_files = [
        {"sha": "c1", "path": "old/path.py", "old_path": None, "status": "added"},
        {"sha": "c2", "path": "new/path.py", "old_path": "old/path.py", "status": "renamed"},
        {"sha": "c3", "path": "new/path.py", "old_path": None, "status": "modified"},
    ]
    links = tracker.build_commit_file_links("org/repo", commit_files)
    assert len(links) == 3

    # All three commits must point to canonical entity new/path.py
    for link in links:
        assert link.source_id == "file:org/repo:new/path.py"
        assert link.rel_type == "MODIFIED_IN"

    # Commit 1 had old/path.py so it is marked rename_follow
    c1_link = next(l for l in links if l.target_id == "commit:c1")
    assert c1_link.derivation_method == "rename_follow"


def test_module_containment_extraction() -> None:
    assert get_module_for_path("src/urllib3/poolmanager.py") == "src/urllib3"
    assert get_module_for_path("urllib3/connection.py") == "urllib3"
    assert get_module_for_path("README.md") is None
    assert get_module_for_path("docs/index.md") is None

    files = [
        "src/urllib3/poolmanager.py",
        "src/urllib3/connection.py",
        "README.md",
    ]
    links = extract_containment_links("urllib3/urllib3", files)
    
    # Repo contains module src/urllib3 and root README.md
    repo_contains = [l for l in links if l.source_id == "repo:urllib3/urllib3"]
    targets = {l.target_id for l in repo_contains}
    assert "module:urllib3/urllib3:src/urllib3" in targets
    assert "file:urllib3/urllib3:README.md" in targets

    # Module src/urllib3 contains the two python files
    mod_contains = [l for l in links if l.source_id == "module:urllib3/urllib3:src/urllib3"]
    mod_targets = {l.target_id for l in mod_contains}
    assert "file:urllib3/urllib3:src/urllib3/poolmanager.py" in mod_targets
    assert "file:urllib3/urllib3:src/urllib3/connection.py" in mod_targets


def test_sqlite_cache_stores_and_queries_links(tmp_path: Path) -> None:
    db_path = tmp_path / "test_cache.sqlite3"
    with SqliteCache(db_path) as cache:
        link = LinkRecord(
            id=make_link_id("commit:c1", "REVERTS", "commit:c0"),
            repo="org/repo",
            source_id="commit:c1",
            source_type="Commit",
            rel_type="REVERTS",
            target_id="commit:c0",
            target_type="Commit",
            is_direct=True,
            derivation_method="revert_message",
            confidence=1.0,
            metadata={"reason": "test"},
        )
        assert cache.put_link(link.as_row()) is True
        
        # Idempotent put
        assert cache.put_link(link.as_row()) is True

        rows = cache.links_for("org/repo", rel_type="REVERTS")
        assert len(rows) == 1
        assert rows[0]["source_id"] == "commit:c1"
        assert rows[0]["target_id"] == "commit:c0"

        from_rows = cache.links_from("commit:c1")
        assert len(from_rows) == 1

        to_rows = cache.links_to("commit:c0")
        assert len(to_rows) == 1
