from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import EntityType


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: EntityType
    label: str


class Entity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: EntityType
    label: str
    path: str
    decision_count: int = Field(ge=0)


class EntityListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entities: list[Entity] = Field(default_factory=list)
    query: str
    fixture: bool
