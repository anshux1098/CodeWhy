"""The Neo4j store is exercised through an injected fake driver.

A live database is not needed to pin the query construction and the record shaping:
`Neo4jGraphStore` accepts a driver, so a fake records what each call asked for and
returns hand-built records. This covers the counts read back from the store, the
source text a quote is re-checked against, and the subgraph the API renders, without
weakening anything or reaching the network.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.stores.graph_store import Neo4jGraphStore


class FakeRecord(dict):
    """A Neo4j record is a mapping with a lenient `get`."""

    def get(self, key, default=None):
        return dict.get(self, key, default)


class FakeResult:
    def __init__(self, records):
        self._records = list(records)

    def __iter__(self):
        return iter(self._records)

    def single(self):
        return self._records[0] if self._records else None


class FakeSession:
    def __init__(self, router, database):
        self._router = router
        self.database = database
        self.queries: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query, **params):
        self.queries.append(query)
        return FakeResult(self._router(query, params))


class FakeDriver:
    def __init__(self, router):
        self._router = router
        self.closed = False
        self.sessions: list[FakeSession] = []

    def session(self, database=None):
        session = FakeSession(self._router, database)
        self.sessions.append(session)
        return session

    def close(self):
        self.closed = True


def _router(query: str, params: dict):
    if "count(n) AS c" in query:
        return [FakeRecord(c=7)]
    if "count(r) AS c" in query:
        return [FakeRecord(c=4)]
    if "n.text AS text" in query:
        return [FakeRecord(text="mobile clients kept timing out")]
    if "MATCH (e:CodeEntity {id: $entity_id})" in query:
        # Entity subgraph: the node itself plus a one-hop neighbour.
        return [
            FakeRecord(node={"id": "key:MAX_RETRIES", "repo": "acme-netclient"}, labels=["CodeEntity"]),
            FakeRecord(node={"id": "dec_1", "repo": "acme-netclient"}, labels=["Decision"]),
        ]
    if "RETURN node, labels(node) AS labels" in query:
        # Repository subgraph: a duplicate id is returned to prove dedup.
        return [
            FakeRecord(node={"id": "dec_1", "repo": "acme-netclient"}, labels=["Decision"]),
            FakeRecord(node={"id": "dec_1", "repo": "acme-netclient"}, labels=["Decision"]),
            FakeRecord(
                node={"id": "key:MAX_RETRIES", "repo": "acme-netclient"}, labels=["CodeEntity"]
            ),
        ]
    if "UNWIND labels(n) AS l" in query:
        return [FakeRecord(l="CodeEntity", c=2), FakeRecord(l="Decision", c=5)]
    if "type(r) AS t" in query:
        return [FakeRecord(t="GOVERNS", c=3), FakeRecord(t="SUPPORTED_BY", c=1)]
    if "type(r) AS" in query:
        return [
            FakeRecord(**{"from": "dec_1", "type": "GOVERNS", "to": "key:MAX_RETRIES",
                          "props": {"confidence": 1.0}}),
        ]
    if "n.id = $node_id" in query:
        if params.get("node_id") == "acme-netclient":
            return [
                FakeRecord(n={"id": "acme-netclient", "repo": "acme-netclient",
                              "name": "netclient", "url": "https://github.com/acme/netclient"}),
            ]
        return []
    if "MATCH (e:CodeEntity {repo: $repo})" in query:
        return []
    return []


@pytest.fixture()
def store() -> Neo4jGraphStore:
    return Neo4jGraphStore(driver=FakeDriver(_router), database="test-db")


def test_the_injected_driver_is_used(store) -> None:
    assert isinstance(store.driver, FakeDriver)


def test_counts_are_read_back_from_the_database(store) -> None:
    assert store.node_count() == 7
    assert store.relationship_count() == 4


def test_counts_by_label_and_relationship_type_are_read_back(store) -> None:
    assert store.label_counts() == {"CodeEntity": 2, "Decision": 5}
    assert store.relationship_type_counts() == {"GOVERNS": 3, "SUPPORTED_BY": 1}


def test_source_text_comes_from_the_node(store) -> None:
    assert store.source_text_for("pr:acme/netclient#7") == "mobile clients kept timing out"


def test_source_text_is_empty_when_the_node_has_none() -> None:
    store = Neo4jGraphStore(driver=FakeDriver(lambda q, p: []), database="db")
    assert store.source_text_for("pr:acme/netclient#7") == ""


def test_a_repository_subgraph_deduplicates_nodes_and_returns_edges(store) -> None:
    subgraph = store.get_subgraph("acme-netclient")

    ids = [node["id"] for node in subgraph["nodes"]]
    assert ids == ["dec_1", "key:MAX_RETRIES"]
    assert all("labels" in node for node in subgraph["nodes"])

    assert subgraph["relationships"] == [
        {"from": "dec_1", "type": "GOVERNS", "to": "key:MAX_RETRIES", "confidence": 1.0}
    ]


def test_an_entity_subgraph_returns_the_node_and_its_neighbour(store) -> None:
    subgraph = store.get_subgraph("acme-netclient", entity_id="key:MAX_RETRIES")

    assert {node["id"] for node in subgraph["nodes"]} == {"key:MAX_RETRIES", "dec_1"}


def test_the_graph_source_finds_a_repository_through_the_neo4j_store(store) -> None:
    from app.services.data_source import GraphDataSource

    cfg = Settings(_env_file=None, data_source="graph", allow_mock_providers=True)
    source = GraphDataSource(cfg, store=store)

    assert source._has_repository_node("acme-netclient") is True
    assert source._has_repository_node("acme-other") is False
