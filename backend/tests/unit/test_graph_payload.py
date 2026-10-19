"""The /graph payload carries each node's properties, not an empty placeholder.

The audit found `GraphNode.props` was always `{}`, every node type's state, date,
source URL and quote were dropped, `SUPERSEDES` lost its rule and method, and
`truncated` was hard-coded false even when the node cap was hit.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.services.data_source import GraphDataSource
from app.stores.graph_store import InMemoryGraphStore

REPO = "acme/netclient"
E1 = "file:acme/netclient:src/a.py"
D1 = "dec_1"
D2 = "dec_2"
EV1 = "ev:1"
PR1 = "pr:acme/netclient#1"
C1 = "commit:abc"


def _store() -> InMemoryGraphStore:
    store = InMemoryGraphStore()
    store.merge_node("Repository", {
        "id": REPO, "repo": REPO, "name": "netclient", "full_name": "acme/netclient",
        "owner": "acme", "url": "https://github.com/acme/netclient", "scope": "acme/netclient",
    })
    store.merge_node("CodeEntity", {
        "id": E1, "repo": REPO, "name": "src/a.py", "path": "src/a.py", "entity_type": "File",
    })
    store.merge_node("Decision", {
        "id": D1, "repo": REPO, "summary": "Do a thing", "state": "ACTIVE",
        "source_url": "https://github.com/acme/netclient/pull/1", "quote_verified": True,
        "effective_at": "2024-02-11T09:20:00Z", "rule": None, "embedding": [0.1] * 384,
    })
    store.merge_node("Decision", {
        "id": D2, "repo": REPO, "summary": "Revert the thing", "state": "ACTIVE",
        "source_url": "https://github.com/acme/netclient/pull/2", "quote_verified": True,
        "effective_at": "2024-03-01T00:00:00Z",
    })
    store.merge_node("Evidence", {
        "id": EV1, "repo": REPO, "quote": "we did the thing",
        "source_url": "https://github.com/acme/netclient/pull/1", "author": "priya",
        "timestamp": "2024-02-11T09:14:00Z", "text": "x" * 5000,
    })
    store.merge_node("PullRequest", {
        "id": PR1, "repo": REPO, "number": 1, "title": "Add the thing",
        "url": "https://github.com/acme/netclient/pull/1", "author": "priya",
        "merged_at": "2024-02-11T09:36:35Z", "text": "y" * 5000,
    })
    store.merge_node("Commit", {
        "id": C1, "repo": REPO, "sha": "abc", "subject": "do it",
        "url": "https://github.com/acme/netclient/commit/abc",
    })
    store.merge_relationship("GOVERNS", D1, E1, {})
    store.merge_relationship("SUPPORTED_BY", D1, EV1, {})
    store.merge_relationship("DECIDED_IN", D1, PR1, {})
    store.merge_relationship("SUPERSEDES", D2, D1, {
        "rule": "1_revert_commit", "method": "commit_revert", "confidence": 1.0,
    })
    return store


def _graph(max_nodes: int = 80):
    cfg = Settings(_env_file=None, data_source="graph", allow_mock_providers=True,
                   max_graph_nodes=max_nodes)
    return GraphDataSource(cfg, store=_store()).get_graph(REPO, None)


def _node(payload, node_id):
    return next(n for n in payload.nodes if n.id == node_id)


def test_a_node_of_each_type_carries_its_properties() -> None:
    graph = _graph()
    repo = _node(graph, REPO)
    assert repo.props["name"] == "netclient"
    assert repo.props["full_name"] == "acme/netclient"
    assert repo.props["url"] == "https://github.com/acme/netclient"

    entity = _node(graph, E1)
    assert entity.props["path"] == "src/a.py"
    assert entity.props["entity_type"] == "File"

    decision = _node(graph, D1)
    assert decision.props["state"] == "ACTIVE"
    assert decision.props["summary"] == "Do a thing"
    assert decision.props["source_url"].endswith("/pull/1")
    assert decision.props["quote_verified"] is True
    assert decision.props["effective_at"] == "2024-02-11T09:20:00Z"

    evidence = _node(graph, EV1)
    assert evidence.props["quote"] == "we did the thing"
    assert evidence.props["source_url"].endswith("/pull/1")
    assert evidence.props["author"] == "priya"

    pr = _node(graph, PR1)
    assert pr.props["title"] == "Add the thing"
    assert pr.props["url"].endswith("/pull/1")
    assert pr.props["author"] == "priya"
    assert pr.props["merged_at"] == "2024-02-11T09:36:35Z"

    commit = _node(graph, C1)
    assert commit.props["sha"] == "abc"


def test_huge_fields_are_dropped_from_node_props() -> None:
    graph = _graph()
    assert "embedding" not in _node(graph, D1).props
    assert "text" not in _node(graph, EV1).props
    assert "text" not in _node(graph, PR1).props


def test_a_supersedes_edge_carries_its_rule_and_method() -> None:
    graph = _graph()
    edge = next(e for e in graph.edges if e.type == "SUPERSEDES")
    assert edge.rule == "1_revert_commit"
    assert edge.props["rule"] == "1_revert_commit"
    assert edge.props["method"] == "commit_revert"


def test_graph_is_not_truncated_below_the_cap() -> None:
    graph = _graph(max_nodes=10)
    assert graph.truncated is False


def test_graph_is_truncated_when_the_cap_is_reached() -> None:
    graph = _graph(max_nodes=3)
    assert len(graph.nodes) <= 3
    assert graph.truncated is True


@pytest.mark.live
def test_live_ssl_py_graph_nodes_carry_properties() -> None:
    """The real ssl_.py subgraph must expose non-empty props on its nodes."""
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
    try:
        graph = GraphDataSource(cfg, store=store).get_graph(
            "urllib3-urllib3", "file:urllib3/urllib3:src/urllib3/util/ssl_.py"
        )
        assert graph.nodes
        assert any(node.props for node in graph.nodes), "no node carried any property"
    finally:
        store.close()
