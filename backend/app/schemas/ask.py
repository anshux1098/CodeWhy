from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import Outcome, ReasonCode
from app.schemas.confidence import ConfidenceScore
from app.schemas.decisions import Citation, Decision, WhoToAsk
from app.schemas.entities import Candidate, Entity
from app.services.response_rules import (
    check_answer_required,
    check_citations,
    check_confidence,
    check_entity_and_candidates,
    check_reason_code_outcome,
    check_refusal_text,
)


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3)
    entity_id: str | None = None


class AskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Outcome
    reason_code: ReasonCode | None = None
    answer: str | None = None
    entity: Entity | None = None
    candidates: list[Candidate] = Field(default_factory=list)
    confidence: ConfidenceScore | None = None
    decisions: list[Decision] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    who_to_ask: list[WhoToAsk] = Field(default_factory=list)
    code_differs_from_latest: bool | None = None
    fixture: bool

    @model_validator(mode="after")
    def _enforce_response_rules(self) -> "AskResponse":
        check_reason_code_outcome(self)
        check_entity_and_candidates(self)
        check_citations(self)
        check_confidence(self)
        check_answer_required(self)
        check_refusal_text(self)
        return self
