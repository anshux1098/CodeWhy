from __future__ import annotations

from typing import Final
from urllib.parse import urlsplit

from app.config import Settings
from app.schemas.common import DependencyState
from app.schemas.health import DependenciesResponse, DependencyStatus

APP_VERSION: Final[str] = "0.1.0"


def _service(name: str, resolved: tuple[DependencyState, str]) -> DependencyStatus:
    status, detail = resolved
    return DependencyStatus(name=name, status=status, detail=detail)


def _credential(value: str, variable: str) -> tuple[DependencyState, str]:
    if value.strip():
        return DependencyState.CONFIGURED, f"{variable} is set"
    return DependencyState.NOT_CONFIGURED, f"{variable} not set"


def _database(uri: str) -> tuple[DependencyState, str]:
    if not uri.strip():
        return DependencyState.NOT_CONFIGURED, "NEO4J_URI not set"
    try:
        parts = urlsplit(uri)
    except ValueError:
        return DependencyState.CONFIGURED, "NEO4J_URI is not a valid URI"
    host = parts.hostname or "unknown-host"
    return DependencyState.CONFIGURED, f"NEO4J_URI points at {parts.scheme}://{host}"


def dependency_report(config: Settings) -> DependenciesResponse:
    services = [
        _service("github", _credential(config.github_token, "GITHUB_TOKEN")),
        _service("neo4j", _database(config.neo4j_uri)),
        _service("llm", _credential(config.llm_api_key, "LLM_API_KEY")),
        DependencyStatus(
            name="embeddings",
            status=DependencyState.CONFIGURED,
            detail=f"{config.embedding_provider} / {config.embedding_model} (local, no credentials)",
        ),
    ]
    return DependenciesResponse(services=services, data_source=config.data_source)
