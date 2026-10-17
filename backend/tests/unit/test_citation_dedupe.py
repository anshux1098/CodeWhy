"""One response must not cite the same source twice with one quote inside another.

The live answers returned several citations that pointed at the same pull request
where one quote was a fragment of another. Two quotes lifted from the same source,
one contained in the other, are the same claim printed twice, so only the longest
whole quote is kept.

These cover the shared helper, the answer path, and the decision-detail path.
"""

from __future__ import annotations

import json

from app.config import Settings
from app.providers.llm_provider import MockLLMProvider
from app.schemas.common import CitationKind, SourceType
from app.schemas.decisions import Citation
from app.services.answer import dedupe_citations, generate_answer
from app.services.data_source import GraphDataSource
from app.services.entity_resolution import EntityCandidate, ResolutionOutcome, ResolutionResult
from app.services.retrieval import EvidenceBundle, RetrievedEvidenceItem
from app.stores.graph_store import InMemoryGraphStore

SRC = "https://github.com/acme/netclient/pull/7"
LONG = "The retry cap was raised to 3 because mobile clients kept timing out on flaky networks."
SHORT = "mobile clients kept timing out"


def _cite(cid: str, url: str, quote: str, decision_id: str = "d1") -> Citation:
    return Citation(
        id=cid,
        decision_id=decision_id,
        kind=CitationKind.SOURCE,
        quote=quote,
        source_url=url,
        source_type=SourceType.PULL_REQUEST,
        author="ann",
        timestamp=None,
    )


# --- the helper -------------------------------------------------------------


def test_a_quote_contained_in_another_from_the_same_source_is_dropped() -> None:
    citations = [_cite("cit_short", SRC, SHORT), _cite("cit_long", SRC, LONG)]
    assert [c.id for c in dedupe_citations(citations)] == ["cit_long"]


def test_containment_is_decided_per_source() -> None:
    """The same words from a different document are a separate citation."""
    other = "https://github.com/acme/netclient/pull/8"
    citations = [_cite("cit_a", SRC, SHORT), _cite("cit_b", other, SHORT)]
    assert len(dedupe_citations(citations)) == 2


def test_identical_duplicates_collapse_to_one() -> None:
    citations = [_cite("cit_a", SRC, LONG), _cite("cit_b", SRC, LONG)]
    assert len(dedupe_citations(citations)) == 1


def test_unrelated_quotes_keep_their_order() -> None:
    other = "https://github.com/acme/netclient/pull/8"
    citations = [
        _cite("cit_a", SRC, LONG),
        _cite("cit_b", other, "A different rationale entirely."),
        _cite("cit_c", SRC, SHORT),
    ]
    assert [c.id for c in dedupe_citations(citations)] == ["cit_a", "cit_b"]


# --- the answer path --------------------------------------------------------


def _bundle() -> EvidenceBundle:
    def item(ev_id: str, quote: str) -> RetrievedEvidenceItem:
        return RetrievedEvidenceItem(
            id=ev_id,
            decision_id="d1",
            source_id="pr:acme/netclient#7",
            source_type="pull_request",
            source_url=SRC,
            quote=quote,
            claim="cap raised",
            author="ann",
            timestamp=None,
            quote_verified=True,
            similarity_score=0.9,
        )

    return EvidenceBundle(
        question="Why is MAX_RETRIES 3?",
        resolved_entity={
            "id": "e1", "name": "MAX_RETRIES", "path": "pkg/config.py",
            "entity_type": "ConfigKey",
        },
        decisions=[{
            "id": "d1", "source_id": "pr:acme/netclient#7", "source_url": SRC,
            "source_number": 7, "source_type": "pull_request",
            "summary": "Raised the cap", "state": "ACTIVE",
        }],
        evidence_items=[item("ev1", SHORT), item("ev2", LONG)],
        best_similarity_score=0.9,
        source_texts={"pr:acme/netclient#7": LONG},
    )


def test_the_answer_cites_the_longest_quote_from_a_source_once() -> None:
    provider = MockLLMProvider(
        response_factory=lambda prompt, system: json.dumps(
            {"answer": "Clients kept timing out.", "cited_evidence_ids": ["ev1", "ev2"]}
        )
    )
    resolution = ResolutionResult(
        outcome=ResolutionOutcome.SUCCESS,
        entity=EntityCandidate(
            id="e1", name="MAX_RETRIES", path="pkg/config.py",
            entity_type="ConfigKey", score=1.0,
        ),
    )

    response = generate_answer(
        question="Why is MAX_RETRIES 3?",
        resolution=resolution,
        bundle=_bundle(),
        provider=provider,
        is_real=False,
        min_score=0.5,
        cfg=Settings(_env_file=None),
    )

    assert [c.quote for c in response.citations] == [LONG]


# --- the decision-detail path ----------------------------------------------


def test_a_decision_detail_dedupes_its_evidence() -> None:
    store = InMemoryGraphStore()
    repo = "acme/netclient"
    store.merge_node("Repository", {"id": repo, "name": "netclient", "repo": repo})
    store.merge_node("Decision", {
        "id": "d1", "repo": repo, "summary": "Raised the cap", "state": "ACTIVE",
        "source_id": f"pr:{repo}#7", "source_url": SRC, "source_number": 7,
        "source_type": "pull_request",
    })
    for ev_id, quote in (("ev1", SHORT), ("ev2", LONG)):
        store.merge_node("Evidence", {
            "id": ev_id, "repo": repo, "decision_id": "d1",
            "source_id": f"pr:{repo}#7", "source_type": "pull_request",
            "source_url": SRC, "quote": quote, "author": "ann", "quote_verified": True,
        })
        store.merge_relationship("SUPPORTED_BY", "d1", ev_id, {})

    detail = GraphDataSource(Settings(_env_file=None), store=store).get_decision("d1")

    assert [c.quote for c in detail.citations] == [LONG]
