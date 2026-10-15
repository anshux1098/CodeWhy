"""Ask for the JSON schema where the endpoint understands it.

OpenAI-compatible endpoints disagree about `response_format`. Some accept
`{"type": "json_schema", "json_schema": {...}}`; others reject it with 400 and
accept only `{"type": "json_object"}`. Sending the strict form unconditionally
would fail the whole run on the second kind, so the provider tries the strict form
once and falls back, recording which mode was actually used.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.providers.llm_provider import (
    RESPONSE_FORMAT_JSON_OBJECT,
    RESPONSE_FORMAT_JSON_SCHEMA,
    OpenAICompatibleProvider,
)

KEY = "test-key-not-a-real-secret"

SCHEMA = {
    "type": "object",
    "properties": {"decisions": {"type": "array", "items": {"type": "object"}}},
    "required": ["decisions"],
    "additionalProperties": False,
}


class FakeTransport(httpx.BaseTransport):
    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = list(responses)
        self.bodies: list[dict[str, Any]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        import json as _json

        self.bodies.append(_json.loads(request.content))
        if not self._responses:
            raise AssertionError("more requests than scripted responses")
        return self._responses.pop(0)


def ok(body: str = '{"decisions": []}') -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": body}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 4},
        },
    )


def call(transport: FakeTransport, response_schema: dict | None):
    import app.providers.llm_provider as module

    real_client = module.httpx.Client

    def factory(*args: Any, **kwargs: Any) -> httpx.Client:
        return real_client(*args, transport=transport, **kwargs)

    module.httpx.Client = factory  # type: ignore[assignment]
    original_sleep = module.time.sleep
    module.time.sleep = lambda _s: None  # type: ignore[assignment]
    try:
        provider = OpenAICompatibleProvider(
            api_key=KEY, model="test-model", base_url="https://example.invalid/v1",
            response_json_schema=response_schema,
        )
        return provider.complete(prompt="ping", max_tokens=32)
    finally:
        module.httpx.Client = real_client  # type: ignore[assignment]
        module.time.sleep = original_sleep  # type: ignore[assignment]


def test_the_strict_form_is_sent_when_a_schema_is_supplied() -> None:
    transport = FakeTransport([ok()])

    call(transport, SCHEMA)

    sent = transport.bodies[0]["response_format"]
    assert sent["type"] == "json_schema"
    assert sent["json_schema"]["schema"] == SCHEMA


def test_no_schema_means_the_plain_json_object_form() -> None:
    transport = FakeTransport([ok()])

    call(transport, None)

    assert transport.bodies[0]["response_format"] == {"type": "json_object"}


def test_a_400_on_the_strict_form_falls_back_to_the_plain_form() -> None:
    transport = FakeTransport([
        httpx.Response(400, json={"error": {"message": "unsupported response_format"}}),
        ok(),
    ])

    response = call(transport, SCHEMA)

    assert transport.bodies[0]["response_format"]["type"] == "json_schema"
    assert transport.bodies[1]["response_format"] == {"type": "json_object"}
    assert response.status_code == 200


def test_the_mode_actually_used_is_reported() -> None:
    transport = FakeTransport([httpx.Response(400, json={"error": "nope"}), ok()])

    response = call(transport, SCHEMA)

    assert response.response_format_mode == RESPONSE_FORMAT_JSON_OBJECT


def test_no_fallback_happens_when_the_strict_form_works() -> None:
    transport = FakeTransport([ok()])

    response = call(transport, SCHEMA)

    assert len(transport.bodies) == 1
    assert response.response_format_mode == RESPONSE_FORMAT_JSON_SCHEMA


def test_a_400_without_a_schema_is_still_fatal() -> None:
    """Falling back when there was nothing to fall back from would hide a real error."""
    transport = FakeTransport([httpx.Response(400, json={"error": "bad request"})])

    with pytest.raises(Exception):
        call(transport, None)


def test_only_one_fallback_attempt_is_made() -> None:
    transport = FakeTransport([
        httpx.Response(400, json={"error": "unsupported"}),
        httpx.Response(400, json={"error": "still bad"}),
    ])

    with pytest.raises(Exception):
        call(transport, SCHEMA)

    assert len(transport.bodies) == 2, "one strict attempt plus one fallback, no more"
    assert transport.bodies[0]["response_format"]["type"] == "json_schema"
    assert transport.bodies[1]["response_format"] == {"type": "json_object"}


def test_a_per_call_schema_is_sent_and_reported() -> None:
    """A schema passed per call must appear in the body and in the reported mode."""
    transport = FakeTransport([ok()])

    import app.providers.llm_provider as module

    real_client = module.httpx.Client

    def factory(*args: Any, **kwargs: Any) -> httpx.Client:
        return real_client(*args, transport=transport, **kwargs)

    module.httpx.Client = factory  # type: ignore[assignment]
    original_sleep = module.time.sleep
    module.time.sleep = lambda _s: None  # type: ignore[assignment]
    try:
        # No schema at construction, as the extraction service does.
        provider = OpenAICompatibleProvider(
            api_key=KEY, model="test-model", base_url="https://example.invalid/v1"
        )
        response = provider.complete(
            prompt="ping", max_tokens=32, response_json_schema=SCHEMA
        )
    finally:
        module.httpx.Client = real_client  # type: ignore[assignment]
        module.time.sleep = original_sleep  # type: ignore[assignment]

    assert transport.bodies[0]["response_format"]["type"] == "json_schema"
    assert response.response_format_mode == RESPONSE_FORMAT_JSON_SCHEMA, (
        "the reported mode must be the one actually sent"
    )


def test_the_schema_is_sanitised_into_a_name() -> None:
    """A named schema needs a name, and the model name is the natural one."""
    transport = FakeTransport([ok()])

    call(transport, SCHEMA)

    sent = transport.bodies[0]["response_format"]["json_schema"]
    assert sent["name"]
    assert " " not in sent["name"], "a name with spaces can be rejected"