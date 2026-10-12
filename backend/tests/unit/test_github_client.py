from __future__ import annotations

import json
import logging
from typing import Any, Callable

import httpx
import pytest

from app.config import Settings
from app.services.ingest.github_client import (
    BACKOFF_CAP_SECONDS,
    MAX_ATTEMPTS,
    GITHUB_GRAPHQL_URL,
    GitHubAuthError,
    GitHubGraphQLClient,
    GitHubProtocolError,
    GitHubRetryExhaustedError,
    assert_canonical_graphql_url,
    backoff_seconds,
)

SECRET = "ghp_ThisIsTheSecretTokenValue1234567890"


def settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, github_token=SECRET, **overrides)


class Recorder:
    def __init__(self, responses: list[httpx.Response | Exception]) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []
        self.slept: list[float] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)


def response(
    status_code: int = 200,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    body = payload if payload is not None else {"data": {"ok": True}}
    return httpx.Response(status_code, json=body, headers=headers or {})


def build(recorder: Recorder, **overrides: Any) -> GitHubGraphQLClient:
    return GitHubGraphQLClient(
        settings(**overrides),
        transport=httpx.MockTransport(recorder.handler),
        sleep=recorder.sleep,
        rng=lambda: 0.5,
    )


def rate_limited_payload(remaining: int, cost: int = 1) -> dict[str, Any]:
    return {
        "data": {
            "rateLimit": {
                "cost": cost,
                "limit": 5000,
                "remaining": remaining,
                "resetAt": "2026-10-12T18:00:00Z",
            }
        }
    }


# Endpoint and redirect guards


def test_canonical_endpoint_is_accepted() -> None:
    assert_canonical_graphql_url(GITHUB_GRAPHQL_URL)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/graphql",
        "http://api.github.com/graphql",
        "https://api.github.com/v4/graphql",
        "https://api.github.com.evil.example/graphql",
        "https://github.com/graphql",
    ],
)
def test_other_hosts_and_schemes_are_refused(url: str) -> None:
    with pytest.raises(GitHubProtocolError):
        assert_canonical_graphql_url(url)


def test_client_posts_only_to_the_canonical_endpoint() -> None:
    recorder = Recorder([response()])
    with build(recorder) as client:
        client.query("query { viewer { login } }")
    assert [str(request.url) for request in recorder.requests] == [GITHUB_GRAPHQL_URL]


def test_cross_host_redirect_is_refused_and_never_followed() -> None:
    recorder = Recorder(
        [
            httpx.Response(302, headers={"location": "https://evil.example/graphql"}),
            response(),
        ]
    )
    with build(recorder) as client, pytest.raises(GitHubProtocolError) as excinfo:
        client.query("query { viewer { login } }")
    assert "evil.example" in str(excinfo.value)
    assert len(recorder.requests) == 1
    assert all("evil.example" not in str(request.url) for request in recorder.requests)


# Retries


@pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
def test_retryable_statuses_are_retried_then_succeed(status_code: int) -> None:
    recorder = Recorder([response(status_code), response()])
    with build(recorder) as client:
        assert client.query("query { viewer { login } }") == {"data": {"ok": True}}
    assert len(recorder.requests) == 2
    assert len(recorder.slept) == 1


def test_gives_up_after_exactly_five_attempts() -> None:
    recorder = Recorder([response(503)] * (MAX_ATTEMPTS + 3))
    with build(recorder) as client, pytest.raises(GitHubRetryExhaustedError):
        client.query("query { viewer { login } }")
    assert len(recorder.requests) == MAX_ATTEMPTS
    assert len(recorder.slept) == MAX_ATTEMPTS - 1


def test_rate_limited_403_is_retried() -> None:
    recorder = Recorder(
        [
            response(403, rate_limited_payload(remaining=0), {"x-ratelimit-remaining": "0"}),
            response(),
        ]
    )
    with build(recorder) as client:
        client.query("query { viewer { login } }")
    assert len(recorder.requests) == 2


def test_transport_errors_are_retried() -> None:
    recorder = Recorder([httpx.ConnectError("boom"), response()])
    with build(recorder) as client:
        client.query("query { viewer { login } }")
    assert len(recorder.requests) == 2


# Auth failures fail fast


def test_403_without_rate_limit_evidence_fails_fast() -> None:
    recorder = Recorder([response(403), response()])
    with build(recorder) as client, pytest.raises(GitHubAuthError):
        client.query("query { viewer { login } }")
    assert len(recorder.requests) == 1
    assert recorder.slept == []


def test_401_fails_fast() -> None:
    recorder = Recorder([response(401)])
    with build(recorder) as client, pytest.raises(GitHubAuthError):
        client.query("query { viewer { login } }")
    assert len(recorder.requests) == 1


def test_missing_token_raises_a_settings_error_before_any_request() -> None:
    recorder = Recorder([response()])
    with pytest.raises(RuntimeError):
        GitHubGraphQLClient(
            Settings(_env_file=None, github_token=""),
            transport=httpx.MockTransport(recorder.handler),
            sleep=recorder.sleep,
        )
    assert recorder.requests == []


# Backoff


def test_backoff_is_bounded_and_jittered() -> None:
    for attempt in range(6):
        for sample in (0.0, 0.5, 1.0):
            value = backoff_seconds(attempt, lambda: sample)
            assert 0 < value <= BACKOFF_CAP_SECONDS
    assert backoff_seconds(0, lambda: 0.5) < backoff_seconds(3, lambda: 0.5)
    assert backoff_seconds(20, lambda: 1.0) <= BACKOFF_CAP_SECONDS


def test_backoff_actually_varies_with_jitter() -> None:
    values = {backoff_seconds(2, lambda: 0.0), backoff_seconds(2, lambda: 0.9)}
    assert len(values) == 2


# Rate limit plumbing


def test_rate_limit_is_read_from_every_response() -> None:
    recorder = Recorder([response(payload=rate_limited_payload(remaining=4999, cost=3))])
    with build(recorder) as client:
        client.query("query { viewer { login } }")
        snapshot = client.rate_limit
    assert snapshot is not None
    assert snapshot.cost == 3
    assert snapshot.remaining == 4999
    assert snapshot.limit == 5000
    assert snapshot.reset_at is not None
    assert snapshot.is_low() is False


def test_low_remaining_is_reported_as_low() -> None:
    recorder = Recorder([response(payload=rate_limited_payload(remaining=10))])
    with build(recorder) as client:
        client.query("query { viewer { login } }")
        assert client.rate_limit is not None
        assert client.rate_limit.is_low() is True


def test_graphql_errors_surface_as_a_protocol_error() -> None:
    recorder = Recorder([response(payload={"errors": [{"message": "Field does not exist"}]})])
    with build(recorder) as client, pytest.raises(GitHubProtocolError) as excinfo:
        client.query("query { nope }")
    assert "Field does not exist" in str(excinfo.value)


def test_non_json_response_is_a_protocol_error() -> None:
    recorder = Recorder([httpx.Response(200, text="<html>not json</html>")])
    with build(recorder) as client, pytest.raises(GitHubProtocolError):
        client.query("query { viewer { login } }")


def test_other_client_errors_are_not_retried() -> None:
    recorder = Recorder([response(404), response()])
    with build(recorder) as client, pytest.raises(GitHubProtocolError):
        client.query("query { viewer { login } }")
    assert len(recorder.requests) == 1


# The token must never escape


def assert_no_secret(caplog: pytest.LogCaptureFixture, *texts: str) -> None:
    captured = "\n".join(record.getMessage() for record in caplog.records)
    combined = "\n".join(texts) + "\n" + captured
    assert SECRET not in combined


@pytest.mark.parametrize(
    ("responses", "expected"),
    [
        ([response(403)], GitHubAuthError),
        ([response(404, {"message": "Not Found"})], GitHubProtocolError),
        ([response(503)] * (MAX_ATTEMPTS + 1), GitHubRetryExhaustedError),
        ([httpx.ConnectError("down")] * (MAX_ATTEMPTS + 1), GitHubRetryExhaustedError),
        ([response(payload={"errors": [{"message": "boom"}]})], GitHubProtocolError),
        ([httpx.Response(200, text="not json")], GitHubProtocolError),
    ],
)
def test_the_token_never_appears_in_exceptions_or_logs(
    caplog: pytest.LogCaptureFixture,
    responses: list[Any],
    expected: type[Exception],
) -> None:
    caplog.set_level(logging.DEBUG)
    recorder = Recorder(responses)
    with build(recorder) as client, pytest.raises(expected) as excinfo:
        client.query("query { viewer { login } }")
    assert_no_secret(caplog, str(excinfo.value))


def test_the_token_is_redacted_even_if_a_server_echoes_it() -> None:
    recorder = Recorder([response(404, {"echo": f"bad token {SECRET}"})])
    with build(recorder) as client, pytest.raises(GitHubProtocolError) as excinfo:
        client.query("query { viewer { login } }")
    assert SECRET not in str(excinfo.value)
    assert "***" in str(excinfo.value)


def test_the_token_is_sent_in_the_authorization_header_and_nowhere_else() -> None:
    recorder = Recorder([response()])
    with build(recorder) as client:
        client.query("query { viewer { login } }")
    sent = json.dumps(dict(recorder.requests[0].headers))
    assert f"bearer {SECRET}" in sent
    assert SECRET in sent
    assert SECRET not in recorder.requests[0].content.decode()


def test_client_repr_does_not_leak_the_token() -> None:
    recorder = Recorder([response()])
    client = build(recorder)
    assert SECRET not in repr(client)
    client.close()


@pytest.mark.live
def test_live_query_reaches_github() -> None:
    import os

    if os.environ.get("RUN_LIVE") != "1":
        pytest.skip("set RUN_LIVE=1 to hit the real GitHub API")
    from app.config import settings as global_settings

    global_settings.require_github()
    with GitHubGraphQLClient(global_settings) as client:
        payload = client.query("query { rateLimit { cost remaining } }")
    assert payload["data"]["rateLimit"]["remaining"] >= 0