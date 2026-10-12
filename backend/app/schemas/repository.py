from __future__ import annotations

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
    fixture: bool
