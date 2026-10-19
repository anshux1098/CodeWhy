from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class RepositoryCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: int = Field(ge=0)
    entities: int = Field(ge=0)
    pull_requests: int = Field(ge=0)
    commits: int = Field(ge=0)


class RepositoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    url: str
    counts: RepositoryCounts
    # Ingestion and coverage status the build records on the Repository node. Null
    # when the node predates it or the value was never measured, rather than a zero
    # that would read as "nothing was ingested".
    full_name: Optional[str] = None
    owner: Optional[str] = None
    scope: Optional[str] = None
    prs_fetched: Optional[int] = Field(default=None, ge=0)
    sources_analyzed: Optional[int] = Field(default=None, ge=0)
    prs_noise_skipped: Optional[int] = Field(default=None, ge=0)
    verified_decisions: Optional[int] = Field(default=None, ge=0)
    last_rebuilt_at: Optional[str] = None
    fixture: bool


class RepositoryListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RepositoryResponse] = Field(default_factory=list)
    fixture: bool
