"""Provider selection and credential routing.

The point of these tests is one guarantee: a credential only ever reaches the host
an operator configured. A Gemini key sent to api.openai.com is a leaked key, and
it would also silently produce plausible-looking wrong answers.
"""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel

from app.config import Settings
from app.providers.llm_provider import (
    PROVIDER_BASE_URLS,
    BaseLLMProvider,
    OpenAICompatibleProvider,
    get_llm_provider,
)

GOOGLE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class Answer(BaseModel):
    no_decision: bool = False


class RecordingTransport(httpx.BaseTransport):
    """Captures the request instead of sending it. No network, no key leaves."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:  # noqa: D102
        self.requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({"no_decision": True})}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5},
            },
        )


def settings_for(provider: str, **overrides) -> Settings:
    base = {
        "llm_provider": provider,
        "llm_model": "gemini-3.6-flash",
        "llm_api_key": "placeholder-key-not-real",
        "neo4j_uri": "neo4j+s://x.invalid",
        "neo4j_username": "u",
        "neo4j_password": "p",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


# --- provider selection ----------------------------------------------------


@pytest.mark.parametrize("name", ["google", "gemini"])
def test_google_and_gemini_are_supported(name: str) -> None:
    assert name in PROVIDER_BASE_URLS


def test_google_uses_the_documented_compatibility_endpoint() -> None:
    assert PROVIDER_BASE_URLS["google"] == GOOGLE_URL
    assert PROVIDER_BASE_URLS["gemini"] == GOOGLE_URL


def test_google_resolves_to_a_real_provider() -> None:
    provider = get_llm_provider(cfg=settings_for("google"))
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.is_real is True


def test_the_gemini_alias_works_too() -> None:
    assert isinstance(get_llm_provider(cfg=settings_for("gemini")), OpenAICompatibleProvider)


def test_an_explicit_base_url_overrides_the_default() -> None:
    provider = get_llm_provider(
        cfg=settings_for("google", llm_base_url="https://proxy.internal/v1")
    )
    assert provider.base_url == "https://proxy.internal/v1"


def test_an_unknown_provider_still_raises_and_lists_the_supported_ones() -> None:
    with pytest.raises(ValueError) as excinfo:
        get_llm_provider(cfg=settings_for("not-a-provider"))
    message = str(excinfo.value)
    assert "not-a-provider" in message
    for name in ("google", "gemini", "mock", "openai", "ollama"):
        assert name in message, f"{name} missing from the error: {message}"


def test_openai_default_is_not_referenced_anywhere_in_the_factory() -> None:
    """The URL must come from the map, not a literal in the factory body."""
    import inspect

    body = inspect.getsource(get_llm_provider)
    assert "api.openai.com" not in body, (
        "the OpenAI URL is still hardcoded in the factory instead of the map"
    )


# --- credential routing ----------------------------------------------------


def test_a_google_key_is_never_sent_to_the_openai_endpoint() -> None:
    """The single most important guarantee in this module."""
    provider = get_llm_provider(cfg=settings_for("google"))
    transport = RecordingTransport()

    original = httpx.Client
    httpx.Client = lambda *a, **k: original(transport=transport, **{x: y for x, y in k.items() if x != "transport"})
    try:
        provider.complete("say ok")
    finally:
        httpx.Client = original

    assert transport.requests, "no request was attempted"
    sent = transport.requests[0]
    assert "generativelanguage.googleapis.com" in str(sent.url)
    assert "api.openai.com" not in str(sent.url), "the key was routed to OpenAI"


def test_the_key_is_sent_only_to_the_configured_host() -> None:
    provider = get_llm_provider(
        cfg=settings_for("google", llm_base_url="https://proxy.internal/v1")
    )
    transport = RecordingTransport()
    original = httpx.Client
    httpx.Client = lambda *a, **k: original(transport=transport, **{x: y for x, y in k.items() if x != "transport"})
    try:
        provider.complete("say ok")
    finally:
        httpx.Client = original

    assert str(transport.requests[0].url).startswith("https://proxy.internal/v1")


def test_the_authorization_header_carries_the_configured_key() -> None:
    provider = get_llm_provider(cfg=settings_for("google"))
    transport = RecordingTransport()
    original = httpx.Client
    httpx.Client = lambda *a, **k: original(transport=transport, **{x: y for x, y in k.items() if x != "transport"})
    try:
        provider.complete("say ok")
    finally:
        httpx.Client = original

    request = transport.requests[0]
    assert request.headers["Authorization"] == "Bearer placeholder-key-not-real"
    assert request.url.path.endswith("/chat/completions")


def test_the_request_body_shape_is_openai_compatible() -> None:
    """Documents what the compatibility endpoint must accept."""
    provider = get_llm_provider(cfg=settings_for("google"))
    transport = RecordingTransport()
    original = httpx.Client
    httpx.Client = lambda *a, **k: original(transport=transport, **{x: y for x, y in k.items() if x != "transport"})
    try:
        provider.complete_structured(schema=Answer, prompt="p", system="s")
    finally:
        httpx.Client = original

    body = json.loads(transport.requests[0].content)
    assert body["model"] == "gemini-3.6-flash"
    assert isinstance(body["messages"], list)
    assert "response_format" in body
    assert body["response_format"]["type"] == "json_object"
    assert "max_tokens" in body


def test_a_real_provider_is_not_marked_real_when_it_is_the_mock() -> None:
    mock = get_llm_provider(cfg=settings_for("mock"))
    assert isinstance(mock, BaseLLMProvider)
    assert mock.is_real is False
