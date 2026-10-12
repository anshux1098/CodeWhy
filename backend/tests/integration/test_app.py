from __future__ import annotations

from app.fixtures.dataset import EXAMPLE_QUESTIONS, REPOSITORY_ID

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
    assert response.headers.get("access-control-allow-origin") != "*"


def test_repository_endpoint(client) -> None:
    payload = client.get(f"{API}/repositories/{REPOSITORY_ID}").json()
    assert payload["id"] == REPOSITORY_ID
    assert payload["fixture"] is True
    assert payload["counts"]["decisions"] == 5


def test_unknown_repository_is_404(client) -> None:
    response = client.get(f"{API}/repositories/acme/other")
    assert response.status_code == 404
    assert "detail" in response.json()


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


def test_dependencies_endpoint_reports_every_service(client) -> None:
    payload = client.get(f"{API}/health/dependencies").json()
    states = {service["name"]: service["status"] for service in payload["services"]}
    assert set(states) == {"github", "neo4j", "llm", "embeddings"}
    assert payload["data_source"] == "fixture"


def test_dependencies_endpoint_leaks_no_secret(client) -> None:
    body = client.get(f"{API}/health/dependencies").text
    for secret in ("ghp_", "sk-", "Bearer ", "password\": \""):
        assert secret not in body


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
