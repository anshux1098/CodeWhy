"""Unit tests for G2 Multi-Hop Evidence Retrieval & Graceful Degradation (Point 2)."""

from __future__ import annotations

import json

from app.config import Settings
from app.providers.llm_provider import MockLLMProvider
from app.schemas.common import ConfidenceLabel, Outcome, ReasonCode
from app.services.answer import generate_answer
from app.services.entity_resolution import EntityCandidate, ResolutionOutcome, ResolutionResult
from app.services.gate import GateOutcome, evaluate_refusal_gate
from app.services.retrieval import EvidenceTier, retrieve_evidence
from app.stores.graph_store import InMemoryGraphStore

REPO = "acme/payments"


def _cfg(**overrides) -> Settings:
    defaults = dict(_env_file=None, offline=True, min_score=0.0)
    defaults.update(overrides)
    return Settings(**defaults)


def test_tier2_parent_module_fallback_degrades_directness_gracefully() -> None:
    store = InMemoryGraphStore()
    file_id = f"file:{REPO}:src/auth/jwt.py"
    mod_id = f"module:{REPO}:src/auth"
    store.merge_node("CodeEntity", {
        "id": mod_id, "repo": REPO, "name": "src/auth", "path": "src/auth", "entity_type": "Module",
    })
    store.merge_node("CodeEntity", {
        "id": file_id, "repo": REPO, "name": "src/auth/jwt.py", "path": "src/auth/jwt.py", "entity_type": "File",
    })
    store.merge_node("Decision", {
        "id": "dec_mod_1",
        "repo": REPO,
        "summary": "Enforce short-lived JWT tokens across src/auth",
        "rationale": "Short TTL reduces replay window if a token leaks.",
        "state": "ACTIVE",
        "source_id": f"pr:{REPO}#77",
    })
    quote = "Short TTL reduces replay window if a token leaks."
    store.merge_node("Evidence", {
        "id": "ev_mod_1",
        "repo": REPO,
        "decision_id": "dec_mod_1",
        "source_id": f"pr:{REPO}#77",
        "source_type": "pull_request",
        "source_url": f"https://github.com/{REPO}/pull/77",
        "quote": quote,
        "claim": "Short TTL rationale",
        "quote_verified": True,
    })
    store.merge_relationship("GOVERNS", "dec_mod_1", mod_id, {})
    store.merge_relationship("SUPPORTED_BY", "dec_mod_1", "ev_mod_1", {})
    store.source_texts[f"pr:{REPO}#77"] = quote

    entity = {"id": file_id, "repo": REPO, "name": "src/auth/jwt.py", "path": "src/auth/jwt.py", "entity_type": "File"}
    bundle = retrieve_evidence(
        question="Why does jwt.py use short-lived tokens?",
        entity=entity,
        store=store,
        cfg=_cfg(),
    )
    assert bundle.evidence_tier == EvidenceTier.MODULE.value
    assert bundle.evidence_sufficiency > 0.0
    assert bundle.fallback_note is not None and "src/auth" in bundle.fallback_note
    assert len(bundle.decisions) == 1

    res = ResolutionResult(
        outcome=ResolutionOutcome.SUCCESS,
        entity=EntityCandidate(id=file_id, name="src/auth/jwt.py", path="src/auth/jwt.py", entity_type="File", score=1.0),
    )
    gate = evaluate_refusal_gate(res, bundle, min_score=0.0, cfg=_cfg())
    assert gate.outcome == GateOutcome.PASS
    assert gate.evidence_tier == EvidenceTier.MODULE.value

    provider = MockLLMProvider(canned_response=json.dumps({
        "answer": "At the src/auth module level, short TTL reduces replay window.",
        "cited_evidence_ids": ["ev_mod_1"],
    }))
    ans = generate_answer(
        question="Why does jwt.py use short-lived tokens?",
        resolution=res,
        bundle=bundle,
        provider=provider,
        store=store,
        min_score=0.0,
        cfg=_cfg(),
    )
    assert ans.confidence is not None
    assert ans.confidence.signals.directness == 0.65
    assert any("src/auth" in gap for gap in ans.evidence_gaps)


def test_tier3_touching_source_fallback_returns_caveated_lower_confidence_answer() -> None:
    store = InMemoryGraphStore()
    file_id = f"file:{REPO}:src/billing/retry.py"
    store.merge_node("CodeEntity", {
        "id": file_id, "repo": REPO, "name": "src/billing/retry.py",
        "path": "src/billing/retry.py", "entity_type": "File",
    })
    store.merge_node("PullRequest", {
        "id": f"pr:{REPO}#105",
        "repo": REPO,
        "title": "Cap billing retry attempts at 3",
        "body": "Upstream payment gateway rate-limits aggressive retries above 3 attempts.",
        "url": f"https://github.com/{REPO}/pull/105",
        "files": ["src/billing/retry.py"],
        "author": "alice",
    })

    entity = {"id": file_id, "repo": REPO, "name": "src/billing/retry.py", "path": "src/billing/retry.py", "entity_type": "File"}
    bundle = retrieve_evidence(
        question="Why does billing retry cap attempts?",
        entity=entity,
        store=store,
        cfg=_cfg(),
    )
    assert bundle.evidence_tier == EvidenceTier.SOURCE.value
    assert bundle.evidence_sufficiency > 0.0
    assert len(bundle.decisions) == 1
    assert len(bundle.evidence_items) == 1

    res = ResolutionResult(
        outcome=ResolutionOutcome.SUCCESS,
        entity=EntityCandidate(id=file_id, name="src/billing/retry.py", path="src/billing/retry.py", entity_type="File", score=1.0),
    )
    provider = MockLLMProvider(canned_response=json.dumps({
        "answer": "PR #105 notes that the payment gateway rate-limits retries above 3.",
        "cited_evidence_ids": [bundle.evidence_items[0].id],
    }))
    ans = generate_answer(
        question="Why does billing retry cap attempts?",
        resolution=res,
        bundle=bundle,
        provider=provider,
        store=store,
        min_score=0.0,
        cfg=_cfg(),
    )
    assert ans.confidence is not None
    assert ans.confidence.signals.directness == 0.40
    assert ans.outcome == Outcome.PARTIAL
    assert ans.confidence.label in (ConfidenceLabel.MEDIUM, ConfidenceLabel.LOW)


def test_no_evidence_across_all_tiers_still_refuses_cleanly() -> None:
    store = InMemoryGraphStore()
    file_id = f"file:{REPO}:src/orphan.py"
    store.merge_node("CodeEntity", {
        "id": file_id, "repo": REPO, "name": "src/orphan.py",
        "path": "src/orphan.py", "entity_type": "File",
    })
    entity = {"id": file_id, "repo": REPO, "name": "src/orphan.py", "path": "src/orphan.py", "entity_type": "File"}
    bundle = retrieve_evidence(question="Why does orphan.py exist?", entity=entity, store=store, cfg=_cfg())
    assert bundle.evidence_tier == EvidenceTier.NONE.value
    assert bundle.evidence_sufficiency == 0.0

    res = ResolutionResult(
        outcome=ResolutionOutcome.SUCCESS,
        entity=EntityCandidate(id=file_id, name="src/orphan.py", path="src/orphan.py", entity_type="File", score=1.0),
    )
    gate = evaluate_refusal_gate(res, bundle, cfg=_cfg())
    assert gate.outcome == GateOutcome.REFUSAL
    assert gate.reason_code == ReasonCode.NO_DECISION_PATH
    assert gate.gate_name == "G2"
