from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Optional

from app.config import Settings, settings
from app.services.entity_resolution import ResolutionOutcome, ResolutionResult
from app.services.policy import (
    GatePolicyProfile,
    GateSignals,
    GateTelemetryEvent,
    PolicyRegistry,
    evaluate_policy,
)
from app.services.retrieval import EvidenceBundle


class GateOutcome(StrEnum):
    PASS = "pass"
    PARTIAL = "partial"
    REFUSAL = "refusal"


@dataclass(frozen=True)
class GateCheckResult:
    outcome: GateOutcome
    reason_code: Optional[str] = None
    gate_name: Optional[str] = None
    detail: Optional[str] = None
    grounding_method: Optional[str] = None
    score_margin: Optional[float] = None
    evidence_tier: Optional[str] = None
    evidence_sufficiency: Optional[float] = None
    entailment_score: Optional[float] = None
    calibrated_relevance: Optional[float] = None
    policy_profile: Optional[str] = None


def collect_gate_signals(
    resolution: ResolutionResult,
    bundle: Optional[EvidenceBundle] = None,
) -> GateSignals:
    """Pure signal collector decoupling observation from policy decisions."""
    entity_resolved = bool(resolution.entity is not None and bundle is not None)
    entity_name = resolution.entity.name if resolution.entity else None

    if bundle is None:
        return GateSignals(
            entity_resolved=False,
            entity_outcome=resolution.outcome.value,
            entity_reason_code=resolution.reason_code,
            entity_name=entity_name,
            entity_error_detail=resolution.error_message,
            grounding_method=resolution.grounding_method,
            score_margin=resolution.score_margin,
        )

    evidence_tier = getattr(bundle, "evidence_tier", "direct" if bundle.decisions else "none")
    evidence_sufficiency = float(
        getattr(bundle, "evidence_sufficiency", 1.0 if bundle.decisions else 0.0)
    )
    verified_quotes = [
        ev for ev in bundle.evidence_items
        if ev.quote_verified and bool(ev.quote.strip())
    ]
    entailment_score = round(
        len(verified_quotes) / max(len(bundle.evidence_items), 1), 4
    ) if verified_quotes else 0.0

    calibrated_rel = getattr(bundle, "calibrated_relevance_score", None)
    effective_relevance = (
        float(calibrated_rel)
        if calibrated_rel is not None
        else float(bundle.best_similarity_score)
    )

    return GateSignals(
        entity_resolved=entity_resolved,
        entity_outcome=resolution.outcome.value,
        entity_reason_code=resolution.reason_code,
        entity_name=entity_name,
        entity_error_detail=resolution.error_message,
        grounding_method=resolution.grounding_method,
        score_margin=resolution.score_margin,
        decision_count=len(bundle.decisions),
        evidence_tier=evidence_tier,
        evidence_sufficiency=evidence_sufficiency,
        verified_quote_count=len(verified_quotes),
        total_evidence_count=len(bundle.evidence_items),
        entailment_score=entailment_score,
        calibrated_relevance=effective_relevance,
    )


def evaluate_refusal_gate(
    resolution: ResolutionResult,
    bundle: Optional[EvidenceBundle] = None,
    min_score: Optional[float] = None,
    question: str = "",
    cfg: Optional[Settings] = None,
    *,
    repository_id: Optional[str] = None,
    profile: Optional[GatePolicyProfile] = None,
    telemetry_sink: Optional[Callable[[GateTelemetryEvent], None]] = None,
) -> GateCheckResult:
    """Evaluate the 4-gate refusal pipeline via the declarative Policy Engine.

    1. Collect pure ``GateSignals`` from entity resolution and retrieved evidence.
    2. Resolve the active ``GatePolicyProfile`` (explicit profile, per-repo override,
       or configured default profile).
    3. Evaluate declarative rules and emit structured telemetry.
    """
    config = cfg or settings
    if profile is not None:
        active_profile = profile
    else:
        registry = PolicyRegistry.from_settings(config)
        active_profile = registry.for_repository(repository_id)

    if min_score is not None:
        active_profile = active_profile.with_min_relevance(min_score)

    signals = collect_gate_signals(resolution, bundle)
    outcome_str, reason_code, gate_name, detail = evaluate_policy(
        signals,
        active_profile,
        telemetry_sink=telemetry_sink,
    )

    return GateCheckResult(
        outcome=GateOutcome(outcome_str),
        reason_code=reason_code,
        gate_name=gate_name,
        detail=detail,
        grounding_method=signals.grounding_method,
        score_margin=signals.score_margin,
        evidence_tier=signals.evidence_tier,
        evidence_sufficiency=signals.evidence_sufficiency,
        entailment_score=signals.entailment_score,
        calibrated_relevance=signals.calibrated_relevance,
        policy_profile=active_profile.name,
    )
