from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from app.config import Settings
from app.providers.llm_provider import MockLLMProvider
from app.schemas.ask import AskRequest
from app.schemas.common import WhoToAskReason
from app.services.data_source import GraphDataSource
from app.stores.graph_store import InMemoryGraphStore
from app.stores.sqlite_cache import SqliteCache
from scripts.rebuild_graph import rebuild_graph


def test_who_to_ask_returns_authored_and_reviewed_maintainers_from_graph():
    now_iso = datetime.now(timezone.utc).isoformat()
    with TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "c.sqlite3"
        with SqliteCache(db) as cache:
            cache.put_raw(
                "pr",
                "acme/app",
                "15",
                {
                    "number": 15,
                    "title": "Enforce strict timeout",
                    "body": "Timeouts prevent socket starvation.",
                    "state": "MERGED",
                    "merged": True,
                    "mergedAt": now_iso,
                    "author": "alice_dev",
                    "reviews": [{"author": {"login": "bob_reviewer"}, "state": "APPROVED", "body": "LGTM"}],
                    "files": ["src/app/client.py"],
                },
            )
            cache.put_decision({
                "id": "dec_15",
                "source_id": "pr:acme/app#15",
                "repo": "acme/app",
                "summary": "Enforce strict timeout",
                "decision_type": "Reliability",
                "rationale": "Timeouts prevent socket starvation.",
                "state": "ACTIVE",
                "affected_entities": ["src/app/client.py"],
                "quote_verified": True,
                "extraction_version": "v1",
                "content_hash": "h15",
            })
            cache.put_evidence({
                "id": "ev_15",
                "decision_id": "dec_15",
                "source_id": "pr:acme/app#15",
                "source_type": "pull_request",
                "source_url": "https://github.com/acme/app/pull/15",
                "quote": "Timeouts prevent socket starvation.",
                "author": "alice_dev",
                "timestamp": now_iso,
                "classification": "explicit",
                "claim": "Timeout prevents starvation",
                "quote_verified": True,
            })

        store = InMemoryGraphStore()
        rebuild_graph("acme/app", db, store)

        ds = GraphDataSource(cfg=Settings(_env_file=None, offline=True, min_score=0.0), store=store)
        ds.provider = MockLLMProvider(
            canned_response=json.dumps({
                "answer": "Timeouts prevent socket starvation.",
                "cited_evidence_ids": ["ev_15"],
            })
        )
        resp = ds.ask("acme-app", AskRequest(
            question="Why does src/app/client.py enforce a strict timeout?",
            entity_id="file:acme/app:src/app/client.py",
        ))
        logins = {w.login: w for w in resp.who_to_ask}
        assert "alice_dev" in logins
        assert logins["alice_dev"].reason == WhoToAskReason.AUTHOR
        assert "bob_reviewer" in logins
        assert logins["bob_reviewer"].reason == WhoToAskReason.REVIEWER
        assert logins["bob_reviewer"].active is True
