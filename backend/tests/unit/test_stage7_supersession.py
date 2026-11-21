from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from app.schemas.common import DecisionState
from app.services.state import check_code_differs_from_latest, compute_decision_states
from app.stores.graph_store import InMemoryGraphStore
from app.stores.sqlite_cache import SqliteCache
from scripts.rebuild_graph import rebuild_graph


def test_silent_code_drift_detection():
    decs = [
        {"id": "dec_1", "source_id": "pr:acme/app#1", "effective_at": "2025-01-10T00:00:00Z"},
    ]
    analysis = compute_decision_states(decs, edges=[])
    assert analysis.states["dec_1"].state == DecisionState.ACTIVE
    assert check_code_differs_from_latest("dec_1", analysis, decs, latest_entity_commit_at="2025-01-10T00:00:00Z") is False
    assert check_code_differs_from_latest("dec_1", analysis, decs, latest_entity_commit_at="2025-02-15T00:00:00Z") is True


def test_rebuild_graph_persists_probable_supersession_and_rejected_state():
    with TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "c.sqlite3"
        with SqliteCache(db) as cache:
            cache.put_raw("pr", "acme/app", "1", {
                "number": 1, "title": "Initial retry", "body": "Set retry to 3",
                "state": "MERGED", "merged": True, "mergedAt": "2025-01-01T00:00:00Z",
                "author": "alice", "files": ["src/app/retry.py"],
            })
            cache.put_raw("pr", "acme/app", "2", {
                "number": 2, "title": "Follow up on #1", "body": "Follows up on #1 with jitter",
                "state": "MERGED", "merged": True, "mergedAt": "2025-02-01T00:00:00Z",
                "author": "bob", "files": ["src/app/retry.py"],
            })
            cache.put_raw("pr", "acme/app", "3", {
                "number": 3, "title": "Closed unmerged", "body": "Abandoned",
                "state": "CLOSED", "merged": False, "author": "carol", "files": ["src/app/retry.py"],
            })
            for idx, (pid, summary) in enumerate([("1", "Initial retry"), ("2", "Follows up on #1"), ("3", "Abandoned")], start=1):
                cache.put_decision({
                    "id": f"dec_{idx}",
                    "source_id": f"pr:acme/app#{pid}",
                    "repo": "acme/app",
                    "summary": summary,
                    "decision_type": "Reliability",
                    "state": "ACTIVE",
                    "affected_entities": ["src/app/retry.py"],
                    "quote_verified": True,
                    "extraction_version": "v1",
                    "content_hash": f"h{idx}",
                })

        store = InMemoryGraphStore()
        rebuild_graph("acme/app", db, store)

        d1 = store.get_node("dec_1")
        d3 = store.get_node("dec_3")
        assert d1 is not None and d3 is not None
        assert "dec_2" in d1["probable_superseded_by"]
        assert d3["state"] == "REJECTED"
