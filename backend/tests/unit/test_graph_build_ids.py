"""The graph build maps cache rows onto the nodes the API addresses.

These run the real builder against a small on-disk cache and an in-memory store, so
the production code path is exercised without a database. They pin the properties the
rest of the system depends on: the repository is addressed by its slug, every node
carries that slug as `repo`, a source node carries the text a quote is re-checked
against, a decision carries its provenance, only a verified decision is graphed, and
a link endpoint that names a source is materialised so the edge is never dropped.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.graph.ids import (
    entity_id_for,
    graph_id,
    source_label_for,
    source_number,
    source_text_from_payload,
    source_url,
    to_api_id,
)
from app.stores.sqlite_cache import SqliteCache
from scripts import rebuild_graph

REPO = "acme/netclient"
SLUG = "acme-netclient"


def seed_cache(path: Path) -> None:
    with SqliteCache(path) as cache:
        cache.put_raw("pr", REPO, "7", {
            "title": "Cap the retries",
            "body": "mobile clients kept timing out",
            "comments": [{"body": "Looks reasonable to me"}],
            "url": f"https://github.com/{REPO}/pull/7",
            "state": "closed",
        })
        cache.put_raw("issue", REPO, "3", {"title": "Flaky timeouts", "body": "clients time out"})
        cache.put_raw("doc", REPO, "docs/guide.md", {"title": "Guide", "body": "how to configure"})
        cache.put_commit(REPO, {
            "sha": "abc", "subject": "fix retries",
            "message": "fix retries\n\nThis reverts #7",
            "pull_requests": [7],
        })
        cache.put_commit_file("abc", {"path": "pkg/config.py", "status": "modified"})
        cache.put_decision({
            "id": "dec_ok", "source_id": f"pr:{REPO}#7", "repo": REPO,
            "summary": "Raised the retry cap", "decision_type": "change",
            "rationale": "timeouts", "state": "ACTIVE",
            "affected_entities": ["pkg/config.py", "MAX_RETRIES"],
            "quote_verified": True, "extraction_version": "1", "content_hash": "h1",
        })
        cache.put_decision({
            "id": "dec_bad", "source_id": f"pr:{REPO}#7", "repo": REPO,
            "summary": "Placeholder", "decision_type": "change", "state": "ACTIVE",
            "quote_verified": False, "extraction_version": "1", "content_hash": "h2",
        })
        cache.put_evidence({
            "id": "ev_ok", "decision_id": "dec_ok", "source_id": f"pr:{REPO}#7",
            "source_type": "pull_request", "source_url": f"https://github.com/{REPO}/pull/7",
            "quote": "mobile clients kept timing out", "classification": "rationale",
            "claim": "cap raised", "author": "reviewer", "timestamp": "2025-01-01T00:00:00Z",
            "quote_verified": True,
        })
        cache.put_link({
            "id": "l1", "repo": REPO, "source_id": "commit:abc", "source_type": "commit",
            "rel_type": "PART_OF", "target_id": f"pr:{REPO}#7", "target_type": "pull_request",
            "derivation_method": "commit_pr",
        })
        # This pull request was never ingested, but a commit names it, so the build must
        # still create the node or the edge would be dropped by MATCH.
        cache.put_link({
            "id": "l2", "repo": REPO, "source_id": "commit:zzz", "source_type": "commit",
            "rel_type": "PART_OF", "target_id": f"pr:{REPO}#99", "target_type": "pull_request",
            "derivation_method": "commit_pr",
        })


@pytest.fixture()
def built(tmp_path: Path):
    cache_path = tmp_path / "c.sqlite3"
    seed_cache(cache_path)
    return rebuild_graph.build_from_cache(cache_path, REPO)


def test_only_a_verified_decision_is_graphed(built) -> None:
    assert built.store.get_node("dec_ok") is not None
    assert built.store.get_node("dec_bad") is None


def test_the_excluded_placeholder_count_is_reported(built) -> None:
    assert built.counts["excluded_placeholders"] == 1


def test_the_counts_are_measured_from_the_store(built) -> None:
    assert built.counts["nodes"] == built.store.node_count()
    assert built.counts["relationships"] == built.store.relationship_count()


def test_the_repository_is_addressed_by_its_slug(built) -> None:
    repo = built.store.get_node(SLUG)
    assert repo is not None
    assert repo["full_name"] == REPO
    assert repo["repo"] == SLUG


def test_every_node_carries_the_slug_as_its_repo(built) -> None:
    for node_id, props in built.store.nodes.items():
        assert props.get("repo") == SLUG, f"{node_id} is not tagged with the slug"


def test_a_source_node_carries_the_text_a_quote_is_checked_against(built) -> None:
    node = built.store.get_node(f"pr:{REPO}#7")
    assert node["text"] == "Cap the retries\nmobile clients kept timing out\nLooks reasonable to me"
    assert built.store.source_text_for(f"pr:{REPO}#7") == node["text"]


def test_a_decision_carries_its_provenance(built) -> None:
    node = built.store.get_node("dec_ok")
    assert node["source_id"] == f"pr:{REPO}#7"
    assert node["source_type"] == "PullRequest"
    assert node["source_number"] == 7
    assert node["source_url"] == f"https://github.com/{REPO}/pull/7"


def test_a_link_endpoint_naming_an_unfetched_source_is_materialised(built) -> None:
    stub = built.store.get_node(f"pr:{REPO}#99")
    assert stub is not None
    assert stub["repo"] == SLUG
    assert (f"commit:zzz", "PART_OF", f"pr:{REPO}#99") in built.store.edges


def test_a_part_of_link_between_two_known_nodes_is_present(built) -> None:
    assert ("commit:abc", "PART_OF", f"pr:{REPO}#7") in built.store.edges


def test_graph_id_maps_only_the_repository_to_its_slug() -> None:
    assert graph_id(f"repo:{REPO}", REPO) == SLUG
    assert graph_id(f"pr:{REPO}#7", REPO) == f"pr:{REPO}#7"
    assert graph_id("commit:abc", REPO) == "commit:abc"


def test_to_api_id_replaces_every_slash() -> None:
    assert to_api_id("a/b") == "a-b"
    assert to_api_id("a/b/c") == "a-b-c"


def test_entity_id_for_separates_paths_from_keys() -> None:
    assert entity_id_for("pkg/config.py", REPO) == f"file:{REPO}:pkg/config.py"
    assert entity_id_for("src/urllib3/util/ssl_.py", REPO) == f"file:{REPO}:src/urllib3/util/ssl_.py"
    assert entity_id_for("MAX_RETRIES", REPO) == f"entity:{REPO}:MAX_RETRIES"


def test_source_helpers_agree_on_the_label_and_number() -> None:
    assert source_label_for(f"pr:{REPO}#7") == "PullRequest"
    assert source_label_for("commit:abc") == "Commit"
    assert source_label_for("file:x.py") is None
    assert source_number(f"pr:{REPO}#7") == 7
    assert source_number("commit:abc") is None


def test_source_url_points_at_the_record_not_the_repository() -> None:
    assert source_url(f"pr:{REPO}#7", REPO) == f"https://github.com/{REPO}/pull/7"
    assert source_url(f"issue:{REPO}#3", REPO) == f"https://github.com/{REPO}/issues/3"
    assert source_url("commit:abc", REPO) == f"https://github.com/{REPO}/commit/abc"


def test_source_text_joins_title_body_and_comments() -> None:
    payload = {"title": "T", "body": "B", "comments": [{"body": "C1"}, {"body": "C2"}, {"no": 1}]}
    assert source_text_from_payload(payload) == "T\nB\nC1\nC2"
