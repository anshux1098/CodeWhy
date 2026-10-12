from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.ask import AskRequest, AskResponse
from app.schemas.common import ConfidenceLabel
from app.schemas.decisions import Citation, Decision, SourceRef
from app.schemas.entities import Candidate, Entity
from app.services.confidence import derive_label

PR_41 = SourceRef(type="PullRequest", number=41, url="https://github.invalid/acme/netclient/pull/41")
PR_77 = SourceRef(type="PullRequest", number=77, url="https://github.invalid/acme/netclient/pull/77")

HIGH_SIGNALS = {
    "directness": 1.0,
    "provenance": 0.8,
    "agreement": 0.4,
    "relevance": 0.9,
    "temporal_consistency": 1.0,
    "contradiction": 0.0,
}
MEDIUM_SIGNALS = {**HIGH_SIGNALS, "directness": 0.5, "relevance": 0.85, "temporal_consistency": 0.5}
LOW_SIGNALS = {
    **HIGH_SIGNALS,
    "directness": 0.0,
    "provenance": 0.0,
    "agreement": 0.0,
    "relevance": 0.3,
    "temporal_consistency": 0.3,
}

ENTITY = Entity(
    id="key:MAX_RETRIES",
    type="ConfigKey",
    label="MAX_RETRIES",
    path="netclient/config.py",
    decision_count=3,
)
CANDIDATE_RETRY = Candidate(id="file:netclient/retry.py", type="File", label="retry.py")
CANDIDATE_BACKOFF = Candidate(id="key:RETRY_BACKOFF_MS", type="ConfigKey", label="RETRY_BACKOFF_MS")
TWO_CANDIDATES = [CANDIDATE_RETRY, CANDIDATE_BACKOFF]
RETRY_FILE = Entity(
    id="file:netclient/retry.py",
    type="File",
    label="retry.py",
    path="netclient/retry.py",
    decision_count=1,
)
DECISION_41 = Decision(
    id="dec_41",
    summary="Cap MAX_RETRIES at 3",
    rationale="Mobile clients give up after three retries.",
    state="ACTIVE",
    recorded_at="2024-02-11T09:14:00Z",
    source=PR_41,
    superseded_by=["dec_77"],
)
SOURCE_CITATION = Citation(
    id="cit_41",
    decision_id="dec_41",
    kind="SOURCE",
    quote="Cap the library at three retries.",
    source_url=PR_41.url,
    source_type="PullRequest",
    author="priya",
    timestamp="2024-02-11T09:14:00Z",
)
INFERRED_CITATION = {**SOURCE_CITATION.model_dump(), "id": "cit_inferred", "kind": "INFERRED"}


def build(**overrides: object) -> AskResponse:
    payload: dict[str, object] = {
        "outcome": "full",
        "reason_code": None,
        "answer": "MAX_RETRIES is 3 because mobile clients give up after three retries.",
        "entity": ENTITY,
        "candidates": [],
        "confidence": {"score": 0.83, "signals": HIGH_SIGNALS},
        "decisions": [DECISION_41],
        "citations": [SOURCE_CITATION],
        "evidence_gaps": [],
        "who_to_ask": [],
        "code_differs_from_latest": False,
        "fixture": True,
    }
    payload.update(overrides)
    return AskResponse(**payload)


# R1 reason_code and outcome


@pytest.mark.parametrize(
    "code",
    ["entity_not_found", "ambiguous_entity", "out_of_scope", "no_decision_path", "low_score", "no_verified_quote"],
)
def test_r1_refusal_only_code_rejected_on_full(code: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        build(reason_code=code)
    assert "R1_REASON_CODE_OUTCOME" in str(excinfo.value)


def test_r1_no_verified_quote_rejected_on_refusal() -> None:
    with pytest.raises(ValidationError) as excinfo:
        build(outcome="refusal", reason_code="no_verified_quote", answer="no", confidence=None)
    assert "R1_REASON_CODE_OUTCOME" in str(excinfo.value)


def test_r1_no_verified_quote_accepted_on_partial() -> None:
    partial = build(
        outcome="partial",
        reason_code="no_verified_quote",
        answer="Change recorded, rationale unknown.",
        confidence={"score": 0.35, "signals": LOW_SIGNALS},
        decisions=[],
        citations=[],
        entity=RETRY_FILE,
    )
    assert partial.outcome == "partial"


def test_r1_null_reason_code_accepted_on_full() -> None:
    assert build(reason_code=None).reason_code is None


# R2 entity nullity and ambiguity


@pytest.mark.parametrize("code", ["entity_not_found", "ambiguous_entity", "out_of_scope"])
def test_r2_entity_must_be_null(code: str) -> None:
    candidates = TWO_CANDIDATES if code == "ambiguous_entity" else []
    answer = None if code == "ambiguous_entity" else "Refused."
    with pytest.raises(ValidationError) as excinfo:
        build(
            outcome="refusal",
            reason_code=code,
            entity=ENTITY,
            candidates=candidates,
            answer=answer,
            confidence=None,
        )
    assert "R2_ENTITY_NULLITY" in str(excinfo.value)


def test_r2_ambiguous_requires_candidates() -> None:
    with pytest.raises(ValidationError) as excinfo:
        build(
            outcome="refusal",
            reason_code="ambiguous_entity",
            entity=None,
            candidates=[],
            answer=None,
            confidence=None,
            evidence_gaps=["Say which one you mean."],
        )
    assert "R2_CANDIDATES_EMPTY" in str(excinfo.value)


def test_r2_ambiguous_requires_at_least_two_candidates() -> None:
    with pytest.raises(ValidationError) as excinfo:
        build(
            outcome="refusal",
            reason_code="ambiguous_entity",
            entity=None,
            candidates=[CANDIDATE_RETRY],
            answer=None,
            confidence=None,
            decisions=[],
            citations=[],
            evidence_gaps=["Say which one you mean."],
        )
    assert "R2_CANDIDATES_NOT_AMBIGUOUS" in str(excinfo.value)


def test_r2_ambiguous_rejects_duplicate_candidate_ids() -> None:
    with pytest.raises(ValidationError) as excinfo:
        build(
            outcome="refusal",
            reason_code="ambiguous_entity",
            entity=None,
            candidates=[CANDIDATE_RETRY, CANDIDATE_RETRY],
            answer=None,
            confidence=None,
            decisions=[],
            citations=[],
            evidence_gaps=["Say which one you mean."],
        )
    assert "R2_CANDIDATES_DUPLICATE" in str(excinfo.value)


def test_r2_ambiguous_requires_null_answer() -> None:
    with pytest.raises(ValidationError) as excinfo:
        build(
            outcome="refusal",
            reason_code="ambiguous_entity",
            entity=None,
            candidates=TWO_CANDIDATES,
            answer="I am not sure which one you mean.",
            confidence=None,
            evidence_gaps=["Say which one you mean."],
        )
    assert "R2_AMBIGUOUS_ANSWER" in str(excinfo.value)


def test_r2_ambiguous_shape_accepted() -> None:
    ambiguous = build(
        outcome="refusal",
        reason_code="ambiguous_entity",
        entity=None,
        candidates=TWO_CANDIDATES,
        answer=None,
        confidence=None,
        decisions=[],
        citations=[],
        evidence_gaps=["Say which one you mean: the file or the config key."],
    )
    assert len(ambiguous.candidates) == 2


# R3 citation integrity


def test_r3_full_requires_a_citation() -> None:
    with pytest.raises(ValidationError) as excinfo:
        build(citations=[])
    assert "R3_FULL_NO_CITATIONS" in str(excinfo.value)


def test_r3_full_requires_at_least_one_source_citation() -> None:
    with pytest.raises(ValidationError) as excinfo:
        build(citations=[INFERRED_CITATION])
    assert "R3_FULL_NO_SOURCE_CITATION" in str(excinfo.value)


def test_r3_citation_must_name_a_decision() -> None:
    with pytest.raises(ValidationError) as excinfo:
        build(citations=[{**SOURCE_CITATION.model_dump(), "decision_id": ""}])
    assert "R3_CITATION_NO_DECISION" in str(excinfo.value)


def test_r3_citation_must_resolve_to_a_decision_in_the_answer() -> None:
    with pytest.raises(ValidationError) as excinfo:
        build(citations=[{**SOURCE_CITATION.model_dump(), "decision_id": "dec_99"}])
    assert "R3_CITATION_UNKNOWN_DECISION" in str(excinfo.value)


def test_r3_no_verified_quote_forbids_citations() -> None:
    with pytest.raises(ValidationError) as excinfo:
        build(
            outcome="partial",
            reason_code="no_verified_quote",
            answer="Change recorded, rationale unknown.",
            confidence={"score": 0.35, "signals": LOW_SIGNALS},
            citations=[SOURCE_CITATION],
        )
    assert "R3_NO_VERIFIED_QUOTE_CITATIONS" in str(excinfo.value)


# R4 confidence


def test_r4_full_requires_high() -> None:
    with pytest.raises(ValidationError) as excinfo:
        build(confidence={"score": 0.6, "signals": MEDIUM_SIGNALS})
    assert "R4_FULL_REQUIRES_HIGH" in str(excinfo.value)


def test_r4_partial_requires_medium() -> None:
    with pytest.raises(ValidationError) as excinfo:
        build(outcome="partial", confidence={"score": 0.35, "signals": LOW_SIGNALS}, answer="Because.")
    assert "R4_PARTIAL_LABEL" in str(excinfo.value)


def test_r4_partial_with_no_verified_quote_may_be_low() -> None:
    partial = build(
        outcome="partial",
        reason_code="no_verified_quote",
        answer="Change recorded, rationale unknown.",
        confidence={"score": 0.35, "signals": LOW_SIGNALS},
        citations=[],
    )
    assert partial.confidence.label == "LOW"


def test_r4_partial_with_no_verified_quote_may_not_be_high() -> None:
    with pytest.raises(ValidationError) as excinfo:
        build(
            outcome="partial",
            reason_code="no_verified_quote",
            answer="Change recorded, rationale unknown.",
            confidence={"score": 0.9, "signals": HIGH_SIGNALS},
            citations=[],
        )
    assert "R4_PARTIAL_LABEL" in str(excinfo.value)


@pytest.mark.parametrize("code", ["entity_not_found", "ambiguous_entity", "out_of_scope"])
def test_r4_prescoring_refusals_must_have_null_confidence(code: str) -> None:
    candidates = TWO_CANDIDATES if code == "ambiguous_entity" else []
    answer = None if code == "ambiguous_entity" else "Refused."
    with pytest.raises(ValidationError) as excinfo:
        build(outcome="refusal", reason_code=code, entity=None, candidates=candidates, answer=answer)
    assert "R4_PRESCORING_CONFIDENCE" in str(excinfo.value)


@pytest.mark.parametrize("code", ["no_decision_path", "low_score"])
def test_r4_scored_refusal_may_not_carry_a_high_label(code: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        build(
            outcome="refusal",
            reason_code=code,
            answer="I cannot answer that.",
            confidence={"score": 0.9, "signals": HIGH_SIGNALS},
            decisions=[],
            citations=[],
        )
    assert "R4_REFUSAL_LABEL" in str(excinfo.value)


@pytest.mark.parametrize("code", ["no_decision_path", "low_score"])
def test_r4_scored_refusal_may_carry_a_medium_label(code: str) -> None:
    refusal = build(
        outcome="refusal",
        reason_code=code,
        answer="I cannot answer that.",
        confidence={"score": 0.6, "signals": MEDIUM_SIGNALS},
        decisions=[],
        citations=[],
        evidence_gaps=["Nothing found."],
    )
    assert refusal.confidence.label == "MEDIUM"


@pytest.mark.parametrize(
    ("outcome", "confidence"),
    [
        ("full", {"score": 0.83, "signals": HIGH_SIGNALS}),
        ("partial", {"score": 0.6, "signals": MEDIUM_SIGNALS}),
    ],
)
def test_r4_full_and_partial_require_a_non_empty_answer(outcome: str, confidence: dict) -> None:
    with pytest.raises(ValidationError) as excinfo:
        build(outcome=outcome, answer="   ", confidence=confidence)
    assert "R4_ANSWER_REQUIRED" in str(excinfo.value)


def test_r4_full_requires_a_non_null_answer() -> None:
    with pytest.raises(ValidationError) as excinfo:
        build(answer=None)
    assert "R4_ANSWER_REQUIRED" in str(excinfo.value)


def test_r4_full_and_partial_may_carry_a_short_answer() -> None:
    partial = build(
        outcome="partial",
        answer="Because.",
        confidence={"score": 0.6, "signals": MEDIUM_SIGNALS},
    )
    assert partial.answer == "Because."


@pytest.mark.parametrize("code", ["no_decision_path", "low_score"])
def test_r4_scored_refusals_must_carry_a_score(code: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        build(outcome="refusal", reason_code=code, answer="I cannot answer that.", confidence=None)
    assert "R4_CONFIDENCE_REQUIRED" in str(excinfo.value)


def test_r4_no_decision_path_with_a_low_score_is_accepted() -> None:
    refusal = build(
        outcome="refusal",
        reason_code="no_decision_path",
        answer="No recorded decision governs _PAD_BYTES.",
        confidence={"score": 0.09, "signals": LOW_SIGNALS},
        decisions=[],
        citations=[],
        entity=Entity(
            id="key:_PAD_BYTES",
            type="ConfigKey",
            label="_PAD_BYTES",
            path="netclient/config.py",
            decision_count=0,
        ),
        evidence_gaps=["No pull request, issue or design doc mentions _PAD_BYTES."],
    )
    assert refusal.confidence.label == "LOW"


def test_r4_contradiction_caps_the_score_at_zero_seventy() -> None:
    with pytest.raises(ValidationError) as excinfo:
        build(
            outcome="partial",
            answer="Change recorded, but the sources disagree.",
            confidence={"score": 0.71, "signals": {**MEDIUM_SIGNALS, "contradiction": 1.0}},
        )
    assert "R4_CONTRADICTION_CAP" in str(excinfo.value)


def test_r4_contradiction_cap_boundary_is_allowed() -> None:
    capped = build(
        outcome="partial",
        answer="Change recorded, but the sources disagree.",
        confidence={"score": 0.70, "signals": {**MEDIUM_SIGNALS, "contradiction": 1.0}},
        code_differs_from_latest=True,
    )
    assert capped.confidence.score == 0.70


def test_r4_contradiction_makes_full_unreachable() -> None:
    best_contradictory_score = 0.30 + 0.20 + 0.20 + 0.15 + 0.15 - 0.30
    assert best_contradictory_score == pytest.approx(0.70)
    assert derive_label(best_contradictory_score) is not ConfidenceLabel.HIGH


# R5 refusal text


@pytest.mark.parametrize("code", ["entity_not_found", "out_of_scope", "no_decision_path"])
def test_r5_refusal_requires_answer_text(code: str) -> None:
    entity = None if code in {"entity_not_found", "out_of_scope"} else ENTITY
    confidence = (
        None
        if code in {"entity_not_found", "out_of_scope"}
        else {"score": 0.09, "signals": LOW_SIGNALS}
    )
    with pytest.raises(ValidationError) as excinfo:
        build(
            outcome="refusal",
            reason_code=code,
            answer=None,
            entity=entity,
            confidence=confidence,
            evidence_gaps=["Nothing found."],
        )
    assert "R5_REFUSAL_ANSWER" in str(excinfo.value)


@pytest.mark.parametrize("code", ["entity_not_found", "out_of_scope", "no_decision_path", "low_score"])
def test_r5_refusal_requires_evidence_gaps(code: str) -> None:
    entity = None if code in {"entity_not_found", "out_of_scope"} else ENTITY
    confidence = (
        None
        if code in {"entity_not_found", "out_of_scope"}
        else {"score": 0.09, "signals": LOW_SIGNALS}
    )
    with pytest.raises(ValidationError) as excinfo:
        build(
            outcome="refusal",
            reason_code=code,
            answer="I cannot answer that.",
            entity=entity,
            confidence=confidence,
            evidence_gaps=[],
        )
    assert "R5_EVIDENCE_GAPS" in str(excinfo.value)


def test_r5_scored_refusal_shape_accepted() -> None:
    refusal = build(
        outcome="refusal",
        reason_code="low_score",
        answer="The closest recorded change is too loosely related to assert a reason.",
        confidence={"score": 0.4, "signals": LOW_SIGNALS},
        decisions=[],
        citations=[],
        evidence_gaps=["No source links the question to a decision."],
    )
    assert refusal.outcome == "refusal"


# request


def test_ask_request_rejects_an_empty_question() -> None:
    with pytest.raises(ValidationError):
        AskRequest(question="")


def test_ask_request_entity_id_defaults_to_none() -> None:
    assert AskRequest(question="Why is MAX_RETRIES 3?").entity_id is None
