from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_source, reset_data_source_cache
from app.config import Settings
from app.main import create_app

FRONTEND_ORIGIN = "http://localhost:5173"

#: The values every integration test runs against. They are spelled out here rather
#: than inherited, because inheriting means a test's behaviour depends on whatever
#: the developer happens to have in their `.env`.
FIXTURE_SETTINGS: dict[str, object] = {
    "_env_file": None,
    "data_source": "fixture",
    "llm_provider": "",
    "llm_model": "",
    "llm_api_key": "",
    "llm_base_url": "",
    "github_token": "",
    "neo4j_uri": "",
    "neo4j_username": "",
    "neo4j_password": "",
}

#: No slash: a path parameter cannot match across a "/", so a repo id containing
#: one never reaches the route at all and would silently test the wrong thing.
REPO = "acme-netclient"


def fixture_settings(**overrides: object) -> Settings:
    """Settings for a test: no `.env`, no credentials, fixture data source."""
    values = dict(FIXTURE_SETTINGS)
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def build_test_app(**overrides: object) -> FastAPI:
    """An application wired to fixture settings, independent of any `.env`."""
    reset_data_source_cache()
    return create_app(fixture_settings(**overrides))


def seeded_graph_store() -> "object":
    """An in-memory graph holding one repository, so the graph source has something to serve.

    The in-memory store reports `is_real = False`, so every response built from it
    is flagged `fixture: true` even though the graph source is in use. That is the
    point of these tests: the production code path, without a database.
    """
    from app.stores.graph_store import InMemoryGraphStore

    store = InMemoryGraphStore()
    store.merge_node("Repository", {"id": REPO, "name": "netclient", "repo": REPO})
    store.merge_node("CodeEntity", {
        "id": "key:MAX_RETRIES", "repo": REPO, "name": "MAX_RETRIES",
        "path": "pkg/config.py", "entity_type": "ConfigKey",
    })
    store.merge_node("Decision", {
        "id": "dec_1", "repo": REPO, "summary": "Raised the retry cap",
        "rationale": "mobile clients kept timing out", "state": "ACTIVE",
        # Provenance is required: the source refuses to invent a reference, so a
        # decision without one is a 503 by design rather than a test failure.
        "source_id": f"pr:{REPO}#7", "source_type": "PullRequest",
        "source_url": f"https://github.com/{REPO}/pull/7", "source_number": 7,
    })
    store.merge_node("Evidence", {
        "id": "ev_1", "repo": REPO, "decision_id": "dec_1",
        "source_id": f"pr:{REPO}#7", "source_type": "pull_request",
        "source_url": f"https://github.com/{REPO}/pull/7",
        "quote": "mobile clients kept timing out", "claim": "cap raised",
        "author": "real-reviewer", "timestamp": "2025-01-01T00:00:00Z",
        "quote_verified": True,
    })
    store.merge_relationship("GOVERNS", "dec_1", "key:MAX_RETRIES", {})
    store.merge_relationship("SUPPORTED_BY", "dec_1", "ev_1", {})
    store.source_texts[f"pr:{REPO}#7"] = "mobile clients kept timing out"
    return store


@pytest.fixture()
def app() -> Iterator[FastAPI]:
    reset_data_source_cache()
    yield build_test_app()
    reset_data_source_cache()


@pytest.fixture()
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def graph_store():
    return seeded_graph_store()


@pytest.fixture()
def graph_client(graph_store) -> Iterator[TestClient]:
    """A client on the graph source backed by an in-memory store, never a database."""
    from app.services.data_source import GraphDataSource

    settings = fixture_settings(data_source="graph", allow_mock_providers=True)
    reset_data_source_cache()
    application = create_app(settings)
    application.dependency_overrides[get_source] = lambda: GraphDataSource(
        settings, store=graph_store
    )
    try:
        with TestClient(application) as test_client:
            yield test_client
    finally:
        reset_data_source_cache()
