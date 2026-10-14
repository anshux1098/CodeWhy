"""Confidence inputs must be derived from independent evidence.

Three defects are covered here: agreement counted citations instead of independent
sources, every decision claimed to come from pull/1 with a fixed timestamp, and
the gate threshold ignored the Settings handed to the data source.
"""

from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.providers.llm_provider import MockLLMProvider
from app.schemas.ask import AskRequest
from app.services import answer as answer_module
from app.services.answer import generate_answer
from app.services.confidence import calculate_confidence
from app.services.data_source import DataSourceError, GraphDataSource
from app.services.entity_resolution import resolve_entity
from app.services.retrieval import EvidenceBundle, RetrievedEvidenceItem
from app.stores.graph_store import InMemoryGraphStore

REPO = "acme/netclient"
QUESTION = "Why is MAX_RETRIES 3?"


def provider() -> MockLLMProvider:
    return MockLLMProvider(canned_response=json.dumps({
        "answer": "raised because flaky networks",
        "cited_evidence_ids": ["ev1", "ev2", "ev3"],
    }))


def ev(ident: str, author: str, quote: str, number: str) -> RetrievedEvidenceItem:
    """An evidence item with a realistic stable source id, pr:<repo>#<number>."""
    return RetrievedEvidenceItem(
        id=ident, decision_id="d1", source_id=f"pr:{REPO}#{number}",
        source_type="pull_request",
        source_url=f"https://github.com/{REPO}/pull/{number}",
        quote=quote, claim="cap raised", author=author,
        timestamp="2025-01-01T00:00:00Z", quote_verified=True, similarity_score=0.95,
    )


def mk_bundle(items: list[RetrievedEvidenceItem], source_text: str) -> EvidenceBundle:
    entities = [{"id": "e1", "name": "MAX_RETRIES", "path": "pkg/config.py",
                 "entity_type": "ConfigKey"}]
    resolution = resolve_entity(QUESTION, entities)
    return EvidenceBundle(
        question=QUESTION,
        resolved_entity=entities[0],
        decisions=[{"id": "d1", "repo": REPO, "summary": "Raised the cap",
                    "rationale": "flaky networks", "state": "ACTIVE",
                    "source_id": items[0].source_id}],
        evidence_items=items,
        best_similarity_score=0.95,
        source_texts={i.source_id: source_text for i in items},
    )


@pytest.fixture(autouse=True)
def _gates_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(answer_module.settings, "min_score", 0.0)


def run(items, source_text="flaky networks on mobile"):
    entities = [{"id": "e1", "name": "MAX_RETRIES", "path": "pkg/config.py",
                 "entity_type": "ConfigKey"}]
    resolution = resolve_entity(QUESTION, entities)
    bundle = mk_bundle(items, source_text)
    return generate_answer(question=QUESTION, resolution=resolution, bundle=bundle,
                           provider=provider(), is_real=True)


# --- agreement -------------------------------------------------------------


def test_agreement_counts_independent_document_author_pairs() -> None:
    from app.services.answer import agreement_from_citations

    class C:
        def __init__(self, src: str, author: str) -> None:
            self.source_url, self.author = src, author

    one = [C("https://x/1", "ann")]
    assert agreement_from_citations(one) == 0.4
    assert agreement_from_citations([C("https://x/1", "ann"), C("https://x/1", "bob")]) == 0.7
    assert agreement_from_citations(
        [C("https://x/1", "ann"), C("https://x/1", "bob"), C("https://x/2", "ann")]
    ) == 1.0


def test_two_citations_from_the_same_document_and_author_count_once() -> None:
    from app.services.answer import agreement_from_citations

    class C:
        def __init__(self, src: str, author: str) -> None:
            self.source_url, self.author = src, author

    same = [C("https://x/1", "ann"), C("https://x/1", "ann")]
    assert agreement_from_citations(same) == 0.4, "one source is not corroboration"


def test_the_answer_scores_agreement_from_independence_not_from_count() -> None:
    same_source = [
        ev("ev1", "ann", "flaky networks", "1"),
        ev("ev2", "ann", "flaky networks", "1"),
    ]
    independent = [
        ev("ev1", "ann", "flaky networks", "1"),
        ev("ev2", "bob", "flaky networks", "2"),
    ]
    same = run(same_source).confidence.signals.agreement
    indep = run(independent).confidence.signals.agreement
    assert same == 0.4
    assert indep == 0.7
    assert indep > same


# --- provenance ------------------------------------------------------------


def test_decisions_carry_their_real_source_number() -> None:
    response = run([ev("ev1", "ann", "flaky networks", "1")])
    decision = response.decisions[0]
    assert decision.source.number == 1
    assert decision.source.url == f"https://github.com/{REPO}/pull/1"
    assert "pull/1" in decision.source.url


def test_a_decision_does_not_claim_pull_one_regardless_of_its_source() -> None:
    response = run([ev("ev1", "ann", "flaky networks", "4821")])
    assert response.decisions[0].source.number == 4821


def test_no_fixed_placeholder_timestamp_is_emitted() -> None:
    import inspect

    from app.services import answer as mod

    assert "2026-01-01T00:00:00Z" not in inspect.getsource(mod)
    assert '"pull/1"' not in inspect.getsource(mod)
    assert "'pull/1'" not in inspect.getsource(mod)


def test_a_missing_timestamp_is_null_rather_than_invented() -> None:
    item = ev("ev1", "ann", "flaky networks", "1")
    item.timestamp = None
    response = run([item])
    assert response.citations[0].timestamp is None


def test_source_type_comes_from_the_evidence_node() -> None:
    """A citation's kind is the stored source type, not a hardcoded pull request."""
    item = ev("ev1", "ann", "flaky networks", "1")
    item.source_type = "issue"
    response = run([item])
    assert response.citations[0].source_type.value == "Issue"


# --- settings threading ----------------------------------------------------


def test_graph_data_source_uses_its_own_min_score(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Settings handed to the source must actually reach the gate."""
    from app.services import answer as mod

    monkeypatch.setattr(mod.settings, "min_score", 0.0)
    store = InMemoryGraphStore()
    store.merge_node("CodeEntity", {"id": "e1", "repo": REPO, "name": "MAX_RETRIES",
                                    "path": "pkg/config.py", "entity_type": "ConfigKey"})
    store.merge_node("Decision", {"id": "d1", "repo": REPO, "summary": "s",
                                  "rationale": "flaky networks", "state": "ACTIVE",
                                  "source_id": f"pr:{REPO}#1"})
    store.merge_node("Evidence", {"id": "ev1", "source_id": f"pr:{REPO}#1", "source_type": "pull_request",
                                  "source_url": f"https://github.com/{REPO}/pull/1",
                                  "quote": "flaky networks", "claim": "c",
                                  "author": "ann", "timestamp": "2025-01-01T00:00:00Z",
                                  "quote_verified": True})
    store.merge_relationship("GOVERNS", "d1", "e1", {})
    store.merge_relationship("SUPPORTED_BY", "d1", "ev1", {})
    store.source_texts[f"pr:{REPO}#1"] = "flaky networks"

    strict = GraphDataSource(Settings(_env_file=None, allow_mock_providers=True,
                                      min_score=0.99), store=store)
    strict.provider = provider()
    blocked = strict.ask(REPO, AskRequest(question=QUESTION))
    assert blocked.reason_code == "low_score", "the injected min_score must be honoured"

    lenient = GraphDataSource(Settings(_env_file=None, allow_mock_providers=True,
                                       min_score=0.0), store=store)
    lenient.provider = provider()
    allowed = lenient.ask(REPO, AskRequest(question=QUESTION))
    assert allowed.reason_code != "low_score"


def test_generate_answer_never_reads_the_module_global_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    import inspect

    from app.services import answer as mod

    source = inspect.getsource(mod.generate_answer)
    assert "min_score=settings.min_score" not in source, (
        "generate_answer still reads the module-global settings instead of a parameter"
    )


def test_confidence_formula_is_unchanged() -> None:
    """R6 must not disturb the weighting or the contradiction cap."""
    score = calculate_confidence(
        directness=1.0, provenance=0.8, agreement=0.7, relevance=0.88,
        temporal_consistency=1.0, contradiction=0.0,
    )
    assert score.score == pytest.approx(0.30 + 0.16 + 0.14 + 0.15 * 0.88 + 0.15, abs=1e-4)
    # With contradiction the raw score is 0.70 - 0.30 = 0.60, so the cap is not
    # reached here; what matters is that no contradiction case can exceed it.
    capped = calculate_confidence(
        directness=1.0, provenance=1.0, agreement=1.0, relevance=1.0,
        temporal_consistency=1.0, contradiction=1.0,
    )
    assert capped.score <= 0.70


def test_a_decision_without_provenance_is_refused_not_invented() -> None:
    from app.services.data_source import source_ref_for

    with pytest.raises(DataSourceError):
        source_ref_for({"id": "d1", "summary": "s"})


def test_provenance_is_derived_from_a_stable_source_id() -> None:
    from app.services.data_source import source_ref_for

    ref = source_ref_for({"source_id": f"pr:{REPO}#4821"})
    assert ref.number == 4821
    assert ref.url == f"https://github.com/{REPO}/pull/4821"
    assert ref.type.value == "PullRequest"


def test_an_issue_source_id_yields_an_issue_reference() -> None:
    from app.services.data_source import source_ref_for

    ref = source_ref_for({"source_id": f"issue:{REPO}#77"})
    assert ref.type.value == "Issue"
    assert ref.number == 77
    assert ref.url.endswith("/issues/77")
