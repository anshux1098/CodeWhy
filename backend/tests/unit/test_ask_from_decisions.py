"""A question that names no entity is answered from the decisions' own text.

The entity resolver can only act on a name that appears in the question. Real
questions often name none ("why was HTTP/2 TLS support reverted?") while the
decisions themselves are full of the subject. These pin the fallback: the decisions
are found from their text, the entity is taken from them through GOVERNS, and a
question whose words match no decision stays a refusal instead of becoming a guess.
"""

from __future__ import annotations

import json

from app.config import Settings
from app.providers.llm_provider import MockLLMProvider
from app.schemas.ask import AskRequest
from app.schemas.common import Outcome
from app.services.data_source import GraphDataSource
from app.services.entity_resolution import ResolutionOutcome, resolve_entity_from_decisions
from app.stores.graph_store import InMemoryGraphStore

REPO = "acme/netclient"
SSL = "file:acme/netclient:src/netclient/ssl_.py"
#: An entity whose path happens to contain the token "http". It has nothing to do
#: with the HTTP/2 TLS change, so it must not steal a question that merely says "HTTP/2".
HTTP2 = "file:acme/netclient:src/netclient/http2/connection.py"


def _store() -> InMemoryGraphStore:
    store = InMemoryGraphStore()
    store.merge_node("Repository", {"id": REPO, "repo": REPO, "name": "netclient"})
    store.merge_node("CodeEntity", {
        "id": SSL, "repo": REPO, "name": "src/netclient/ssl_.py",
        "path": "src/netclient/ssl_.py", "entity_type": "File",
    })
    store.merge_node("Decision", {
        "id": "dec_add", "repo": REPO, "state": "ACTIVE",
        "summary": "Add HTTP/2 TLS support",
        "rationale": "HTTP/2 TLS support was added for the new client.",
        "source_id": "pr:acme/netclient#3456",
    })
    store.merge_node("Decision", {
        "id": "dec_revert", "repo": REPO, "state": "ACTIVE",
        "summary": "Revert HTTP/2 TLS support",
        "rationale": "HTTP/2 TLS support was added and then reverted.",
        "source_id": "pr:acme/netclient#3466",
    })
    store.merge_relationship("GOVERNS", "dec_add", SSL, {})
    store.merge_relationship("GOVERNS", "dec_revert", SSL, {})
    # A second entity whose name carries the token "http2" and an unrelated decision.
    # The question's loose "HTTP" token matches it (a substring of "http2"), which is a
    # coincidence: the entity route must not let that coincidence preempt the text route.
    store.merge_node("CodeEntity", {
        "id": HTTP2, "repo": REPO, "name": "src/netclient/http2/connection.py",
        "path": "src/netclient/http2/connection.py", "entity_type": "File",
    })
    store.merge_node("Decision", {
        "id": "dec_port0", "repo": REPO, "state": "ACTIVE",
        "summary": "Preserve an explicit port 0 in the URL",
        "rationale": "A falsy check dropped an explicit port 0 from the URL.",
        "source_id": "pr:acme/netclient#5101",
    })
    store.merge_relationship("GOVERNS", "dec_port0", HTTP2, {})
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
    # Offline forces the deterministic embedder, so the similarity the gate sees is
    # reproducible and no model weights are fetched.
    cfg = Settings(_env_file=None, data_source="graph", allow_mock_providers=True, offline=True)
    return GraphDataSource(cfg, store=store)


def _store_with_evidence() -> InMemoryGraphStore:
    """The same graph, now with a verified quote behind each decision.

    Source text is stored alongside each quote, because the answer path re-verifies
    every quote against it before citing.
    """
    store = _store()
    evidence = {
        "ev_add": ("dec_add", "pr:acme/netclient#3456",
                   "https://github.com/acme/netclient/pull/3456",
                   "Add the TLS settings that HTTP/2 needs"),
        "ev_revert": ("dec_revert", "pr:acme/netclient#3466",
                      "https://github.com/acme/netclient/pull/3466",
                      "Revert the TLS settings that HTTP/2 needs"),
        "ev_port0": ("dec_port0", "pr:acme/netclient#5101",
                     "https://github.com/acme/netclient/pull/5101",
                     "Keep an explicit port 0 in the URL"),
    }
    for ev_id, (decision_id, source_id, source_url, quote) in evidence.items():
        store.merge_node("Evidence", {
            "id": ev_id, "repo": REPO, "decision_id": decision_id,
            "source_id": source_id, "source_type": "pull_request",
            "source_url": source_url, "quote": quote, "claim": quote,
            "author": "real-reviewer", "timestamp": "2024-03-01T00:00:00Z",
            "quote_verified": True,
        })
        store.merge_relationship("SUPPORTED_BY", decision_id, ev_id, {})
        store.source_texts[source_id] = quote
    return store


def test_the_http2_question_is_answered_from_the_ssl_decisions() -> None:
    source = _source(_store_with_evidence())
    source.provider = MockLLMProvider(canned_response=json.dumps({
        "answer": "TLS support was added for HTTP/2 in #3456 and reverted in #3466.",
        "cited_evidence_ids": ["ev_add", "ev_revert"],
    }))

    response = source.ask(
        REPO, AskRequest(question="Why was HTTP/2 TLS support added and then reverted?")
    )

    # The loose "HTTP" token inside the http2 path is a coincidence, not a reference.
    # The decisions whose text is actually about the change win, and the answer cites
    # both the addition and the revert.
    assert response.entity is not None
    assert response.entity.id == SSL
    assert response.outcome == Outcome.FULL
    urls = {citation.source_url for citation in response.citations}
    assert "https://github.com/acme/netclient/pull/3456" in urls
    assert "https://github.com/acme/netclient/pull/3466" in urls


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
