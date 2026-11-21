"""Unit tests for Point 6: Declarative Policy Engine, Per-Repo Profiles & Replay."""

from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings
from app.services.entity_resolution import EntityCandidate, ResolutionOutcome, ResolutionResult
from app.services.gate import GateOutcome, evaluate_refusal_gate
from app.services.policy import (
    GateTelemetryEvent,
    PolicyRegistry,
    builtin_profiles,
    replay_policy,
)
from app.services.retrieval import EvidenceBundle, EvidenceTier, RetrievedEvidenceItem


def _resolution(name: str = "src/auth/jwt.py") -> ResolutionResult:
    return ResolutionResult(
        outcome=ResolutionOutcome.SUCCESS,
        entity=EntityCandidate(id=f"file:acme/payments:{name}", name=name, path=name, entity_type="File", score=1.0),
        grounding_method="structural",
        score_margin=1.0,
    )


def _module_bundle(rel: float = 0.62) -> EvidenceBundle:
    return EvidenceBundle(
        question="Why use short JWT TTL?",
        resolved_entity={"id": "file:acme/payments:src/auth/jwt.py", "name": "src/auth/jwt.py"},
        decisions=[{"id": "dec_1", "summary": "Short JWT TTL", "state": "ACTIVE"}],
        evidence_items=[
            RetrievedEvidenceItem(
                id="ev_1",
                decision_id="dec_1",
                source_id="pr:acme/payments#77",
                source_type="pull_request",
                source_url="https://github.com/acme/payments/pull/77",
                quote="Short TTL reduces replay window.",
                claim="Short TTL",
                quote_verified=True,
                similarity_score=rel,
            )
        ],
        best_similarity_score=rel,
        calibrated_relevance_score=rel,
        evidence_tier=EvidenceTier.MODULE.value,
        evidence_sufficiency=0.58,
    )


def test_strict_vs_balanced_vs_exploratory_profiles_behave_declaratively() -> None:
    res = _resolution()
    bundle = _module_bundle(rel=0.62)
    profiles = builtin_profiles(default_min_score=0.55)

    # Balanced allows Tier 2 module fallback and passes at 0.62 >= 0.55
    g_bal = evaluate_refusal_gate(res, bundle, profile=profiles["balanced"])
    assert g_bal.outcome == GateOutcome.PASS
    assert g_bal.policy_profile == "balanced"

    # Strict rejects Tier 2 module fallback cleanly on G2
    g_strict = evaluate_refusal_gate(res, bundle, profile=profiles["strict"])
    assert g_strict.outcome == GateOutcome.REFUSAL
    assert g_strict.gate_name == "G2"
    assert g_strict.reason_code == "no_decision_path"
    assert g_strict.policy_profile == "strict"


def test_per_repo_policy_overrides_load_from_json_file(tmp_path: Path) -> None:
    policy_file = tmp_path / "gate_policies.json"
    policy_file.write_text(
        json.dumps({
            "default_profile": "balanced",
            "repo_overrides": {
                "acme/payments": "strict",
                "acme/docs": "exploratory",
            },
        }),
        encoding="utf-8",
    )
    cfg = Settings(_env_file=None, offline=True, gate_policy_path=str(policy_file))
    registry = PolicyRegistry.from_settings(cfg)

    assert registry.for_repository("acme/payments").name == "strict"
    assert registry.for_repository("acme/docs").name == "exploratory"
    assert registry.for_repository("acme/other").name == "balanced"

    res = _resolution()
    bundle = _module_bundle(rel=0.62)
    g_pay = evaluate_refusal_gate(res, bundle, cfg=cfg, repository_id="acme/payments")
    g_docs = evaluate_refusal_gate(res, bundle, cfg=cfg, repository_id="acme/docs")
    assert g_pay.outcome == GateOutcome.REFUSAL
    assert g_docs.outcome == GateOutcome.PASS


def test_gate_telemetry_and_offline_policy_replay() -> None:
    events: list[GateTelemetryEvent] = []
    res = _resolution()
    profiles = builtin_profiles(default_min_score=0.55)

    # Collect telemetry under balanced profile
    evaluate_refusal_gate(res, _module_bundle(rel=0.62), profile=profiles["balanced"], telemetry_sink=events.append)
    evaluate_refusal_gate(res, _module_bundle(rel=0.35), profile=profiles["balanced"], telemetry_sink=events.append)
    assert len(events) == 2
    assert [e.outcome for e in events] == ["pass", "refusal"]

    # Replay those same events under exploratory profile (min_relevance=0.25) -> both pass!
    summary = replay_policy(events, profiles["exploratory"])
    assert summary.total_events == 2
    assert summary.outcome_counts["pass"] == 2
    assert summary.changed_decisions == 1
