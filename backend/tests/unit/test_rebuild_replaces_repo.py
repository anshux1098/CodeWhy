"""A rebuild must replace a repository's graph, not add to it.

The live graph accumulated a second copy of another repository and stale decisions
from earlier builds because every write was a MERGE and nothing removed rows that
the current cache no longer supports. A rebuild now clears the repository's own
subgraph first, keyed by both the API slug and the raw owner/name, and then loads.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.stores.graph_store import InMemoryGraphStore, Neo4jGraphStore
from app.stores.sqlite_cache import SqliteCache
from scripts.rebuild_graph import rebuild_graph

REPO = "urllib3/urllib3"
SLUG = "urllib3-urllib3"
OTHER_REPO = "sqlalchemy-alembic"
OTHER_DECISION = "dec_other"


def _cache(path: Path) -> None:
    with SqliteCache(path) as cache:
        cache.put_raw("pr", REPO, "pr:urllib3/urllib3#7", {
            "number": 7, "body": "body", "title": "A kept pull request",
        })
        base = {
            "repo": REPO,
            "source_id": "pr:urllib3/urllib3#7",
            "summary": "A kept decision",
            "rationale": "A kept rationale",
            "state": "ACTIVE",
            "decision_type": "Other",
            "affected_entities": json.dumps(["pkg/config.py"]),
            "created_at": "2026-01-01T00:00:00Z",
            "evaluated_at": "2026-01-01T00:00:00Z",
            "alternatives_considered": [],
            "constraints": [],
            "explicit_reversal_language": False,
            "unknown_fields": [],
            "extraction_version": "v1",
            "content_hash": "abc",
        }
        cache.put_decision({**base, "id": "dec_kept", "quote_verified": True})
        cache.put_decision({**base, "id": "dec_placeholder", "quote_verified": False})
        cache.put_evidence({
            "id": "ev_kept", "decision_id": "dec_kept",
            "source_id": "pr:urllib3/urllib3#7", "source_type": "pull_request",
            "source_url": "https://github.com/urllib3/urllib3/pull/7",
            "quote": "some quote", "author": "ann",
            "timestamp": "2025-01-01T00:00:00Z", "classification": "explicit",
            "claim": "c", "quote_verified": 1, "created_at": "2026-01-01T00:00:00Z",
        })


def _seeded_store() -> InMemoryGraphStore:
    store = InMemoryGraphStore()
    store.merge_node("Repository", {"id": SLUG, "repo": SLUG, "full_name": REPO})
    store.merge_node("Decision", {"id": "dec_stale", "repo": SLUG, "summary": "old"})
    store.merge_node("Decision", {"id": "dec_placeholder", "repo": SLUG, "summary": "old"})
    store.merge_node("Decision", {**{"id": OTHER_DECISION, "repo": OTHER_REPO}, "summary": "other"})
    store.merge_node("PullRequest", {
        "id": "pr:urllib3/urllib3#999", "repo": REPO, "number": 999,
    })
    store.merge_relationship("DECIDED_IN", "dec_stale", "pr:urllib3/urllib3#999", {})
    store.merge_relationship("REFERENCES", "dec_stale", OTHER_DECISION, {})
    return store


def test_a_rebuild_removes_stale_placeholder_and_old_id_nodes(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.sqlite3"
    _cache(cache_path)
    store = _seeded_store()

    rebuild_graph(REPO, cache_path, store)

    assert store.get_node("dec_stale") is None
    assert store.get_node("dec_placeholder") is None
    assert store.get_node("pr:urllib3/urllib3#999") is None
    assert store.get_node(OTHER_DECISION) is not None, "another repository must survive"
    assert store.count_nodes(SLUG, "Decision") == 1
    assert ("dec_stale", "DECIDED_IN", "pr:urllib3/urllib3#999") not in store.edges
    assert ("dec_stale", "REFERENCES", OTHER_DECISION) not in store.edges


class _EmptyResult:
    def __iter__(self):
        return iter(())

    def single(self):
        return None


class _RecordingDriver:
    def __init__(self) -> None:
        self.queries: list[tuple[str, dict]] = []

    def session(self, database=None):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query, **params):
        self.queries.append((query, params))
        return _EmptyResult()

    def close(self) -> None:
        pass


def test_the_neo4j_delete_is_scoped_to_the_repository_aliases() -> None:
    driver = _RecordingDriver()
    store = Neo4jGraphStore(driver=driver, database="db")

    store.delete_repository((SLUG, REPO))

    query, params = driver.queries[-1]
    assert "DETACH DELETE" in query
    assert "n.repo IN $repo_ids" in query
    assert params["repo_ids"] == [SLUG, REPO]
