from __future__ import annotations

from typing import TYPE_CHECKING, Final

from app.schemas.common import CitationKind, ConfidenceLabel, Outcome, ReasonCode

if TYPE_CHECKING:
    from app.schemas.ask import AskResponse

from app.services.confidence import CONTRADICTION_SCORE_CAP

REFUSAL_ONLY_CODES: Final[frozenset[ReasonCode]] = frozenset(
    {
        ReasonCode.ENTITY_NOT_FOUND,
        ReasonCode.AMBIGUOUS_ENTITY,
        ReasonCode.OUT_OF_SCOPE,
        ReasonCode.NO_DECISION_PATH,
        ReasonCode.LOW_SCORE,
    }
)
PRESCORING_REFUSALS: Final[frozenset[ReasonCode]] = frozenset(
    {ReasonCode.ENTITY_NOT_FOUND, ReasonCode.AMBIGUOUS_ENTITY, ReasonCode.OUT_OF_SCOPE}
)
NULL_ENTITY_CODES: Final[frozenset[ReasonCode]] = PRESCORING_REFUSALS


def check_reason_code_outcome(response: "AskResponse") -> None:
    code = response.reason_code
    if code is None:
        return
    if code in REFUSAL_ONLY_CODES and response.outcome is not Outcome.REFUSAL:
        raise ValueError(
            f"R1_REASON_CODE_OUTCOME: reason_code {code.value!r} is only valid with "
            f"outcome 'refusal', got {response.outcome.value!r}"
        )
    if code is ReasonCode.NO_VERIFIED_QUOTE and response.outcome is not Outcome.PARTIAL:
        raise ValueError(
            "R1_REASON_CODE_OUTCOME: reason_code 'no_verified_quote' is only valid with "
            f"outcome 'partial', got {response.outcome.value!r}"
        )


def check_entity_and_candidates(response: "AskResponse") -> None:
    code = response.reason_code
    if code in NULL_ENTITY_CODES and response.entity is not None:
        raise ValueError(
            f"R2_ENTITY_NULLITY: entity must be null when reason_code is {code.value!r}, "
            f"got {response.entity.id!r}"
        )
    if code is ReasonCode.AMBIGUOUS_ENTITY:
        if not response.candidates:
            raise ValueError(
                "R2_CANDIDATES_EMPTY: reason_code 'ambiguous_entity' requires a "
                "non-empty candidates list"
            )
        if response.answer is not None:
            raise ValueError(
                "R2_AMBIGUOUS_ANSWER: answer must be null when reason_code is 'ambiguous_entity'"
            )


def check_citations(response: "AskResponse") -> None:
    if response.outcome is Outcome.FULL:
        if not response.citations:
            raise ValueError("R3_FULL_NO_CITATIONS: outcome 'full' requires at least one citation")
        if not any(citation.kind is CitationKind.SOURCE for citation in response.citations):
            raise ValueError(
                "R3_FULL_NO_SOURCE_CITATION: outcome 'full' requires at least one "
                "citation of kind 'SOURCE'"
            )
    known = {decision.id for decision in response.decisions}
    for citation in response.citations:
        if not citation.decision_id:
            raise ValueError(f"R3_CITATION_NO_DECISION: citation {citation.id!r} must name a decision")
        if citation.decision_id not in known:
            raise ValueError(
                f"R3_CITATION_UNKNOWN_DECISION: citation {citation.id!r} names decision "
                f"{citation.decision_id!r}, which is not in decisions"
            )
    if response.reason_code is ReasonCode.NO_VERIFIED_QUOTE and response.citations:
        raise ValueError("R3_NO_VERIFIED_QUOTE_CITATIONS: reason_code 'no_verified_quote' forbids citations")


def check_confidence(response: "AskResponse") -> None:
    code = response.reason_code
    if code in PRESCORING_REFUSALS:
        if response.confidence is not None:
            raise ValueError(
                f"R4_PRESCORING_CONFIDENCE: confidence must be null when reason_code is "
                f"{code.value!r}; these refusals happen before scoring"
            )
        return
    if response.outcome in {Outcome.FULL, Outcome.PARTIAL} or code in REFUSAL_ONLY_CODES:
        if response.confidence is None:
            raise ValueError(
                f"R4_CONFIDENCE_REQUIRED: outcome {response.outcome.value!r} with "
                f"reason_code {code.value if code else None!r} requires a confidence object"
            )
    confidence = response.confidence
    if confidence is None:
        return
    if response.outcome is Outcome.FULL and confidence.label is not ConfidenceLabel.HIGH:
        raise ValueError(
            f"R4_FULL_REQUIRES_HIGH: outcome 'full' requires label HIGH, "
            f"got {confidence.label.value!r}"
        )
    if response.outcome is Outcome.PARTIAL:
        allowed = {ConfidenceLabel.MEDIUM}
        if code is ReasonCode.NO_VERIFIED_QUOTE:
            allowed = {ConfidenceLabel.MEDIUM, ConfidenceLabel.LOW}
        if confidence.label not in allowed:
            expected = " or ".join(sorted(label.value for label in allowed))
            raise ValueError(
                f"R4_PARTIAL_LABEL: outcome 'partial' requires label {expected}, "
                f"got {confidence.label.value!r}"
            )
    if confidence.signals.contradiction == 1.0 and confidence.score > CONTRADICTION_SCORE_CAP:
        raise ValueError(
            f"R4_CONTRADICTION_CAP: signals.contradiction is 1, so the score must be "
            f"{CONTRADICTION_SCORE_CAP} or lower, got {confidence.score}"
        )


def check_refusal_text(response: "AskResponse") -> None:
    if response.outcome is not Outcome.REFUSAL:
        return
    if response.reason_code is not ReasonCode.AMBIGUOUS_ENTITY and not (response.answer or "").strip():
        raise ValueError(
            "R5_REFUSAL_ANSWER: outcome 'refusal' requires a refusal message in answer, "
            "except for reason_code 'ambiguous_entity'"
        )
    if not response.evidence_gaps:
        raise ValueError("R5_EVIDENCE_GAPS: every refusal must list at least one evidence gap")
