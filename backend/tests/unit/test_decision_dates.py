"""A decision's date must come from when its pull request merged.

The audit found every decision date empty: the graph copied `decisions.created_at`,
which the cache leaves blank, so a decision carried no date at all. The contract
documents no meaning for `recorded_at`/`effective_at`, so the date is written to
`effective_at` (the field the state layer already treats as "in force from") and the
extraction time is never used.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import Settings
from app.services.data_source import GraphDataSource
from app.stores.sqlite_cache import SqliteCache
from scripts.rebuild_graph import build_from_cache

REPO = "acme/netclient"


def _seed(cache_path: Path, *, merged_at: str | None, decision_created_at: str = "") -> str:
    with SqliteCache(cache_path) as cache:
        payload = {"number": 7, "title": "Cap retries", "body": "because", "files": ["pkg/config.py"]}
        if merged_at is not None:
            payload["mergedAt"] = merged_at
        cache.put_raw("pr", REPO, "7", payload)
        cache.put_decision({
            "id": "d1", "repo": REPO, "source_id": "pr:acme/netclient#7",
            "summary": "s", "rationale": "r", "state": "ACTIVE",
            "decision_type": "Other", "affected_entities": json.dumps(["pkg/config.py"]),
            "quote_verified": True, "created_at": decision_created_at,
            "evaluated_at": decision_created_at, "alternatives_considered": [],
            "constraints": [], "explicit_reversal_language": False, "unknown_fields": [],
            "extraction_version": "v1", "content_hash": "abc",
        })
    return "d1"


def _source(cache_path: Path) -> GraphDataSource:
    result = build_from_cache(cache_path, REPO)
    cfg = Settings(_env_file=None, data_source="graph", allow_mock_providers=True)
    return GraphDataSource(cfg, store=result.store)


def test_the_decision_date_is_the_pull_request_merged_at(tmp_path: Path) -> None:
    cache_path = tmp_path / "c.sqlite3"
    decision_id = _seed(cache_path, merged_at="2024-08-22T17:36:35Z")

    node = build_from_cache(cache_path, REPO).store.get_node(decision_id)
    assert node["effective_at"] == "2024-08-22T17:36:35Z"
    assert node["recorded_at"] is None


def test_the_extraction_time_is_never_used_as_the_decision_date(tmp_path: Path) -> None:
    cache_path = tmp_path / "c.sqlite3"
    decision_id = _seed(
        cache_path, merged_at="2024-09-03T09:10:49Z", decision_created_at="2099-12-31T23:59:59Z"
    )

    node = build_from_cache(cache_path, REPO).store.get_node(decision_id)
    assert node["effective_at"] == "2024-09-03T09:10:49Z"


def test_a_decision_without_a_merged_at_has_a_null_date(tmp_path: Path) -> None:
    cache_path = tmp_path / "c.sqlite3"
    decision_id = _seed(cache_path, merged_at=None)

    node = build_from_cache(cache_path, REPO).store.get_node(decision_id)
    assert node["effective_at"] is None
    assert node["recorded_at"] is None


def test_the_decision_api_returns_the_date_from_the_graph(tmp_path: Path) -> None:
    cache_path = tmp_path / "c.sqlite3"
    decision_id = _seed(cache_path, merged_at="2024-08-22T17:36:35Z")

    detail = _source(cache_path).get_decision(decision_id)
    assert detail.effective_at == "2024-08-22T17:36:35Z"
    assert detail.recorded_at is None


@pytest.mark.live
def test_live_decisions_carry_their_pull_request_merge_dates() -> None:
    import os

    if os.environ.get("RUN_LIVE") != "1":
        pytest.skip("set RUN_LIVE=1 to read the live graph")

    from app.config import settings as global_settings
    from app.stores.graph_store import Neo4jGraphStore, get_graph_store

    global_settings.require_neo4j()
    store = get_graph_store(global_settings)
    assert isinstance(store, Neo4jGraphStore), "the live check needs a real store"
    cfg = Settings(_env_file=None, data_source="graph", allow_mock_providers=True,
                   neo4j_uri=global_settings.neo4j_uri,
                   neo4j_username=global_settings.neo4j_username,
                   neo4j_password=global_settings.neo4j_password,
                   neo4j_database=global_settings.neo4j_database)
    source = GraphDataSource(cfg, store=store)
    try:
        assert source.get_decision("dec_6dee7648b9ef5416").effective_at == "2024-08-22T17:36:35Z"
        assert source.get_decision("dec_ce303eb845540d38").effective_at == "2024-09-03T09:10:49Z"
    finally:
        store.close()
