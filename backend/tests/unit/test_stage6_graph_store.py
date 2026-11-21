from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from app.stores.graph_store import InMemoryGraphStore
from app.stores.sqlite_cache import SqliteCache
from scripts.rebuild_graph import rebuild_graph


def test_rebuild_graph_creates_person_nodes_authored_reviewed_and_pre_stored_counts():
    with TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "c.sqlite3"
        with SqliteCache(db) as cache:
            cache.put_raw(
                "pr",
                "acme/net",
                "42",
                {
                    "number": 42,
                    "title": "Pin retry budget",
                    "body": "Mobile clients kept timing out.",
                    "state": "MERGED",
                    "merged": True,
                    "mergedAt": "2025-03-01T00:00:00Z",
                    "author": "alice",
                    "reviews": [{"author": {"login": "bob"}, "state": "APPROVED", "body": "LGTM"}],
                    "files": ["src/net/retry.py"],
                },
            )
            cache.put_commits_and_files_batch(
                "acme/net",
                [{"sha": "sha1", "subject": "Pin retry (#42)", "message": "Pin retry (#42)", "author_name": "alice"}],
                [("sha1", {"path": "src/net/retry.py", "status": "M", "diff": "+RETRY = 5"})],
            )
            cache.put_decision({
                "id": "dec_42",
                "source_id": "pr:acme/net#42",
                "repo": "acme/net",
                "summary": "Pin retry budget to 5",
                "decision_type": "Reliability",
                "rationale": "Mobile clients kept timing out.",
                "state": "ACTIVE",
                "affected_entities": ["src/net/retry.py"],
                "quote_verified": True,
                "extraction_version": "v1",
                "content_hash": "h42",
            })

        store = InMemoryGraphStore()
        counts = rebuild_graph("acme/net", db, store)

        assert counts["nodes"] > 0
        # 6B: Person nodes + AUTHORED & REVIEWED edges
        assert store.get_node("person:alice") is not None
        assert store.get_node("person:bob") is not None
        rel_counts = store.relationship_type_counts()
        assert rel_counts.get("AUTHORED", 0) >= 1
        assert rel_counts.get("REVIEWED", 0) == 1

        # 6D: Pre-stored exact counts on Repository & CodeEntity
        repo_node = store.get_node("acme-net")
        assert repo_node is not None
        assert repo_node["decisions_count"] == 1
        assert repo_node["pull_requests_count"] == 1
        assert repo_node["commits_count"] == 1
        assert repo_node["entities_count"] >= 1

        ent_node = store.get_node("file:acme/net:src/net/retry.py")
        assert ent_node is not None
        assert ent_node["decision_count"] == 1
