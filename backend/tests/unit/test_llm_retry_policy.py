"""Retry policy for transient upstream failures.

A model endpoint that answers 503 because it is briefly overloaded is a different
situation from one that rejects the request with 400 or 401. The first deserves
patience; the second only deserves a clear message.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx
import pytest

from app.providers.llm_provider import (
    MAX_ATTEMPTS,
    NON_RETRYABLE_STATUSES,
    RETRY_BACKOFF_SECONDS,
    RETRYABLE_STATUSES,
    LLMProviderError,
    OpenAICompatibleProvider,
)

KEY = "test-key-not-a-real-secret"


class FakeTransport(httpx.BaseTransport):
    """Replays a scripted list of responses and records every request."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self._responses:
            raise AssertionError("the client asked for more responses than the script has")
        return self._responses.pop(0)


def ok(body: str = '{"ok": true}', headers: Optional[dict[str, str]] = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": body}}],
              "usage": {"prompt_tokens": 5, "completion_tokens": 5}},
        headers=headers,
    )


def failure(status: int, headers: Optional[dict[str, str]] = None) -> httpx.Response:
    return httpx.Response(status, json={"error": "nope"}, headers=headers)


def attempt_call(provider: OpenAICompatibleProvider, transport: FakeTransport, sleeper: Any):
    """Call the provider with the fake transport and a recording sleep."""
    import app.providers.llm_provider as module

    real_client = module.httpx.Client

    def factory(*args: Any, **kwargs: Any) -> httpx.Client:
        return real_client(*args, transport=transport, **kwargs)

    module.httpx.Client = factory  # type: ignore[assignment]
    original_sleep = module.time.sleep
    module.time.sleep = sleeper  # type: ignore[assignment]
    try:
        return provider.complete(prompt="ping", system="test", max_tokens=16)
    finally:
        module.httpx.Client = real_client  # type: ignore[assignment]
        module.time.sleep = original_sleep  # type: ignore[assignment]


def build(transport: FakeTransport) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        api_key=KEY, model="gemini-test", base_url="https://example.invalid/v1"
    )


def test_the_schedule_is_the_six_documented_waits() -> None:
    assert RETRY_BACKOFF_SECONDS == (5, 15, 30, 60, 120, 120)
    assert MAX_ATTEMPTS == 7


@pytest.mark.parametrize("status", sorted(RETRYABLE_STATUSES))
def test_each_transient_status_is_retried_until_it_succeeds(status: int) -> None:
    transport = FakeTransport([failure(status), failure(status), ok()])
    waits: list[float] = []

    response = attempt_call(build(transport), transport, waits.append)

    assert response.status_code == 200
    assert len(transport.requests) == 3
    assert waits == [5.0, 15.0]


@pytest.mark.parametrize("status", sorted(NON_RETRYABLE_STATUSES))
def test_each_client_error_fails_on_the_first_attempt(status: int) -> None:
    transport = FakeTransport([failure(status)] * (MAX_ATTEMPTS + 3))
    waits: list[float] = []

    with pytest.raises(LLMProviderError) as excinfo:
        attempt_call(build(transport), transport, waits.append)

    assert len(transport.requests) == 1, "a bad request must not be repeated"
    assert waits == []
    assert str(status) in str(excinfo.value)


def test_a_retry_after_header_overrides_the_scheduled_wait() -> None:
    transport = FakeTransport([failure(503, {"Retry-After": "2"}), ok()])
    waits: list[float] = []
    provider = build(transport)
    attempt_call(provider, transport, waits.append)

    assert waits == [2.0], "the server asked for 2s, not the scheduled 5s"


def test_a_nonsensical_retry_after_falls_back_to_the_schedule() -> None:
    transport = FakeTransport([failure(503, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}), ok()])
    waits: list[float] = []
    provider = build(transport)
    attempt_call(provider, transport, waits.append)

    assert waits == [5.0]


def test_giving_up_uses_every_scheduled_wait_exactly_once() -> None:
    transport = FakeTransport([failure(503)] * (MAX_ATTEMPTS + 4))
    waits: list[float] = []
    provider = build(transport)

    with pytest.raises(LLMProviderError) as excinfo:
        attempt_call(provider, transport, waits.append)

    assert len(transport.requests) == MAX_ATTEMPTS
    assert waits == [float(value) for value in RETRY_BACKOFF_SECONDS]
    assert "503" in str(excinfo.value)


def test_a_success_on_the_first_attempt_does_not_wait() -> None:
    transport = FakeTransport([ok()])
    waits: list[float] = []

    response = attempt_call(build(transport), transport, waits.append)

    assert response.status_code == 200
    assert waits == []
