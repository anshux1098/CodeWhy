from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services.data_source import DataSource, DataSourceError, get_data_source

REQUIRED_METHODS = {
    "get_repository": ["repository_id"],
    "search_entities": ["repository_id", "query"],
    "ask": ["repository_id", "request"],
    "get_decision": ["decision_id"],
    "get_graph": ["repository_id", "entity_id"],
}


@pytest.mark.parametrize(("method", "parameters"), sorted(REQUIRED_METHODS.items()))
def test_protocol_declares_the_seam_methods(method: str, parameters: list[str]) -> None:
    assert hasattr(DataSource, method)
    declared = list(inspect.signature(getattr(DataSource, method)).parameters)[1:]
    assert declared == parameters


def test_fixture_is_the_default_implementation() -> None:
    from app.fixtures.source import FixtureDataSource

    assert isinstance(get_data_source(Settings(_env_file=None)), FixtureDataSource)


def test_graph_source_refuses_to_run_on_mocks_without_opt_in() -> None:
    """A graph source with no Neo4j and no real LLM can only invent answers, so
    building it must fail loudly rather than serve fabricated history."""
    with pytest.raises(DataSourceError) as excinfo:
        get_data_source(Settings(_env_file=None, data_source="graph"))
    assert "ALLOW_MOCK_PROVIDERS" in str(excinfo.value)


def test_graph_source_is_wired_up_when_mock_mode_is_opted_into() -> None:
    from app.services.data_source import GraphDataSource

    source = get_data_source(
        Settings(_env_file=None, data_source="graph", allow_mock_providers=True)
    )
    assert isinstance(source, GraphDataSource)
    # No Neo4j credentials and no LLM provider must not stop it constructing.
    repository = source.get_repository("acme/netclient")
    assert repository.fixture is True, "a mock-backed source must declare itself"


def test_an_unsupported_data_source_is_rejected_by_settings() -> None:
    """The allowed values are closed at the config layer, before a source is built."""
    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None, data_source="postgres")
    assert "postgres" in str(excinfo.value)
