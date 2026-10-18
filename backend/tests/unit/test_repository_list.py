"""There must be a way to discover which repositories are in the graph.

The audit found the only repository route took an id the caller had to already know,
and that the response omitted the ingestion status the build already stores on the
node. This adds a list route and surfaces that status.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.services.data_source import GraphDataSource
from app.stores.graph_store import InMemoryGraphStore


def _store() -> InMemoryGraphStore:
    store = InMemoryGraphStore()
    store.merge_node("Repository", {
        "id": "acme-netclient", "repo": "acme-netclient", "name": "netclient",
        "full_name": "acme/netclient", "owner": "acme",
        "url": "https://github.com/acme/netclient",
        "scope": "acme/netclient at branch main, 4 file paths touched",
        "prs_fetched": 10, "sources_analyzed": 4, "prs_noise_skipped": 3,
        "verified_decisions": 5, "last_rebuilt_at": "2026-10-19T00:00:00Z",
    })
    store.merge_node("Repository", {
        "id": "other-repo", "repo": "other-repo", "name": "other",
        "full_name": "o/other", "owner": "o", "url": "https://github.com/o/other",
    })
    store.merge_node("Decision", {
        "id": "d1", "repo": "acme-netclient", "summary": "s", "state": "ACTIVE",
        "source_id": "pr:acme/netclient#1", "source_type": "PullRequest",
        "source_url": "https://github.com/acme/netclient/pull/1", "source_number": 1,
    })
    store.merge_node("CodeEntity", {"id": "file:acme/netclient:a.py", "repo": "acme-netclient"})
    return store


def _source(store: InMemoryGraphStore) -> GraphDataSource:
    return GraphDataSource(
        Settings(_env_file=None, data_source="graph", allow_mock_providers=True), store=store
    )


def test_the_repository_list_names_every_repository_in_the_graph() -> None:
    payload = _source(_store()).list_repositories()
    assert [item.id for item in payload.items] == ["acme-netclient", "other-repo"]
    assert payload.fixture is True


def test_each_listed_repository_carries_its_identity_and_counts() -> None:
    item = next(i for i in _source(_store()).list_repositories().items if i.id == "acme-netclient")
    assert item.name == "netclient"
    assert item.full_name == "acme/netclient"
    assert item.owner == "acme"
    assert item.url == "https://github.com/acme/netclient"
    assert item.counts.decisions == 1
    assert item.counts.entities == 1


def test_the_list_carries_the_ingestion_status() -> None:
    item = next(i for i in _source(_store()).list_repositories().items if i.id == "acme-netclient")
    assert item.prs_fetched == 10
    assert item.sources_analyzed == 4
    assert item.prs_noise_skipped == 3
    assert item.verified_decisions == 5
    assert item.scope.startswith("acme/netclient at branch main")
    assert item.last_rebuilt_at == "2026-10-19T00:00:00Z"


def test_a_repository_without_recorded_status_reports_none() -> None:
    item = next(i for i in _source(_store()).list_repositories().items if i.id == "other-repo")
    assert item.prs_fetched is None
    assert item.verified_decisions is None
    assert item.counts.decisions == 0


def test_the_single_repository_view_carries_the_same_status() -> None:
    payload = _source(_store()).get_repository("acme-netclient")
    assert payload.full_name == "acme/netclient"
    assert payload.verified_decisions == 5
    assert payload.prs_fetched == 10


@pytest.mark.live
def test_live_the_repository_list_includes_urllib3() -> None:
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
        ids = {item.id for item in source.list_repositories().items}
        assert "urllib3-urllib3" in ids
        item = next(i for i in source.list_repositories().items if i.id == "urllib3-urllib3")
        assert item.verified_decisions == 34
        assert item.counts.decisions == 34
    finally:
        store.close()
