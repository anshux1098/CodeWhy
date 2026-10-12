from __future__ import annotations

import pytest

from app.config import Settings, SettingsError

CREDENTIAL_FIELDS = [
    "github_token",
    "neo4j_uri",
    "neo4j_username",
    "neo4j_password",
    "llm_api_key",
]


def test_settings_import_without_credentials() -> None:
    config = Settings(_env_file=None)
    assert config.data_source == "fixture"
    assert config.max_graph_nodes == 80
    for field in CREDENTIAL_FIELDS:
        assert getattr(config, field) == ""


def test_settings_never_validate_credentials_at_construction() -> None:
    Settings(_env_file=None, llm_provider="", llm_model="")


@pytest.mark.parametrize(
    ("method", "missing"),
    [
        ("require_github", "GITHUB_TOKEN"),
        ("require_neo4j", "NEO4J_URI"),
        ("require_llm", "LLM_PROVIDER"),
    ],
)
def test_require_methods_name_the_missing_setting(method: str, missing: str) -> None:
    config = Settings(_env_file=None)
    with pytest.raises(SettingsError) as excinfo:
        getattr(config, method)()
    assert missing in str(excinfo.value)


def test_require_embeddings_accepts_the_local_default() -> None:
    Settings(_env_file=None).require_embeddings()


def test_require_embeddings_rejects_an_unsupported_provider() -> None:
    config = Settings(_env_file=None, embedding_provider="openai")
    with pytest.raises(SettingsError) as excinfo:
        config.require_embeddings()
    assert "EMBEDDING_PROVIDER" in str(excinfo.value)


def test_require_methods_pass_when_configured() -> None:
    config = Settings(
        _env_file=None,
        github_token="t",
        neo4j_uri="neo4j+s://x",
        neo4j_username="u",
        neo4j_password="p",
        llm_provider="local",
        llm_model="m",
        llm_api_key="k",
        embedding_provider="local",
    )
    config.require_github()
    config.require_neo4j()
    config.require_llm()
    config.require_embeddings()


def test_unknown_data_source_is_rejected() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, data_source="postgres")


def test_min_score_outside_zero_to_one_is_rejected() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, min_score=1.5)
