from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends

from app.api.deps import get_settings
from app.config import Settings
from app.schemas.common import DependencyState
from app.schemas.health import DependenciesResponse, DependencyStatus, HealthResponse

router = APIRouter(tags=["health"])

APP_VERSION = "0.1.0"


@router.get("/health", response_model=HealthResponse, summary="Liveness and the active data source")
def health(config: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(status="ok", version=APP_VERSION, data_source=config.data_source)


def _presence(value: str, variable: str) -> str:
    return f"{variable} is set" if value.strip() else f"{variable} not set"


def _database(uri: str) -> str:
    if not uri.strip():
        return "NEO4J_URI not set"
    parts = urlsplit(uri)
    host = parts.hostname or "unknown-host"
    return f"NEO4J_URI points at {parts.scheme}://{host}"


@router.get("/health/dependencies", response_model=DependenciesResponse, summary="Configured services, without secrets")
def dependencies(config: Settings = Depends(get_settings)) -> DependenciesResponse:
    services = [
        DependencyStatus(
            name="github",
            status=DependencyState.CONFIGURED if config.github_token.strip() else DependencyState.NOT_CONFIGURED,
            detail=_presence(config.github_token, "GITHUB_TOKEN"),
        ),
        DependencyStatus(
            name="neo4j",
            status=DependencyState.CONFIGURED if config.neo4j_uri.strip() else DependencyState.NOT_CONFIGURED,
            detail=_database(config.neo4j_uri),
        ),
        DependencyStatus(
            name="llm",
            status=DependencyState.CONFIGURED if config.llm_api_key.strip() else DependencyState.NOT_CONFIGURED,
            detail=_presence(config.llm_api_key, "LLM_API_KEY"),
        ),
        DependencyStatus(
            name="embeddings",
            status=DependencyState.CONFIGURED,
            detail=f"{config.embedding_provider} / {config.embedding_model} (local, no credentials)",
        ),
    ]
    return DependenciesResponse(services=services, data_source=config.data_source)
