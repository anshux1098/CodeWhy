from __future__ import annotations

from typing import Final

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.schemas.common import GRAPH_NODE_CAP

DATA_SOURCES: Final[tuple[str, ...]] = ("fixture", "graph")
SUPPORTED_EMBEDDING_PROVIDERS: Final[frozenset[str]] = frozenset({"local"})


class SettingsError(RuntimeError):
    pass


def _require(values: dict[str, str]) -> None:
    missing = [name.upper() for name, value in values.items() if not value.strip()]
    if missing:
        raise SettingsError(
            f"{', '.join(missing)} not configured. This feature needs it; "
            "copy .env.example to .env and fill it in."
        )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    github_token: str = ""
    neo4j_uri: str = ""
    neo4j_username: str = ""
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"
    llm_provider: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    llm_timeout_s: int = 60
    max_llm_tokens_per_run: int = 500_000
    embedding_provider: str = "local"
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimensions: int = 384
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    github_timeout_s: int = 30
    max_ingestion_prs: int = 200
    max_ingestion_issues: int = 200
    max_repo_size_mb: int = 1024
    max_graph_traversal_depth: int = 3
    max_chain_length: int = 6
    max_evidence_items: int = 12
    min_score: float = 0.55

    data_source: str = "fixture"
    # Opt in to running the graph data source on mock providers and an in-memory
    # store. Off by default so a misconfigured deployment cannot serve fabricated
    # answers that claim to be real.
    allow_mock_providers: bool = False
    max_graph_nodes: int = Field(
        default=80,
        gt=0,
        le=GRAPH_NODE_CAP,
        description=(
            "Lowers the /graph node cap. Never raises it: the hard cap is GRAPH_NODE_CAP in "
            "app.schemas.common, which every GraphResponse is validated against."
        ),
    )
    app_env: str = "dev"
    log_level: str = "INFO"

    @field_validator("data_source")
    @classmethod
    def _check_data_source(cls, value: str) -> str:
        if value not in DATA_SOURCES:
            raise ValueError(f"DATA_SOURCE must be one of {DATA_SOURCES}, got {value!r}")
        return value

    @field_validator("min_score")
    @classmethod
    def _check_min_score(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"MIN_SCORE must be between 0 and 1, got {value!r}")
        return value

    @field_validator("llm_timeout_s", "github_timeout_s")
    @classmethod
    def _check_positive_timeout(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("timeouts must be positive")
        return value

    @field_validator(
        "max_ingestion_prs",
        "max_ingestion_issues",
        "max_repo_size_mb",
        "max_graph_traversal_depth",
        "max_chain_length",
        "max_evidence_items",
        "embedding_dimensions",
        "max_llm_tokens_per_run",
    )
    @classmethod
    def _check_positive_limit(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("limits must be positive")
        return value

    @property
    def fixture_mode(self) -> bool:
        return self.data_source == "fixture"

    def require_github(self) -> None:
        _require({"github_token": self.github_token})

    def require_neo4j(self) -> None:
        _require(
            {
                "neo4j_uri": self.neo4j_uri,
                "neo4j_username": self.neo4j_username,
                "neo4j_password": self.neo4j_password,
            }
        )

    def require_llm(self) -> None:
        _require(
            {
                "llm_provider": self.llm_provider,
                "llm_model": self.llm_model,
                "llm_api_key": self.llm_api_key,
            }
        )

    def require_embeddings(self) -> None:
        if self.embedding_provider not in SUPPORTED_EMBEDDING_PROVIDERS:
            raise SettingsError(
                f"EMBEDDING_PROVIDER={self.embedding_provider!r} is not supported. "
                f"Supported providers: {', '.join(sorted(SUPPORTED_EMBEDDING_PROVIDERS))}."
            )


settings = Settings()
