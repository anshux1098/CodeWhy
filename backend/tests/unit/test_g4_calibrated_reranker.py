"""Unit tests for G4 Two-Stage Calibrated Reranker & Split Conformal Thresholding (Point 4)."""

from __future__ import annotations

from app.config import Settings
from app.services.entity_resolution import EntityCandidate, ResolutionOutcome, ResolutionResult
from app.services.gate import GateOutcome, evaluate_refusal_gate
from app.services.reranker import (
    CalibratedLexicalSemanticReranker,
    PlattCalibrator,
    compute_conformal_threshold,
    compute_ece,
)
from app.services.retrieval import retrieve_evidence
from app.stores.graph_store import InMemoryGraphStore


def _cfg(**overrides) -> Settings:
    defaults = dict(_env_file=None, offline=True)
    defaults.update(overrides)
    return Settings(**defaults)


def test_platt_calibrator_fits_separation_and_lowers_ece() -> None:
    raw_scores = [0.05, 0.10, 0.15, 0.20, 0.70, 0.80, 0.90, 0.95]
    labels = [0, 0, 0, 0, 1, 1, 1, 1]
    cal = PlattCalibrator.fit(raw_scores, labels)
    probs = [cal.calibrate(s) for s in raw_scores]

    assert cal.a > 0.0
    assert max(probs[:4]) < 0.35
    assert min(probs[4:]) > 0.65
    assert compute_ece(probs, labels, n_bins=4) < 0.20


def test_split_conformal_threshold_bounds_false_positive_rate() -> None:
    irrelevant_scores = [0.10, 0.12, 0.18, 0.22, 0.25, 0.28, 0.31, 0.34, 0.38, 0.42,
                         0.15, 0.19, 0.21, 0.26, 0.29, 0.33, 0.36, 0.40, 0.44, 0.48]
    # With n=20 and alpha=0.05, ceil(21 * 0.95) = 20 -> 0.48
    t_strict = compute_conformal_threshold(irrelevant_scores, alpha=0.05)
    t_relaxed = compute_conformal_threshold(irrelevant_scores, alpha=0.20)
    assert t_strict == 0.48
    assert t_relaxed < t_strict


def test_reranker_separates_relevant_vs_irrelevant_decisions() -> None:
    reranker = CalibratedLexicalSemanticReranker(cfg=_cfg())
    rel_prob = reranker.score_pair(
        "Why was HTTP/2 TLS support reverted?",
        "src/ssl_.py Revert HTTP/2 TLS support because TLS handshakes failed.",
    )
    irrel_prob = reranker.score_pair(
        "Why was HTTP/2 TLS support reverted?",
        "src/docs.py Update README formatting and copyright year.",
    )
    assert rel_prob > irrel_prob + 0.25
    assert rel_prob > 0.50
    assert irrel_prob < 0.40


def test_two_stage_retrieval_and_g4_gate_use_calibrated_relevance() -> None:
    repo = "acme/net"
    ent_id = f"file:{repo}:src/ssl.py"
    store = InMemoryGraphStore()
    store.merge_node("CodeEntity", {
        "id": ent_id, "repo": repo, "name": "src/ssl.py", "path": "src/ssl.py", "entity_type": "File",
    })
    store.merge_node("Decision", {
        "id": "dec_1",
        "repo": repo,
        "summary": "Enforce TLS 1.3 minimum protocol version",
        "rationale": "TLS 1.0 and 1.1 have known cryptographic vulnerabilities.",
        "state": "ACTIVE",
        "source_id": f"pr:{repo}#1",
    })
    store.merge_node("Evidence", {
        "id": "ev_1",
        "repo": repo,
        "decision_id": "dec_1",
        "source_id": f"pr:{repo}#1",
        "source_type": "pull_request",
        "source_url": f"https://github.com/{repo}/pull/1",
        "quote": "TLS 1.0 and 1.1 have known cryptographic vulnerabilities.",
        "claim": "TLS minimum version",
        "quote_verified": True,
    })
    store.merge_relationship("GOVERNS", "dec_1", ent_id, {})
    store.merge_relationship("SUPPORTED_BY", "dec_1", "ev_1", {})

    entity = {"id": ent_id, "repo": repo, "name": "src/ssl.py", "path": "src/ssl.py", "entity_type": "File"}
    bundle = retrieve_evidence(
        question="Why does src/ssl.py enforce TLS 1.3 minimum protocol?",
        entity=entity,
        store=store,
        cfg=_cfg(),
    )
    assert bundle.calibrated_relevance_score is not None
    assert bundle.calibrated_relevance_score > 0.55

    res = ResolutionResult(
        outcome=ResolutionOutcome.SUCCESS,
        entity=EntityCandidate(id=ent_id, name="src/ssl.py", path="src/ssl.py", entity_type="File", score=1.0),
    )
    gate = evaluate_refusal_gate(res, bundle, cfg=_cfg(min_score=0.55))
    assert gate.outcome == GateOutcome.PASS
    assert gate.calibrated_relevance == bundle.calibrated_relevance_score

    # Conformal threshold above calibrated score rejects cleanly on G4
    gate_strict = evaluate_refusal_gate(res, bundle, min_score=0.99, cfg=_cfg())
    assert gate_strict.outcome == GateOutcome.REFUSAL
    assert gate_strict.gate_name == "G4"
    assert gate_strict.reason_code == "low_score"
