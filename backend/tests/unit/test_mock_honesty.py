"""Mock and in-memory honesty.

A response must never present mock output as real history. The `fixture` flag is
the only signal a consumer has, so it has to be derived from the store and the
provider, not hardcoded.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.providers.llm_provider import MockLLMProvider
from app.schemas.ask import AskRequest
from app.services.data_source import DataSourceError, GraphDataSource, get_data_source
from app.stores.graph_store import InMemoryGraphStore

REPO = "acme/netclient"


def seeded_store() -> InMemoryGraphStore:
    store = InMemoryGraphStore()
    store.merge_node("Repository", {"id": REPO, "name": "netclient", "repo": REPO})
    store.merge_node("CodeEntity", {
        "id": "e1", "repo": REPO, "name": "MAX_RETRIES",
        "path": "pkg/config.py", "entity_type": "ConfigKey",
    })
    store.merge_node("Decision", {
        "id": "d1", "repo": REPO, "summary": "Raised the cap",
        "rationale": "mobile clients time out", "state": "ACTIVE",
        "source_id": f"pr:{REPO}#7",
    })
    store.merge_node("Evidence", {
        "id": "ev1", "source_id": f"pr:{REPO}#7", "source_type": "pull_request",
        "source_url": f"https://github.com/{REPO}/pull/7",
        "quote": "mobile clients time out", "claim": "cap raised",
        "author": "real-reviewer", "timestamp": "2025-01-01T00:00:00Z",
        "quote_verified": True,
    })
    store.merge_relationship("GOVERNS", "d1", "e1", {})
    store.merge_relationship("SUPPORTED_BY", "d1", "ev1", {})
    store.source_texts[f"pr:{REPO}#7"] = "mobile clients time out on flaky networks"
    return store


# --- get_decision must not fabricate ---------------------------------------


def test_get_decision_for_an_unknown_id_does_not_invent_content() -> None:
    source = GraphDataSource(Settings(_env_file=None), store=seeded_store())
    with pytest.raises(DataSourceError) as excinfo:
        source.get_decision("dec_does_not_exist_xyz")
    assert "dec_does_not_exist_xyz" in str(excinfo.value)


def test_get_decision_never_contains_a_synthesised_placeholder() -> None:
    """The old fallback returned summary='Decision summary' and a pull/1 URL."""
    source = GraphDataSource(Settings(_env_file=None), store=seeded_store())
    with pytest.raises(DataSourceError):
        source.get_decision("dec_does_not_exist_xyz")
    # Nothing in the module may still build that placeholder.
    import inspect

    from app.services import data_source as ds

    assert "Decision summary" not in inspect.getsource(ds)
    assert "https://github.com/repo/pull/1" not in inspect.getsource(ds)


def test_get_decision_returns_real_content_when_present() -> None:
    source = GraphDataSource(Settings(_env_file=None), store=seeded_store())
    detail = source.get_decision("d1")
    assert detail.summary == "Raised the cap"
    assert detail.rationale == "mobile clients time out"


# --- the fixture flag must be derived, not hardcoded ------------------------


def test_mock_store_and_mock_provider_produce_fixture_true() -> None:
    source = GraphDataSource(Settings(_env_file=None), store=seeded_store())
    assert isinstance(source.provider, MockLLMProvider)
    response = source.ask(REPO, AskRequest(question="Why is MAX_RETRIES 3?"))
    assert response.fixture is True, "a mock provider must never report fixture=False"


def test_repository_and_entity_responses_are_fixture_true_under_mocks() -> None:
    source = GraphDataSource(Settings(_env_file=None), store=seeded_store())
    assert source.get_repository(REPO).fixture is True
    assert source.search_entities(REPO, "MAX_RETRIES").fixture is True
    assert source.get_graph(REPO, "e1").fixture is True


def test_answer_refusal_paths_are_fixture_true_under_mocks() -> None:
    source = GraphDataSource(Settings(_env_file=None), store=seeded_store())
    response = source.ask(REPO, AskRequest(question="What is the weather in Paris?"))
    assert response.outcome.value == "refusal"
    assert response.fixture is True


def test_no_module_level_hardcoded_fixture_false_remains() -> None:
    import inspect

    from app.services import answer, data_source

    for module in (answer, data_source):
        body = inspect.getsource(module)
        assert "fixture=False" not in body, (
            f"{module.__name__} still hardcodes fixture=False"
        )


# --- mock mode must be explicit ---------------------------------------------


def test_graph_data_source_refuses_without_credentials_or_opt_in() -> None:
    cfg = Settings(_env_file=None, data_source="graph", neo4j_uri="", llm_provider="")
    with pytest.raises(DataSourceError) as excinfo:
        get_data_source(cfg)
    message = str(excinfo.value).lower()
    assert "neo4j" in message or "llm" in message
    assert "allow_mock_providers" in message


def test_graph_data_source_allows_explicit_mock_mode() -> None:
    cfg = Settings(
        _env_file=None,
        data_source="graph",
        neo4j_uri="",
        llm_provider="",
        allow_mock_providers=True,
    )
    source = get_data_source(cfg)
    assert isinstance(source, GraphDataSource)
    # The repository must exist in the store: an unknown one is now a 404, which
    # this test is not about. What it is about is the `fixture` flag.
    source.store = seeded_store()
    response = source.ask(REPO, AskRequest(question="Why is MAX_RETRIES 3?"))
    assert response.fixture is True


def test_fixture_source_still_reports_fixture_true() -> None:
    from app.fixtures.source import FixtureDataSource

    source = get_data_source(Settings(_env_file=None))
    assert isinstance(source, FixtureDataSource)
    assert source.get_repository("acme-netclient").fixture is True
