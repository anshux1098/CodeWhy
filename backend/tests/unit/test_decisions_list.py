"""A repository's decisions must be listable in date order, filterable, and paged.

The audit found there was no way to list a repository's decisions at all: the only
decision routes took a single id. The list must read from the graph, order by the
decision's date with undated decisions last, filter by entity and state, and page
without lying about how many decisions there are.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.schemas.common import DecisionState
from app.services.data_source import GraphDataSource
from app.stores.graph_store import InMemoryGraphStore

REPO = "acme/netclient"


def _decision(store: InMemoryGraphStore, decision_id: str, *, state: str, date: str | None) -> None:
    store.merge_node("Decision", {
        "id": decision_id, "repo": REPO, "summary": f"summary {decision_id}",
        "state": state, "effective_at": date,
        "source_id": f"pr:{REPO}#7", "source_type": "PullRequest",
        "source_url": f"https://github.com/{REPO}/pull/7", "source_number": 7,
    })


def _store() -> InMemoryGraphStore:
    store = InMemoryGraphStore()
    store.merge_node("Repository", {"id": REPO, "name": "netclient", "repo": REPO})
    store.merge_node("CodeEntity", {"id": "key:MAX_RETRIES", "repo": REPO, "name": "MAX_RETRIES"})
    store.merge_node("CodeEntity", {"id": f"file:{REPO}:retry.py", "repo": REPO, "name": "retry.py"})
    _decision(store, "dec_a", state="ACTIVE", date="2024-01-01T00:00:00Z")
    _decision(store, "dec_b", state="SUPERSEDED", date="2024-03-01T00:00:00Z")
    _decision(store, "dec_c", state="ACTIVE", date=None)
    store.nodes["dec_a"]["supersedes"] = ["dec_x"]
    store.nodes["dec_a"]["superseded_by"] = ["dec_b"]
    store.nodes["dec_a"]["rule"] = "2_config_key_changed"
    store.merge_relationship("GOVERNS", "dec_a", "key:MAX_RETRIES", {})
    store.merge_relationship("GOVERNS", "dec_b", f"file:{REPO}:retry.py", {})
    store.merge_relationship("GOVERNS", "dec_c", "key:MAX_RETRIES", {})
    return store


def _source(store: InMemoryGraphStore) -> GraphDataSource:
    return GraphDataSource(
        Settings(_env_file=None, data_source="graph", allow_mock_providers=True), store=store
    )


def test_decisions_are_ordered_by_date_with_undated_ones_last() -> None:
    page = _source(_store()).list_decisions(REPO)
    assert [item.id for item in page.items] == ["dec_b", "dec_a", "dec_c"]


def test_the_list_reports_the_total_before_paging() -> None:
    page = _source(_store()).list_decisions(REPO, limit=1, offset=0)
    assert page.total == 3
    assert len(page.items) == 1


def test_paging_walks_the_ordered_list() -> None:
    source = _source(_store())
    assert [i.id for i in source.list_decisions(REPO, limit=1, offset=1).items] == ["dec_a"]
    assert [i.id for i in source.list_decisions(REPO, limit=2, offset=1).items] == ["dec_a", "dec_c"]


def test_the_entity_filter_keeps_only_decisions_that_govern_it() -> None:
    page = _source(_store()).list_decisions(REPO, entity_id="key:MAX_RETRIES")
    assert [item.id for item in page.items] == ["dec_a", "dec_c"]
    assert page.total == 2


def test_an_unknown_entity_is_an_empty_list_not_an_error() -> None:
    page = _source(_store()).list_decisions(REPO, entity_id="key:NOTHING")
    assert page.items == []
    assert page.total == 0


def test_the_state_filter_keeps_only_that_state() -> None:
    page = _source(_store()).list_decisions(REPO, state=DecisionState.ACTIVE)
    assert [item.id for item in page.items] == ["dec_a", "dec_c"]


def test_the_items_are_compact_and_carry_the_supersession_links() -> None:
    page = _source(_store()).list_decisions(REPO)
    item = next(i for i in page.items if i.id == "dec_a")
    assert item.summary == "summary dec_a"
    assert item.state is DecisionState.ACTIVE
    assert item.date == "2024-01-01T00:00:00Z"
    assert item.source_url == f"https://github.com/{REPO}/pull/7"
    assert item.entities == ["key:MAX_RETRIES"]
    assert item.supersedes == ["dec_x"]
    assert item.superseded_by == ["dec_b"]
    assert item.rule == "2_config_key_changed"


def test_a_decision_without_a_date_reports_a_null_date() -> None:
    page = _source(_store()).list_decisions(REPO)
    assert next(i for i in page.items if i.id == "dec_c").date is None


def test_the_source_flags_fixture_data() -> None:
    assert _source(_store()).list_decisions(REPO).fixture is True


@pytest.mark.live
def test_live_a_repository_lists_its_decisions() -> None:
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
        page = source.list_decisions("urllib3-urllib3", entity_id="file:urllib3/urllib3:src/urllib3/util/ssl_.py")
        assert page.total >= 14
        assert all(i.date is not None for i in page.items)
        superseded = source.list_decisions("urllib3-urllib3", state=DecisionState.SUPERSEDED)
        assert superseded.total >= 1
    finally:
        store.close()
