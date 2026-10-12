from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.schemas.common import DependencyState


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    version: str
    data_source: str


class DependencyStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: DependencyState
    detail: str


class DependenciesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    services: list[DependencyStatus]
    data_source: str
