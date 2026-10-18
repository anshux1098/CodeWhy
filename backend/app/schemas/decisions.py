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


class DecisionListItem(BaseModel):
    """One decision in a list: enough to render a row and link to the detail.

    Kept smaller than `Decision` on purpose. A list of a repository's decisions can
    run to hundreds of rows and the rationale, citations and evidence gaps are only
    needed once a row is opened.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    summary: str
    state: DecisionState
    # The decision's date (its `effective_at`). Null when the source carried none.
    date: Optional[str] = None
    source_url: Optional[str] = None
    entities: list[str] = Field(default_factory=list)
    supersedes: list[str] = Field(default_factory=list)
    superseded_by: list[str] = Field(default_factory=list)
    rule: Optional[str] = None


class DecisionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DecisionListItem] = Field(default_factory=list)
    # How many decisions match the filters before `limit`/`offset` are applied.
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    fixture: bool


class WhoToAsk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login: str
    reason: WhoToAskReason
    active: bool


class DecisionDetail(Decision):
    citations: list[Citation] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    fixture: bool
