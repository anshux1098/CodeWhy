"""A 200 with no text is not a success.

A reasoning model can answer with `content: null` and `finish_reason: "length"`
when every output token went into thinking. Treating that as a result would store
an empty citation; treating it as a transient fault would spend seven attempts
against an endpoint that is answering perfectly well.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx
import pytest

from app.config import Settings
from app.providers.llm_provider import (
    LLMEmptyReplyError,
    OpenAICompatibleProvider,
)

KEY = "test-key-not-a-real-secret"


class FakeTransport(httpx.BaseTransport):
    """Replays scripted responses and records the bodies it was sent."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []
        self.bodies: list[dict[str, Any]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        import json as _json

        self.requests.append(request)
        self.bodies.append(_json.loads(request.content))
        if not self._responses:
            raise AssertionError("the client asked for more responses than the script has")
        return self._responses.pop(0)


def reply(
    content: Optional[str],
    finish_reason: str = "stop",
    *,
    reasoning: Optional[str] = None,
    usage: Optional[dict[str, Any]] = None,
) -> httpx.Response:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning"] = reasoning
    return httpx.Response(
        200,
        json={
            "choices": [{"message": message, "finish_reason": finish_reason}],
            "usage": usage if usage is not None else {
                "prompt_tokens": 11, "completion_tokens": 5,
            },
        },
    )


def attempt(
    transport: FakeTransport,
    *,
    max_output_tokens: int = 4096,
    max_tokens: Optional[int] = None,
    reasoning_effort: Optional[str] = None,
) -> Any:
    """Call complete() with the transport patched in and no real sleeping."""
    import app.providers.llm_provider as module

    real_client = module.httpx.Client

    def factory(*args: Any, **kwargs: Any) -> httpx.Client:
        return real_client(*args, transport=transport, **kwargs)

    module.httpx.Client = factory  # type: ignore[assignment]
    original_sleep = module.time.sleep
    module.time.sleep = lambda _seconds: None  # type: ignore[assignment]
    try:
        provider = OpenAICompatibleProvider(
            api_key=KEY, model="test-model", base_url="https://example.invalid/v1",
            max_output_tokens=max_output_tokens, reasoning_effort=reasoning_effort,
        )
        return provider.complete(prompt="ping", system="test", max_tokens=max_tokens)
    finally:
        module.httpx.Client = real_client  # type: ignore[assignment]
        module.time.sleep = original_sleep  # type: ignore[assignment]


# --- the four cases ---------------------------------------------------------


def test_a_normal_reply_is_returned_with_its_finish_reason() -> None:
    transport = FakeTransport([reply('{"ok": true}')])

    response = attempt(transport)

    assert response.content == '{"ok": true}'
    assert response.finish_reason == "stop"
    assert response.reasoning_present is False
    assert len(transport.requests) == 1


def test_null_content_with_finish_reason_length_names_the_reasoning_limit() -> None:
    transport = FakeTransport([
        reply(None, "length", reasoning="thinking...", usage={
            "prompt_tokens": 11, "completion_tokens": 512,
            "completion_tokens_details": {"reasoning_tokens": 512},
        }),
        reply(None, "length", reasoning="thinking...", usage={
            "prompt_tokens": 11, "completion_tokens": 512,
            "completion_tokens_details": {"reasoning_tokens": 512},
        }),
    ])

    with pytest.raises(LLMEmptyReplyError) as excinfo:
        attempt(transport, max_output_tokens=8192, max_tokens=2048)

    error = excinfo.value
    assert "output limit consumed by reasoning" in str(error)
    assert error.finish_reason == "length"
    assert error.reasoning_present is True
    assert error.reasoning_tokens == 512
    assert error.retried is True, "a length reply is retried once with a bigger budget"


def test_a_length_reply_is_retried_once_with_a_doubled_budget() -> None:
    transport = FakeTransport([reply(None, "length"), reply('{"ok": true}')])

    response = attempt(transport, max_output_tokens=8192, max_tokens=2048)

    assert response.content == '{"ok": true}'
    assert len(transport.requests) == 2, "exactly one retry, not seven"
    assert transport.bodies[0]["max_tokens"] == 2048
    assert transport.bodies[1]["max_tokens"] == 4096, "the budget is doubled"


def test_the_retry_stops_at_the_configured_ceiling() -> None:
    transport = FakeTransport([reply(None, "length")])

    with pytest.raises(LLMEmptyReplyError):
        attempt(transport, max_output_tokens=4096, max_tokens=4096)

    assert len(transport.requests) == 1, (
        "already at the ceiling, so there is nothing to raise it to"
    )


def test_null_content_with_finish_reason_stop_is_retried_at_most_once() -> None:
    transport = FakeTransport([reply(None, "stop"), reply(None, "stop")])

    with pytest.raises(LLMEmptyReplyError) as excinfo:
        attempt(transport)

    assert len(transport.requests) == 2, "one retry, then the failure is reported"
    assert excinfo.value.finish_reason == "stop"
    assert excinfo.value.retried is True


def test_an_empty_string_is_treated_the_same_as_null() -> None:
    transport = FakeTransport([reply("", "stop"), reply("", "stop")])

    with pytest.raises(LLMEmptyReplyError):
        attempt(transport)

    assert len(transport.requests) == 2


def test_a_reasoning_only_reply_is_not_mistaken_for_an_answer() -> None:
    """content is empty but the model did spend tokens thinking."""
    transport = FakeTransport([reply(None, "length", reasoning="step by step")])

    with pytest.raises(LLMEmptyReplyError) as excinfo:
        attempt(transport)

    assert excinfo.value.reasoning_present is True
    assert "reasoning" in str(excinfo.value)


def test_the_reasoning_alias_field_is_also_recognised() -> None:
    """OpenRouter documents reasoning_content as an alias for reasoning."""
    response = httpx.Response(
        200,
        json={
            "choices": [{
                "message": {"role": "assistant", "content": None, "reasoning_content": "hmm"},
                "finish_reason": "length",
            }],
            "usage": {"prompt_tokens": 5, "completion_tokens": 9},
        },
    )
    transport = FakeTransport([response, reply(None, "length", reasoning="hmm")])

    with pytest.raises(LLMEmptyReplyError) as excinfo:
        attempt(transport)

    assert excinfo.value.reasoning_present is True


def test_an_empty_reply_never_calls_len_on_none() -> None:
    """The whole point: content=None must not reach len()."""
    transport = FakeTransport([reply(None, "stop"), reply(None, "stop")])

    with pytest.raises(LLMEmptyReplyError):
        attempt(transport)  # a TypeError here would fail the test


def test_missing_usage_does_not_cause_an_error_on_an_empty_reply() -> None:
    response = httpx.Response(
        200,
        json={"choices": [{"message": {"content": None}, "finish_reason": "stop"}]},
    )
    transport = FakeTransport([response, response])

    with pytest.raises(LLMEmptyReplyError):
        attempt(transport)

    assert len(transport.requests) == 2


# --- the reasoning request parameter ---------------------------------------


def test_no_reasoning_key_is_sent_when_no_effort_is_configured() -> None:
    transport = FakeTransport([reply('{"ok": true}')])

    attempt(transport)

    assert "reasoning" not in transport.bodies[0]


def test_the_documented_reasoning_object_is_sent_when_configured() -> None:
    transport = FakeTransport([reply('{"ok": true}')])

    attempt(transport, reasoning_effort="low")

    assert transport.bodies[0]["reasoning"] == {"effort": "low", "exclude": True}


def test_only_openrouter_gets_a_reasoning_effort_from_the_factory() -> None:
    from app.providers.llm_provider import REASONING_EFFORT_BY_PROVIDER, get_llm_provider

    assert REASONING_EFFORT_BY_PROVIDER == {"openrouter": "low"}

    cfg = Settings(_env_file=None, llm_provider="openrouter", llm_model="m",
                   llm_api_key=KEY, llm_max_output_tokens=4096)
    assert get_llm_provider(cfg=cfg).reasoning_effort == "low"

    for name in ("google", "openai", "ollama"):
        cfg = Settings(_env_file=None, llm_provider=name, llm_model="m", llm_api_key=KEY)
        assert get_llm_provider(cfg=cfg).reasoning_effort is None


def test_the_configured_output_limit_is_the_default_max_tokens() -> None:
    transport = FakeTransport([reply('{"ok": true}')])

    attempt(transport, max_output_tokens=1234)

    assert transport.bodies[0]["max_tokens"] == 1234


def test_the_default_output_limit_is_four_thousand_ninety_six() -> None:
    assert Settings(_env_file=None).llm_max_output_tokens == 4096


def test_a_non_string_content_is_treated_as_empty() -> None:
    """A provider that sends a list or a dict must not crash the caller."""
    response = httpx.Response(
        200,
        json={"choices": [{"message": {"content": [{"type": "text", "text": "hi"}]},
                           "finish_reason": "stop"}],
              "usage": {"prompt_tokens": 5, "completion_tokens": 2}},
    )
    transport = FakeTransport([response, reply('{"ok": true}')])

    response_obj = attempt(transport)

    assert response_obj.finish_reason == "stop"
