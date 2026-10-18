from __future__ import annotations

import pytest

from app.fixtures.dataset import EXAMPLE_QUESTIONS, REPOSITORY_ID
from app.schemas.errors import ErrorResponse

API = "/api/v1"


def test_app_starts_and_reports_health(client) -> None:
    payload = client.get(f"{API}/health").json()
    assert payload["status"] == "ok"
    assert payload["data_source"] == "fixture"


def test_docs_are_served(client) -> None:
    response = client.get("/docs")
    assert response.status_code == 200
    assert "swagger" in response.text.lower()


def test_openapi_lists_every_route(client) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths) == {
        f"{API}/health",
        f"{API}/health/dependencies",
        f"{API}/repositories/{{repository_id}}",
        f"{API}/repositories/{{repository_id}}/entities",
        f"{API}/repositories/{{repository_id}}/ask",
        f"{API}/repositories/{{repository_id}}/graph",
        f"{API}/repositories/{{repository_id}}/decisions",
        f"{API}/decisions/{{decision_id}}",
    }


def test_openapi_documents_the_confidence_rules(client) -> None:
    body = client.get("/openapi.json").text
    assert "no_verified_quote" in body
    assert "confidence is null" in body


def test_cors_allows_the_frontend_origin_on_a_preflight(client) -> None:
    response = client.options(
        f"{API}/repositories/{REPOSITORY_ID}/ask",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_header_present_on_a_normal_request(client) -> None:
    response = client.get(f"{API}/health", headers={"Origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_is_not_wildcard(client) -> None:
    response = client.get(f"{API}/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_repository_endpoint(client) -> None:
    payload = client.get(f"{API}/repositories/{REPOSITORY_ID}").json()
    assert payload["id"] == REPOSITORY_ID
    assert payload["fixture"] is True
    assert payload["counts"]["decisions"] == 5


def test_unknown_repository_is_404(client) -> None:
    response = client.get(f"{API}/repositories/acme/other")
    assert response.status_code == 404
    assert "detail" in response.json()


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("GET", f"{API}/repositories/acme/other", None),
        ("GET", f"{API}/repositories/acme/other/entities?q=x", None),
        ("POST", f"{API}/repositories/acme/other/ask", {"question": "Why is MAX_RETRIES 3?"}),
        ("GET", f"{API}/repositories/{REPOSITORY_ID}/graph", None),
        ("GET", f"{API}/repositories/acme/other/decisions", None),
        ("GET", f"{API}/decisions/dec_missing", None),
    ],
    ids=["repository", "entities", "ask", "graph", "decisions_list", "decision"],
)
def test_every_not_found_route_returns_the_error_response_shape(client, method, url, body) -> None:
    if url.endswith("/graph"):
        response = client.get(url, params={"entity_id": "key:NO_SUCH_ENTITY"})
    elif method == "POST":
        response = client.post(url, json=body)
    else:
        response = client.get(url)
    assert response.status_code == 404
    payload = response.json()
    assert set(payload) == {"detail"}
    assert ErrorResponse.model_validate(payload).detail == payload["detail"]
    assert payload["detail"].strip()


def test_entities_endpoint(client) -> None:
    payload = client.get(f"{API}/repositories/{REPOSITORY_ID}/entities", params={"q": "MAX"}).json()
    assert payload["entities"][0]["label"] == "MAX_RETRIES"
    assert payload["query"] == "MAX"
    assert payload["fixture"] is True


def test_decision_endpoint(client) -> None:
    payload = client.get(f"{API}/decisions/dec_77").json()
    assert payload["id"] == "dec_77"
    assert payload["state"] == "SUPERSEDED"
    assert payload["supersedes"] == ["dec_41"]
    assert payload["citations"][0]["id"] == "cit_77"
    assert payload["fixture"] is True


def test_unknown_decision_is_404(client) -> None:
    assert client.get(f"{API}/decisions/dec_missing").status_code == 404


DECISIONS_URL = f"{API}/repositories/acme-netclient/decisions"


def test_decisions_list_endpoint_orders_newest_first(client) -> None:
    payload = client.get(DECISIONS_URL).json()
    assert payload["fixture"] is True
    assert payload["total"] == 5
    assert payload["limit"] == 50 and payload["offset"] == 0
    assert [item["id"] for item in payload["items"]] == [
        "dec_104", "dec_90", "dec_77", "dec_41", "dec_55",
    ]


def test_decisions_list_items_carry_a_date_and_a_source(client) -> None:
    item = next(i for i in client.get(DECISIONS_URL).json()["items"] if i["id"] == "dec_77")
    assert item["date"] == "2024-06-04T10:02:00Z"
    assert item["source_url"].endswith("/pull/77")
    assert item["entities"] == ["key:MAX_RETRIES"]
    assert item["supersedes"] == ["dec_41"]


def test_decisions_list_filters_by_state(client) -> None:
    payload = client.get(DECISIONS_URL, params={"state": "SUPERSEDED"}).json()
    assert [item["id"] for item in payload["items"]] == ["dec_77"]
    assert payload["total"] == 1


def test_decisions_list_filters_by_entity(client) -> None:
    payload = client.get(DECISIONS_URL, params={"entity_id": "file:netclient/retry.py"}).json()
    assert {item["id"] for item in payload["items"]} == {"dec_104"}
    assert payload["total"] == 1


def test_decisions_list_pages_without_changing_the_total(client) -> None:
    payload = client.get(DECISIONS_URL, params={"limit": 2, "offset": 1}).json()
    assert payload["total"] == 5
    assert [item["id"] for item in payload["items"]] == ["dec_90", "dec_77"]


def test_decisions_list_rejects_an_unknown_state_with_422(client) -> None:
    assert client.get(DECISIONS_URL, params={"state": "BOGUS"}).status_code == 422


def test_decisions_list_rejects_a_limit_above_the_maximum(client) -> None:
    assert client.get(DECISIONS_URL, params={"limit": 201}).status_code == 422


def test_graph_endpoint(client) -> None:
    payload = client.get(f"{API}/repositories/{REPOSITORY_ID}/graph").json()
    assert payload["truncated"] is False
    assert payload["fixture"] is True
    assert 0 < len(payload["nodes"]) <= 80


def test_graph_endpoint_filters_by_entity(client) -> None:
    scoped = client.get(
        f"{API}/repositories/{REPOSITORY_ID}/graph", params={"entity_id": "key:_PAD_BYTES"}
    ).json()
    full = client.get(f"{API}/repositories/{REPOSITORY_ID}/graph").json()
    assert len(scoped["nodes"]) < len(full["nodes"])
    ids = {node["id"] for node in scoped["nodes"]}
    assert all(edge["source"] in ids and edge["target"] in ids for edge in scoped["edges"])


def test_dependencies_endpoint_reports_every_service() -> None:
    from fastapi.testclient import TestClient

    from app.api.deps import get_settings
    from app.config import Settings
    from app.main import create_app

    empty = Settings(_env_file=None)
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: empty
    try:
        with TestClient(application) as unconfigured:
            payload = unconfigured.get(f"{API}/health/dependencies").json()
    finally:
        application.dependency_overrides.clear()
    states = {service["name"]: service["status"] for service in payload["services"]}
    assert states == {
        "github": "not configured",
        "neo4j": "not configured",
        "llm": "not configured",
        "embeddings": "configured",
    }
    assert payload["data_source"] == "fixture"


def test_health_version_matches_the_openapi_version(client) -> None:
    live = client.get(f"{API}/health").json()["version"]
    declared = client.get("/openapi.json").json()["info"]["version"]
    assert live == declared


def test_dependencies_endpoint_survives_a_malformed_neo4j_uri() -> None:
    from fastapi.testclient import TestClient

    from app.api.deps import get_settings
    from app.config import Settings
    from app.main import create_app

    broken = Settings(_env_file=None, neo4j_uri="neo4j+s://db.example.invalid:7687[")
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: broken
    try:
        with TestClient(application) as configured:
            response = configured.get(f"{API}/health/dependencies")
    finally:
        application.dependency_overrides.clear()
    assert response.status_code == 200
    services = {service["name"]: service for service in response.json()["services"]}
    assert services["neo4j"]["status"] == "configured"
    assert services["neo4j"]["detail"] == "NEO4J_URI is not a valid URI"


def test_dependencies_endpoint_leaks_no_secret() -> None:
    from fastapi.testclient import TestClient

    from app.api.deps import get_settings
    from app.config import Settings
    from app.main import create_app

    fake = Settings(
        _env_file=None,
        github_token="ghp_FAKE_TOKEN_VALUE",
        neo4j_uri="neo4j+s://neo4juser:supersecretpassword@db.example.invalid",
        neo4j_username="neo4juser",
        neo4j_password="supersecretpassword",
        llm_api_key="sk-FAKE-KEY-VALUE",
    )
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: fake
    try:
        with TestClient(application) as configured:
            response = configured.get(f"{API}/health/dependencies")
    finally:
        application.dependency_overrides.clear()
    body = response.text
    states = {service["name"]: service["status"] for service in response.json()["services"]}
    assert states == {
        "github": "configured",
        "neo4j": "configured",
        "llm": "configured",
        "embeddings": "configured",
    }
    for secret in (
        "ghp_FAKE_TOKEN_VALUE",
        "supersecretpassword",
        "sk-FAKE-KEY-VALUE",
        "neo4juser",
    ):
        assert secret not in body
    assert "db.example.invalid" in body


def test_entities_endpoint_rejects_a_blank_query(client) -> None:
    assert client.get(f"{API}/repositories/{REPOSITORY_ID}/entities", params={"q": ""}).status_code == 422


def test_repository_routes_use_a_slug_converter(client) -> None:
    from app.api.routes_repositories import router as repositories_router

    for route in repositories_router.routes:
        assert "{repository_id}" in route.path_format
        assert ":path" not in route.path_format


def test_a_repository_id_containing_a_slash_is_not_accepted(client) -> None:
    response = client.get(f"{API}/repositories/acme/netclient")
    assert response.status_code == 404


def test_ask_rejects_an_empty_question(client) -> None:
    response = client.post(f"{API}/repositories/{REPOSITORY_ID}/ask", json={"question": ""})
    assert response.status_code == 422


def test_ask_rejects_an_unknown_body_field(client) -> None:
    response = client.post(
        f"{API}/repositories/{REPOSITORY_ID}/ask",
        json={"question": "Why is MAX_RETRIES 3?", "temperature": 0.1},
    )
    assert response.status_code == 422


def test_ask_on_an_unknown_repository_is_404(client) -> None:
    response = client.post(f"{API}/repositories/acme/other/ask", json={"question": "Why is MAX_RETRIES 3?"})
    assert response.status_code == 404


def test_ask_example_questions_end_to_end(client) -> None:
    for name, spec in EXAMPLE_QUESTIONS.items():
        payload = client.post(
            f"{API}/repositories/{REPOSITORY_ID}/ask", json={"question": spec["question"]}
        ).json()
        assert payload["outcome"] == spec["outcome"], name
        assert payload["reason_code"] == spec["reason_code"], name
        assert payload["fixture"] is True, name


def test_ask_full_answer_carries_a_source_citation(client) -> None:
    payload = client.post(
        f"{API}/repositories/{REPOSITORY_ID}/ask", json={"question": EXAMPLE_QUESTIONS["full"]["question"]}
    ).json()
    assert payload["confidence"]["label"] == "HIGH"
    assert any(citation["kind"] == "SOURCE" for citation in payload["citations"])
    assert payload["who_to_ask"]


def test_ask_prescoring_refusals_have_no_confidence(client) -> None:
    payload = client.post(
        f"{API}/repositories/{REPOSITORY_ID}/ask",
        json={"question": EXAMPLE_QUESTIONS["entity_not_found"]["question"]},
    ).json()
    assert payload["confidence"] is None


def test_ask_with_an_explicit_entity_id_resolves_that_entity(client) -> None:
    payload = client.post(
        f"{API}/repositories/{REPOSITORY_ID}/ask",
        json={"question": "Why is this value what it is?", "entity_id": "key:_PAD_BYTES"},
    ).json()
    assert payload["reason_code"] == "no_decision_path"
    assert payload["entity"]["id"] == "key:_PAD_BYTES"
