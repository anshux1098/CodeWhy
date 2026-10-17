"""The repository summary must report what the graph actually holds.

It previously echoed the entity count three times and hard-coded the pull requests
and commits to zero, so a caller could not tell a repository with no merged work from
one whose counts were simply never read.
"""

from __future__ import annotations

from app.config import Settings
from app.services.data_source import GraphDataSource
from app.stores.graph_store import InMemoryGraphStore

REPO = "acme/netclient"


def _source() -> GraphDataSource:
    store = InMemoryGraphStore()
    store.merge_node("Repository", {"id": REPO, "repo": REPO, "name": "netclient"})
    store.merge_node("CodeEntity", {
        "id": "file:acme/netclient:src/a.py", "repo": REPO,
        "name": "src/a.py", "path": "src/a.py", "entity_type": "File",
    })
    store.merge_node("CodeEntity", {
        "id": "file:acme/netclient:src/b.py", "repo": REPO,
        "name": "src/b.py", "path": "src/b.py", "entity_type": "File",
    })
    store.merge_node("Decision", {"id": "dec_1", "repo": REPO, "summary": "Do a thing"})
    store.merge_node("PullRequest", {"id": "pr:acme/netclient#1", "repo": REPO, "number": 1})
    store.merge_node("Commit", {"id": "commit:abc", "repo": REPO, "sha": "abc"})
    cfg = Settings(_env_file=None, data_source="graph", allow_mock_providers=True)
    return GraphDataSource(cfg, store=store)


def test_counts_reflect_the_graph_not_the_entity_total() -> None:
    counts = _source().get_repository(REPO).counts
    assert counts.entities == 2
    assert counts.decisions == 1
    assert counts.pull_requests == 1
    assert counts.commits == 1


def test_entities_beyond_twenty_are_counted_and_searchable() -> None:
    store = InMemoryGraphStore()
    store.merge_node("Repository", {"id": REPO, "repo": REPO, "name": "netclient"})
    for i in range(25):
        store.merge_node("CodeEntity", {
            "id": f"file:acme/netclient:src/mod_{i}.py", "repo": REPO,
            "name": f"src/mod_{i}.py", "path": f"src/mod_{i}.py", "entity_type": "File",
        })
    cfg = Settings(_env_file=None, data_source="graph", allow_mock_providers=True)
    source = GraphDataSource(cfg, store=store)
    counts = source.get_repository(REPO).counts
    assert counts.entities == 25
    all_ents = store.search_entities(REPO, "")
    assert len(all_ents) == 25
    limited = store.search_entities(REPO, "", limit=10)
    assert len(limited) == 10

