from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_settings
from app.config import Settings
from app.schemas.health import DependenciesResponse, HealthResponse
from app.services.health import APP_VERSION, dependency_report

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness and the active data source")
def health(config: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(status="ok", version=APP_VERSION, data_source=config.data_source)


@router.get("/health/dependencies", response_model=DependenciesResponse, summary="Configured services, without secrets")
def dependencies(config: Settings = Depends(get_settings)) -> DependenciesResponse:
    return dependency_report(config)
