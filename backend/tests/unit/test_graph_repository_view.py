"""The repository graph view must show the decisions and what they connect to.

It previously returned an arbitrary page of nodes, so on the live graph the eighty
sampled nodes shared almost no edges and the view rendered with zero relationships.
The view now seeds from the repository's Decision nodes and pulls in the entities,
sources and evidence those decisions link to.
"""

from __future__ import annotations

from app.config import Settings
from app.services.data_source import GraphDataSource
from app.stores.graph_store import InMemoryGraphStore, Neo4jGraphStore

REPO = "acme/netclient"
E1 = "file:acme/netclient:src/a.py"
D1 = "dec_1"
EV1 = "ev:1"
PR1 = "pr:acme/netclient#1"


def _store() -> InMemoryGraphStore:
    store = InMemoryGraphStore()
    store.merge_node("Repository", {"id": REPO, "repo": REPO, "name": "netclient"})
    store.merge_node("CodeEntity", {
        "id": E1, "repo": REPO, "name": "src/a.py", "path": "src/a.py", "entity_type": "File",
    })
    store.merge_node("Decision", {"id": D1, "repo": REPO, "summary": "Do a thing"})
    store.merge_node("Evidence", {"id": EV1, "repo": REPO, "quote": "we did the thing"})
    store.merge_node("PullRequest", {"id": PR1, "repo": REPO, "number": 1})
    store.merge_relationship("GOVERNS", D1, E1, {})
    store.merge_relationship("SUPPORTED_BY", D1, EV1, {})
    store.merge_relationship("DECIDED_IN", D1, PR1, {})
    return store


def test_repository_view_includes_the_decision_and_its_neighbours() -> None:
    sub = _store().get_subgraph(REPO, None)
    ids = {n["id"] for n in sub["nodes"]}
    assert {D1, E1, EV1, PR1} <= ids

    rels = {(r["from"], r["type"], r["to"]) for r in sub["relationships"]}
    assert (D1, "GOVERNS", E1) in rels
    assert (D1, "SUPPORTED_BY", EV1) in rels
    assert (D1, "DECIDED_IN", PR1) in rels


def test_repository_graph_response_carries_edges() -> None:
    cfg = Settings(_env_file=None, data_source="graph", allow_mock_providers=True)
    response = GraphDataSource(cfg, store=_store()).get_graph(REPO, None)
    assert response.nodes, "the view returned no nodes"
    assert response.edges, "the view returned nodes but no edges"


class _EmptyResult:
    def __iter__(self):
        return iter(())

    def single(self):
        return None


class _RecordingDriver:
    """A driver that records the queries it is asked to run."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def session(self, database=None):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query, **params):
        self.queries.append(query)
        return _EmptyResult()

    def close(self) -> None:
        pass


def test_neo4j_repository_view_seeds_from_the_decision_nodes() -> None:
    driver = _RecordingDriver()
    store = Neo4jGraphStore(driver=driver, database="db")
    store.get_subgraph(REPO, None)

    repo_query = next(q for q in driver.queries if "labels(node)" in q)
    assert ":Decision {repo: $repo}" in repo_query
    for relationship in ("GOVERNS", "DECIDED_IN", "SUPPORTED_BY"):
        assert relationship in repo_query
    assert "MATCH (node {repo: $repo})" not in repo_query

