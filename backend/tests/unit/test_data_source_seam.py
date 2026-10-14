from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services.data_source import DataSource, get_data_source

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


def test_graph_source_is_wired_up_and_is_not_the_fixture() -> None:
    """Phase 3 implemented the graph source; it must be selectable and never claim to be a fixture."""
    from app.services.data_source import GraphDataSource

    source = get_data_source(Settings(_env_file=None, data_source="graph"))
    assert isinstance(source, GraphDataSource)

    # No Neo4j credentials and no LLM provider must not stop it constructing.
    repository = source.get_repository("acme/netclient")
    assert repository.fixture is False


def test_an_unsupported_data_source_is_rejected_by_settings() -> None:
    """The allowed values are closed at the config layer, before a source is built."""
    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None, data_source="postgres")
    assert "postgres" in str(excinfo.value)
