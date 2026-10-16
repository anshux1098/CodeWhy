"""A question that names no entity is answered from the decisions' own text.

The entity resolver can only act on a name that appears in the question. Real
questions often name none ("why was HTTP/2 TLS support reverted?") while the
decisions themselves are full of the subject. These pin the fallback: the decisions
are found from their text, the entity is taken from them through GOVERNS, and a
question whose words match no decision stays a refusal instead of becoming a guess.
"""

from __future__ import annotations

from app.config import Settings
from app.schemas.ask import AskRequest
from app.services.data_source import GraphDataSource
from app.services.entity_resolution import ResolutionOutcome, resolve_entity_from_decisions
from app.stores.graph_store import InMemoryGraphStore

REPO = "acme/netclient"
SSL = "file:acme/netclient:src/netclient/ssl_.py"


def _store() -> InMemoryGraphStore:
    store = InMemoryGraphStore()
    store.merge_node("Repository", {"id": REPO, "repo": REPO, "name": "netclient"})
    store.merge_node("CodeEntity", {
        "id": SSL, "repo": REPO, "name": "src/netclient/ssl_.py",
        "path": "src/netclient/ssl_.py", "entity_type": "File",
    })
    store.merge_node("Decision", {
        "id": "dec_add", "repo": REPO, "state": "ACTIVE",
        "summary": "Add TLS settings required for HTTP/2",
        "rationale": "RFC 7540 requires the newer cipher list.",
        "source_id": "pr:acme/netclient#3456",
    })
    store.merge_node("Decision", {
        "id": "dec_revert", "repo": REPO, "state": "ACTIVE",
        "summary": "Revert the addition of TLS settings for HTTP/2",
        "rationale": "The settings broke older proxies.",
        "source_id": "pr:acme/netclient#3466",
    })
    store.merge_relationship("GOVERNS", "dec_add", SSL, {})
    store.merge_relationship("GOVERNS", "dec_revert", SSL, {})
    # A decision whose text mentions the repository name and a directory word. A
    # question that merely says "netclient" (or names "src/...") must not be pulled
    # onto this entity through that coincidence.
    store.merge_node("Decision", {
        "id": "dec_docs", "repo": REPO, "state": "ACTIVE",
        "summary": "Document that netclient uses an src layout",
        "rationale": "netclient moved its package under src, so the docs were updated.",
        "source_id": "pr:acme/netclient#9",
    })
    store.merge_relationship("GOVERNS", "dec_docs", SSL, {})
    return store


def _source(store: InMemoryGraphStore) -> GraphDataSource:
    cfg = Settings(_env_file=None, data_source="graph", allow_mock_providers=True)
    return GraphDataSource(cfg, store=store)


def test_decisions_are_found_from_the_question_and_the_entity_derived() -> None:
    result = resolve_entity_from_decisions(
        "Why was HTTP/2 TLS support added and then reverted?", _store(), REPO
    )
    assert result is not None
    assert result.outcome is ResolutionOutcome.SUCCESS
    assert result.entity is not None
    assert result.entity.id == SSL


def test_a_question_matching_no_decision_yields_nothing() -> None:
    result = resolve_entity_from_decisions(
        "Why does netclient use Kubernetes for orchestration?", _store(), REPO
    )
    assert result is None


def test_ask_reaches_the_entity_found_from_the_decisions() -> None:
    response = _source(_store()).ask(
        REPO, AskRequest(question="Why was HTTP/2 TLS support added and then reverted?")
    )
    assert response.entity is not None
    assert response.entity.id == SSL
    # No evidence is stored, so the change is known but no quote can back it: the
    # gate says exactly that rather than inventing an answer.
    assert response.reason_code == "no_verified_quote"


def test_an_unrelated_question_refuses_without_calling_the_model() -> None:
    class Spy:
        is_real = False

        def complete_structured(self, *args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("the model must not be called for an unrelated question")

    source = _source(_store())
    source.provider = Spy()
    response = source.ask(
        REPO, AskRequest(question="Why does netclient use Kubernetes for orchestration?")
    )
    assert response.outcome == "refusal"
    assert response.reason_code == "entity_not_found"


def test_a_named_path_that_is_absent_refuses_without_reaching_the_decisions() -> None:
    class Spy:
        is_real = False

        def complete_structured(self, *args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("a named but absent path must not become an answer")

    source = _source(_store())
    source.provider = Spy()
    response = source.ask(
        REPO, AskRequest(question="Why was src/netclient/util/url.py changed?")
    )
    assert response.outcome == "refusal"
    assert response.reason_code == "entity_not_found"
