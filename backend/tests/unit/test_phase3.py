from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import settings
from app.providers.embeddings import DeterministicFallbackEmbeddingProvider
from app.providers.llm_provider import MockLLMProvider
from app.schemas.common import ConfidenceLabel, EntityType, Outcome, ReasonCode
from app.services.answer import generate_answer
from app.services.confidence import calculate_confidence
from app.services.entity_resolution import (
    ResolutionOutcome,
    ResolutionResult,
    extract_query_tokens,
    is_out_of_scope,
    resolve_entity,
)
from app.services.gate import GateOutcome, evaluate_refusal_gate
from app.services.retrieval import EvidenceBundle, RetrievedEvidenceItem, retrieve_evidence
from app.stores.graph_store import InMemoryGraphStore


# ===========================================================================
# 1. Entity Resolution Tests
# ===========================================================================

AVAILABLE_ENTITIES = [
    {
        "id": "entity:hynek/structlog:src/structlog/processors.py",
        "name": "src/structlog/processors.py",
        "path": "src/structlog/processors.py",
        "entity_type": "File",
    },
    {
        "id": "entity:hynek/structlog:NAME_TO_LEVEL",
        "name": "NAME_TO_LEVEL",
        "path": "src/structlog/processors.py",
        "entity_type": "ConfigKey",
    },
    {
        "id": "entity:hynek/structlog:src/structlog/_config.py",
        "name": "src/structlog/_config.py",
        "path": "src/structlog/_config.py",
        "entity_type": "File",
    },
    {
        "id": "entity:hynek/structlog:DEFAULT_PROCESSORS",
        "name": "DEFAULT_PROCESSORS",
        "path": "src/structlog/_config.py",
        "entity_type": "ConfigKey",
    },
]


def test_entity_resolution_exact_match_wins() -> None:
    res = resolve_entity("Why is NAME_TO_LEVEL defined this way?", AVAILABLE_ENTITIES)
    assert res.outcome == ResolutionOutcome.SUCCESS
    assert res.entity is not None
    assert res.entity.name == "NAME_TO_LEVEL"


def test_entity_resolution_file_path_match() -> None:
    res = resolve_entity("Why does processors.py format timestamps?", AVAILABLE_ENTITIES)
    assert res.outcome == ResolutionOutcome.SUCCESS
    assert res.entity is not None
    assert "processors.py" in res.entity.name


def test_entity_resolution_out_of_scope() -> None:
    res = resolve_entity("Why was the team late for the demo?", AVAILABLE_ENTITIES)
    assert res.outcome == ResolutionOutcome.REFUSAL
    assert res.reason_code == "out_of_scope"


def test_entity_resolution_entity_not_found() -> None:
    res = resolve_entity("Why is NON_EXISTENT_CONSTANT set to 500?", AVAILABLE_ENTITIES)
    assert res.outcome == ResolutionOutcome.REFUSAL
    assert res.reason_code == "entity_not_found"


def test_entity_resolution_ambiguous_entity() -> None:
    # "structlog" matches both processors.py and _config.py similarly
    ambig_entities = [
        {"id": "e1", "name": "retry.py", "path": "pkg/retry.py", "entity_type": "File"},
        {"id": "e2", "name": "RETRY_BACKOFF_MS", "path": "pkg/retry.py", "entity_type": "ConfigKey"},
    ]
    res = resolve_entity("Why is retry set this way?", ambig_entities)
    assert res.outcome == ResolutionOutcome.AMBIGUOUS
    assert res.reason_code == "ambiguous_entity"
    assert len(res.candidates) >= 2


# ===========================================================================
# 2. Refusal Gate Tests (G1, G2, G3, G4)
# ===========================================================================

def test_gate_g1_entity_failure() -> None:
    res = ResolutionResult(outcome=ResolutionOutcome.REFUSAL, reason_code="entity_not_found")
    gate_res = evaluate_refusal_gate(res, bundle=None)
    assert gate_res.outcome == GateOutcome.REFUSAL
    assert gate_res.reason_code == "entity_not_found"
    assert gate_res.gate_name == "G1"


def test_gate_g2_no_decision_path() -> None:
    res = resolve_entity("Why is NAME_TO_LEVEL defined?", AVAILABLE_ENTITIES)
    assert res.entity is not None
    empty_bundle = EvidenceBundle(
        question="Why is NAME_TO_LEVEL defined?",
        resolved_entity=res.entity.__dict__,
        decisions=[],  # No decisions connected via GOVERNS
    )
    gate_res = evaluate_refusal_gate(res, empty_bundle)
    assert gate_res.outcome == GateOutcome.REFUSAL
    assert gate_res.reason_code == "no_decision_path"
    assert gate_res.gate_name == "G2"


def test_gate_g3_no_verified_quote_partial() -> None:
    res = resolve_entity("Why is NAME_TO_LEVEL defined?", AVAILABLE_ENTITIES)
    assert res.entity is not None
    bundle = EvidenceBundle(
        question="Why is NAME_TO_LEVEL defined?",
        resolved_entity=res.entity.__dict__,
        decisions=[{"id": "dec_1", "summary": "Map level names", "state": "ACTIVE"}],
        evidence_items=[
            RetrievedEvidenceItem(
                id="ev_1",
                decision_id="dec_1",
                source_id="pr:1",
                source_type="PullRequest",
                source_url="http://example.com",
                quote="",  # Empty / unverified
                claim="Map level names",
                quote_verified=False,
                similarity_score=0.9,
            )
        ],
        best_similarity_score=0.9,
    )
    gate_res = evaluate_refusal_gate(res, bundle, min_score=0.55)
    assert gate_res.outcome == GateOutcome.PARTIAL
    assert gate_res.reason_code == "no_verified_quote"
    assert gate_res.gate_name == "G3"


def test_gate_g4_low_score_refusal() -> None:
    res = resolve_entity("Why is NAME_TO_LEVEL defined?", AVAILABLE_ENTITIES)
    assert res.entity is not None
    bundle = EvidenceBundle(
        question="Why is NAME_TO_LEVEL defined?",
        resolved_entity=res.entity.__dict__,
        decisions=[{"id": "dec_1", "summary": "Completely unrelated topic", "state": "ACTIVE"}],
        evidence_items=[
            RetrievedEvidenceItem(
                id="ev_1",
                decision_id="dec_1",
                source_id="pr:1",
                source_type="PullRequest",
                source_url="http://example.com",
                quote="Some text",
                claim="Claim",
                quote_verified=True,
                similarity_score=0.2,
            )
        ],
        best_similarity_score=0.20,  # Below MIN_SCORE 0.55
    )
    gate_res = evaluate_refusal_gate(res, bundle, min_score=0.55)
    assert gate_res.outcome == GateOutcome.REFUSAL
    assert gate_res.reason_code == "low_score"
    assert gate_res.gate_name == "G4"


# ===========================================================================
# 3. Graph Store & Rebuild Tests
# ===========================================================================

def test_in_memory_graph_store_operations() -> None:
    store = InMemoryGraphStore()
    store.init_schema()

    # Node merges
    store.merge_node("Repository", {"id": "hynek/structlog", "name": "structlog", "repo": "hynek/structlog"})
    store.merge_node("CodeEntity", {
        "id": "ent_1",
        "repo": "hynek/structlog",
        "name": "NAME_TO_LEVEL",
        "path": "src/structlog/processors.py",
        "entity_type": "ConfigKey",
    })
    store.merge_node("Decision", {
        "id": "dec_1",
        "repo": "hynek/structlog",
        "summary": "Configure logging levels mapping",
        "state": "ACTIVE",
    })
    store.merge_node("Evidence", {
        "id": "ev_1",
        "decision_id": "dec_1",
        "source_id": "pr:1",
        "source_type": "PullRequest",
        "source_url": "https://github.com/hynek/structlog/pull/1",
        "quote": "NAME_TO_LEVEL = {...}",
        "quote_verified": True,
    })

    # Relationship merges
    store.merge_relationship("GOVERNS", "dec_1", "ent_1")
    store.merge_relationship("SUPPORTED_BY", "dec_1", "ev_1")

    # Queries
    ent = store.get_entity("hynek/structlog", "NAME_TO_LEVEL")
    assert ent is not None
    assert ent["name"] == "NAME_TO_LEVEL"

    decs = store.get_decisions_for_entity("ent_1")
    assert len(decs) == 1
    assert decs[0]["id"] == "dec_1"
    assert len(decs[0]["evidence"]) == 1

    subgraph = store.get_subgraph("hynek/structlog", entity_id="ent_1")
    assert len(subgraph["nodes"]) >= 2
    assert len(subgraph["relationships"]) >= 1


# ===========================================================================
# 4. End-to-End Grounded Answer & Citation Tests
# ===========================================================================

def test_generate_answer_full_success() -> None:
    res = resolve_entity("Why is NAME_TO_LEVEL defined?", AVAILABLE_ENTITIES)
    assert res.entity is not None

    bundle = EvidenceBundle(
        question="Why is NAME_TO_LEVEL defined?",
        resolved_entity=res.entity.__dict__,
        decisions=[
            {
                "id": "dec_1",
                "summary": "Map logging levels to integers",
                "rationale": "Fast O(1) integer lookup for stdlib parity",
                "state": "ACTIVE",
                "repo": "hynek/structlog",
            }
        ],
        evidence_items=[
            RetrievedEvidenceItem(
                id="ev_1",
                decision_id="dec_1",
                source_id="pr:10",
                source_type="PullRequest",
                source_url="https://github.com/hynek/structlog/pull/10",
                quote="NAME_TO_LEVEL provides O(1) level integer mapping",
                claim="Level mapping",
                quote_verified=True,
                similarity_score=0.92,
            )
        ],
        best_similarity_score=0.92,
        source_texts={
            "pr:10": "NAME_TO_LEVEL provides O(1) level integer mapping for stdlib parity.",
        },
    )

    canned_llm = json.dumps({
        "answer": "NAME_TO_LEVEL is defined to provide O(1) integer lookup for stdlib logging level parity.",
        "cited_evidence_ids": ["ev_1"],
    })
    provider = MockLLMProvider(canned_response=canned_llm)

    response = generate_answer("Why is NAME_TO_LEVEL defined?", res, bundle, provider)
    assert response.outcome == Outcome.FULL
    assert response.reason_code is None
    assert response.confidence is not None
    assert response.confidence.label == ConfidenceLabel.HIGH
    assert len(response.citations) >= 1
    assert response.citations[0].quote == "NAME_TO_LEVEL provides O(1) level integer mapping"


def test_generate_answer_refusal_when_unanswerable() -> None:
    res = resolve_entity("Why was the team late for the demo?", AVAILABLE_ENTITIES)
    provider = MockLLMProvider()
    response = generate_answer("Why was the team late for the demo?", res, None, provider)
    assert response.outcome == Outcome.REFUSAL
    assert response.reason_code == ReasonCode.OUT_OF_SCOPE
    assert response.answer is not None
    assert len(response.evidence_gaps) >= 1


def test_generate_answer_partial_when_no_verified_quote() -> None:
    res = resolve_entity("Why is NAME_TO_LEVEL defined?", AVAILABLE_ENTITIES)
    assert res.entity is not None
    bundle = EvidenceBundle(
        question="Why is NAME_TO_LEVEL defined?",
        resolved_entity=res.entity.__dict__,
        decisions=[
            {
                "id": "dec_1",
                "summary": "Add NAME_TO_LEVEL",
                "state": "ACTIVE",
                "repo": "hynek/structlog",
            }
        ],
        evidence_items=[
            RetrievedEvidenceItem(
                id="ev_1",
                decision_id="dec_1",
                source_id="pr:10",
                source_type="PullRequest",
                source_url="https://github.com/hynek/structlog/pull/10",
                quote="Fake unverified quote",
                claim="Claim",
                quote_verified=False,  # Unverified!
                similarity_score=0.85,
            )
        ],
        best_similarity_score=0.85,
    )
    provider = MockLLMProvider()
    response = generate_answer("Why is NAME_TO_LEVEL defined?", res, bundle, provider)
    assert response.outcome == Outcome.PARTIAL
    assert response.reason_code == ReasonCode.NO_VERIFIED_QUOTE
    assert response.citations == []  # Forbidden when no_verified_quote
    assert response.confidence is not None
    assert response.confidence.label in {ConfidenceLabel.MEDIUM, ConfidenceLabel.LOW}


# ===========================================================================
# 5. GraphDataSource Integration Tests
# ===========================================================================

def test_graph_data_source_full_flow() -> None:
    from app.schemas.ask import AskRequest
    from app.services.data_source import GraphDataSource

    store = InMemoryGraphStore()
    store.init_schema()

    # Seed store
    store.merge_node("Repository", {"id": "hynek/structlog", "name": "structlog", "repo": "hynek/structlog"})
    store.merge_node("CodeEntity", {
        "id": "entity:hynek/structlog:NAME_TO_LEVEL",
        "repo": "hynek/structlog",
        "name": "NAME_TO_LEVEL",
        "path": "src/structlog/processors.py",
        "entity_type": "ConfigKey",
    })
    store.merge_node("Decision", {
        "id": "dec_1",
        "repo": "hynek/structlog",
        "summary": "Why is NAME_TO_LEVEL defined for logging level lookup",
        "state": "ACTIVE",
    })
    store.merge_node("Evidence", {
        "id": "ev_1",
        "decision_id": "dec_1",
        "source_id": "pr:1",
        "source_type": "PullRequest",
        "source_url": "https://github.com/hynek/structlog/pull/1",
        "quote": "Map names to levels",
        "quote_verified": True,
    })
    store.merge_relationship("GOVERNS", "dec_1", "entity:hynek/structlog:NAME_TO_LEVEL")
    store.merge_relationship("SUPPORTED_BY", "dec_1", "ev_1")
    # The quote is only citable if its source text is available for re-verification.
    store.source_texts["pr:1"] = "Map names to levels so stdlib consumers see integers."
    assert store.source_text_for("pr:1")

    source = GraphDataSource(store=store)

    # Search entities
    ents = source.search_entities("hynek/structlog", "NAME_TO_LEVEL")
    assert len(ents.entities) >= 1
    assert ents.entities[0].label == "NAME_TO_LEVEL"
    assert ents.fixture is False

    # Ask endpoint
    canned = json.dumps({
        "answer": "NAME_TO_LEVEL maps string level names to numeric logging levels.",
        "cited_evidence_ids": ["ev_1"],
    })
    source.provider = MockLLMProvider(canned_response=canned)

    resp = source.ask("hynek/structlog", AskRequest(question="Why is NAME_TO_LEVEL defined?"))
    assert resp.outcome == Outcome.FULL
    assert resp.fixture is False
    assert len(resp.citations) >= 1

    # Get graph
    graph_resp = source.get_graph("hynek/structlog", entity_id="entity:hynek/structlog:NAME_TO_LEVEL")
    assert graph_resp.fixture is False
    assert len(graph_resp.nodes) >= 1

