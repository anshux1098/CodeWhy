"""An explicit `entity_id` must be honoured by the graph data source.

The fixture source already resolves `entity_id` directly; the graph source ignored
it and always ran text resolution over the question, so a caller who named the
entity still got whatever the words happened to match. These pin the graph path to
the same contract: a named entity is used as given, and a named entity that is not
in the graph is `entity_not_found` rather than a guess.
"""

from __future__ import annotations

from app.config import Settings
from app.schemas.ask import AskRequest
from app.services.data_source import GraphDataSource
from app.stores.graph_store import InMemoryGraphStore

REPO = "acme/netclient"


def _store_with_entity() -> InMemoryGraphStore:
    store = InMemoryGraphStore()
    store.merge_node("Repository", {"id": REPO, "repo": REPO, "name": "netclient"})
    store.merge_node("CodeEntity", {
        "id": "file:acme/netclient:pkg/config.py",
        "repo": REPO,
        "name": "pkg/config.py",
        "path": "pkg/config.py",
        "entity_type": "File",
    })
    return store


def _source(store: InMemoryGraphStore) -> GraphDataSource:
    cfg = Settings(_env_file=None, data_source="graph", allow_mock_providers=True)
    return GraphDataSource(cfg, store=store)


def test_a_named_entity_is_resolved_even_when_the_words_match_nothing() -> None:
    source = _source(_store_with_entity())
    # The question shares no token with the entity, so text resolution alone could
    # not reach it; only the explicit id can.
    response = source.ask(
        REPO,
        AskRequest(question="Why is this the way it is?", entity_id="file:acme/netclient:pkg/config.py"),
    )
    assert response.entity is not None
    assert response.entity.id == "file:acme/netclient:pkg/config.py"
    assert response.reason_code == "no_decision_path"


def test_a_named_entity_that_is_not_in_the_graph_is_not_found() -> None:
    source = _source(_store_with_entity())
    response = source.ask(
        REPO,
        AskRequest(question="Why is this the way it is?", entity_id="file:acme/netclient:pkg/ghost.py"),
    )
    assert response.outcome == "refusal"
    assert response.reason_code == "entity_not_found"
    assert response.entity is None
