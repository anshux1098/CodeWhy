from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import CitationKind, DecisionState, SourceType, WhoToAskReason


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: SourceType
    # Null when the ingested record does not carry the value. A placeholder would
    # attribute the decision to something that never happened.
    number: Optional[int] = Field(default=None, ge=0)
    url: Optional[str] = None


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    decision_id: str
    kind: CitationKind
    quote: str
    source_url: str
    source_type: SourceType
    # Null when the ingested record genuinely does not carry the value. Inventing
    # a placeholder here would misattribute the quote, so the field is honest instead.
    author: Optional[str] = None
    timestamp: Optional[str] = None


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    summary: str
    rationale: str | None = None
    state: DecisionState
    recorded_at: str | None = None
    effective_at: str | None = None
    ended_at: str | None = None
    source: SourceRef
    supersedes: list[str] = Field(default_factory=list)
    superseded_by: list[str] = Field(default_factory=list)
    rule: str | None = None
    probable_superseded_by: list[str] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)
    reaffirms: list[str] = Field(default_factory=list)


class WhoToAsk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login: str
    reason: WhoToAskReason
    active: bool


class DecisionDetail(Decision):
    citations: list[Citation] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    fixture: bool
