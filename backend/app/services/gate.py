from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Optional

from app.config import Settings, settings
from app.services.entity_resolution import ResolutionOutcome, ResolutionResult
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


def evaluate_refusal_gate(
    resolution: ResolutionResult,
    bundle: Optional[EvidenceBundle] = None,
    min_score: Optional[float] = None,
    question: str = "",
    cfg: Optional[Settings] = None,
) -> GateCheckResult:
    """Enforces the 4-check refusal gate from Layer 6 of the specification.

    G1 Entity: Question resolves to exactly one entity.
       Otherwise -> refuse (entity_not_found, out_of_scope) or ask user (ambiguous_entity).
    G2 Path: Entity has at least one decision through GOVERNS.
       Otherwise -> refuse (no_decision_path).
    G3 Quote: At least one linked evidence item has a verified quote.
       Otherwise -> partial answer "change recorded, rationale unknown" (no_verified_quote).
    G4 Relevance: Best similarity between question and decisions >= MIN_SCORE.
       Otherwise -> refuse (low_score).
    """
    config = cfg or settings
    threshold = min_score if min_score is not None else config.min_score

    # ------------------------------------------------------------------
    # G1: Entity Resolution Check
    # ------------------------------------------------------------------
    if resolution.outcome == ResolutionOutcome.REFUSAL:
        return GateCheckResult(
            outcome=GateOutcome.REFUSAL,
            reason_code=resolution.reason_code or "entity_not_found",
            gate_name="G1",
            detail=resolution.error_message or "Entity not found or out of scope.",
        )

    if resolution.outcome == ResolutionOutcome.AMBIGUOUS:
        return GateCheckResult(
            outcome=GateOutcome.REFUSAL,
            reason_code="ambiguous_entity",
            gate_name="G1",
            detail=resolution.error_message or "Ambiguous entity matched.",
        )

    if not resolution.entity or bundle is None:
        return GateCheckResult(
            outcome=GateOutcome.REFUSAL,
            reason_code="entity_not_found",
            gate_name="G1",
            detail="Entity could not be resolved.",
        )

    # ------------------------------------------------------------------
    # G2: Decision Path Check (GOVERNS)
    # ------------------------------------------------------------------
    if not bundle.decisions:
        return GateCheckResult(
            outcome=GateOutcome.REFUSAL,
            reason_code="no_decision_path",
            gate_name="G2",
            detail=f"No engineering decision path governs entity {resolution.entity.name}.",
        )

    # ------------------------------------------------------------------
    # G3: Verified Quote Check
    # ------------------------------------------------------------------
    has_verified_quote = any(
        ev.quote_verified and bool(ev.quote.strip())
        for ev in bundle.evidence_items
    )

    if not has_verified_quote:
        # Fails G3: must return partial answer with no_verified_quote
        return GateCheckResult(
            outcome=GateOutcome.PARTIAL,
            reason_code="no_verified_quote",
            gate_name="G3",
            detail="Change is recorded in history, but no verified rationale quote exists.",
        )

    # ------------------------------------------------------------------
    # G4: Relevance Check (MIN_SCORE)
    # ------------------------------------------------------------------
    if bundle.best_similarity_score < threshold:
        return GateCheckResult(
            outcome=GateOutcome.REFUSAL,
            reason_code="low_score",
            gate_name="G4",
            detail=(
                f"Best evidence similarity {bundle.best_similarity_score:.2f} "
                f"is below threshold {threshold:.2f}."
            ),
        )

    # All gates passed cleanly!
    return GateCheckResult(outcome=GateOutcome.PASS, gate_name="ALL")
