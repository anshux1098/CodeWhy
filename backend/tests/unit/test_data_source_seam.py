from __future__ import annotations

import inspect

import pytest

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
    assert list(inspect.signature(getattr(DataSource, method)).parameters) == parameters


def test_fixture_is_the_default_implementation() -> None:
    from app.fixtures.source import FixtureDataSource

    assert isinstance(get_data_source(Settings(_env_file=None)), FixtureDataSource)


def test_graph_source_is_not_implemented_yet() -> None:
    with pytest.raises(DataSourceError) as excinfo:
        get_data_source(Settings(_env_file=None, data_source="graph"))
    assert "graph" in str(excinfo.value)
