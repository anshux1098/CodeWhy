"""Unit tests for G3 Claim-Level NLI / Faithfulness Verification (Point 3)."""

from __future__ import annotations

import json

from app.config import Settings
from app.providers.llm_provider import MockLLMProvider
from app.schemas.common import ConfidenceLabel, Outcome
from app.services.answer import generate_answer
from app.services.entity_resolution import EntityCandidate, ResolutionOutcome, ResolutionResult
from app.services.faithfulness import (
    EntailmentLabel,
    SemanticEntailmentVerifier,
    decompose_claims,
    verify_answer_faithfulness,
)
from app.services.retrieval import EvidenceBundle, RetrievedEvidenceItem
from app.stores.graph_store import InMemoryGraphStore


def _cfg(**overrides) -> Settings:
    defaults = dict(_env_file=None, offline=True, min_score=0.0)
    defaults.update(overrides)
    return Settings(**defaults)


def test_decompose_claims_preserves_paths_and_splits_sentences() -> None:
    text = (
        "Retry backoff in src/retry.py was capped at 3 attempts. "
        "Upstream gateways rate-limited clients that retried aggressively."
    )
    claims = decompose_claims(text)
    assert len(claims) == 2
    assert "src/retry.py" in claims[0]
    assert "rate-limited" in claims[1]


def test_nli_verifier_entails_supported_claim_and_flags_contradiction() -> None:
    verifier = SemanticEntailmentVerifier(cfg=_cfg())
    premise = "TLS certificate hostname verification is enabled by default to prevent MITM attacks."

    supported = verifier.verify_pair(
        premise,
        "Hostname verification is enabled to prevent MITM attacks.",
    )
    assert supported.label == EntailmentLabel.ENTAILED
    assert supported.entailment >= 0.45

    contradicted = verifier.verify_pair(
        premise,
        "TLS certificate hostname verification is disabled by default.",
    )
    assert contradicted.label == EntailmentLabel.CONTRADICTED
    assert contradicted.contradiction >= 0.75


def test_nli_verifier_detects_numeric_contradiction() -> None:
    verifier = SemanticEntailmentVerifier(cfg=_cfg())
    premise = "The retry budget was capped at 3 attempts to avoid gateway throttling."
    res = verifier.verify_pair(
        premise,
        "The retry budget was capped at 50 attempts to avoid gateway throttling.",
    )
    assert res.label == EntailmentLabel.CONTRADICTED


def test_generate_answer_degrades_hallucinated_or_contradicted_llm_output() -> None:
    quote = "TLS certificate verification is enabled by default to block MITM attacks."
    source_id = "pr:acme/net#12"
    bundle = EvidenceBundle(
        question="Why is TLS verification enabled?",
        resolved_entity={"id": "file:acme/net:src/tls.py", "name": "src/tls.py", "path": "src/tls.py"},
        decisions=[{
            "id": "dec_tls",
            "summary": "Enable TLS certificate verification by default",
            "rationale": quote,
            "state": "ACTIVE",
            "source_id": source_id,
        }],
        evidence_items=[
            RetrievedEvidenceItem(
                id="ev_tls",
                decision_id="dec_tls",
                source_id=source_id,
                source_type="pull_request",
                source_url="https://github.com/acme/net/pull/12",
                quote=quote,
                claim="TLS verification enabled",
                quote_verified=True,
                similarity_score=0.95,
            )
        ],
        best_similarity_score=0.95,
        source_texts={source_id: quote},
    )
    res = ResolutionResult(
        outcome=ResolutionOutcome.SUCCESS,
        entity=EntityCandidate(id="file:acme/net:src/tls.py", name="src/tls.py", path="src/tls.py", entity_type="File", score=1.0),
    )

    # Hallucinated & contradicted LLM answer
    bad_provider = MockLLMProvider(canned_response=json.dumps({
        "answer": "TLS certificate verification is disabled by default for faster benchmarks.",
        "cited_evidence_ids": ["ev_tls"],
    }))
    ans = generate_answer(
        question="Why is TLS verification enabled?",
        resolution=res,
        bundle=bundle,
        provider=bad_provider,
        store=InMemoryGraphStore(),
        min_score=0.0,
        cfg=_cfg(),
    )
    assert ans.outcome in (Outcome.PARTIAL, Outcome.REFUSAL)
    assert ans.confidence is not None
    assert ans.confidence.signals.contradiction == 1.0
    assert ans.confidence.score <= 0.70
    assert ans.confidence.label != ConfidenceLabel.HIGH
    assert any("contradiction" in g.lower() for g in ans.evidence_gaps)


def test_verify_answer_faithfulness_supports_joint_multi_evidence_synthesis() -> None:
    report = verify_answer_faithfulness(
        "TLS support was added in #3456 and later reverted in #3466.",
        [
            ("cit_1", "Add the TLS settings that HTTP/2 needs in #3456."),
            ("cit_2", "Revert the TLS settings that HTTP/2 needs in #3466."),
        ],
        cfg=_cfg(),
    )
    assert report.contradiction_detected is False
    assert report.entailment_rate == 1.0
    assert report.verified_claims == 1
