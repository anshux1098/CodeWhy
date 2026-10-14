"""A record that does not exist is a 404, whichever data source is serving.

The fixture source already refused unknown ids. The graph source did not: it
raised a plain DataSourceError, which the API reports as 503 and so claimed the
database was broken, and it returned an empty graph with 200 for an entity that was
never in the graph at all. Both statements are false. Only a genuine
infrastructure failure is a 503.

These run against the graph source on an in-memory store, so the production code
path is covered without a database. The store reports `is_real = False`, so every
response must still carry `fixture: true`.
"""

from __future__ import annotations

import pytest

from app.schemas.errors import ErrorResponse

API = "/api/v1"
REPO = "acme-netclient"


def assert_error_body(response, expected_detail: str) -> None:
    """The 404 body is the documented ErrorResponse shape."""
    assert response.status_code == 404
    payload = response.json()
    assert set(payload) == {"detail"}, "the error body carries only a detail"
    assert ErrorResponse.model_validate(payload).detail == payload["detail"]
    assert expected_detail in payload["detail"]
    assert payload["detail"].strip()


def test_an_unknown_decision_is_404_on_the_graph_source(graph_client) -> None:
    response = graph_client.get(f"{API}/decisions/dec_does_not_exist")

    assert_error_body(response, "dec_does_not_exist")


def test_an_unknown_entity_on_the_graph_route_is_404(graph_client) -> None:
    response = graph_client.get(
        f"{API}/repositories/{REPO}/graph", params={"entity_id": "key:NO_SUCH_ENTITY"}
    )

    assert_error_body(response, "key:NO_SUCH_ENTITY")


def test_an_unknown_repository_is_404_on_the_graph_source(graph_client) -> None:
    response = graph_client.get(f"{API}/repositories/acme-other")

    assert_error_body(response, "acme-other")


def test_an_unknown_repository_is_404_on_its_subroutes(graph_client) -> None:
    entities = graph_client.get(f"{API}/repositories/acme-other/entities", params={"q": "x"})
    ask = graph_client.post(
        f"{API}/repositories/acme-other/ask", json={"question": "Why is MAX_RETRIES 3?"}
    )
    graph = graph_client.get(f"{API}/repositories/acme-other/graph")

    for response in (entities, ask, graph):
        assert_error_body(response, "acme-other")


def test_a_known_record_is_still_served(graph_client) -> None:
    """The 404 rules must not turn a real hit into a miss."""
    decision = graph_client.get(f"{API}/decisions/dec_1")
    entity_graph = graph_client.get(
        f"{API}/repositories/{REPO}/graph", params={"entity_id": "key:MAX_RETRIES"}
    )

    assert decision.status_code == 200
    assert decision.json()["id"] == "dec_1"
    assert entity_graph.status_code == 200
    assert [node["id"] for node in entity_graph.json()["nodes"]]


def test_graph_responses_are_flagged_as_fixtures(graph_client) -> None:
    """An in-memory store is not a real repository, and must not pretend to be."""
    decision = graph_client.get(f"{API}/decisions/dec_1")
    repository = graph_client.get(f"{API}/repositories/{REPO}")

    assert decision.json()["fixture"] is True
    assert repository.json()["fixture"] is True


def test_a_missing_record_is_not_reported_as_a_server_error(graph_client) -> None:
    """A 503 would tell the caller the database is down. Nothing here is down."""
    responses = [
        graph_client.get(f"{API}/decisions/nope"),
        graph_client.get(f"{API}/repositories/acme-other"),
        graph_client.get(f"{API}/repositories/{REPO}/graph",
                         params={"entity_id": "key:NO_SUCH_ENTITY"}),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404]
