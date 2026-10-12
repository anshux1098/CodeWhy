from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import CitationKind, DecisionState, SourceType, WhoToAskReason


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: SourceType
    number: int = Field(ge=0)
    url: str


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    decision_id: str
    kind: CitationKind
    quote: str
    source_url: str
    source_type: SourceType
    author: str
    timestamp: str


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
