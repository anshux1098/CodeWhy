from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

import httpx

from app.config import Settings

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
GITHUB_GRAPHQL_HOST = "api.github.com"
GITHUB_GRAPHQL_PATH = "/graphql"

LOW_REMAINING_THRESHOLD = 50
MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_CAP_SECONDS = 30.0
USER_AGENT = "codewhy-prototype"

REDACTED = "***"


class GitHubError(RuntimeError):
    pass


class GitHubAuthError(GitHubError):
    pass


class GitHubRetryExhaustedError(GitHubError):
    pass


class GitHubProtocolError(GitHubError):
    pass


@dataclass(frozen=True)
class RateLimitSnapshot:
    cost: int
    limit: int
    remaining: int
    reset_at: Optional[datetime]

    def is_low(self) -> bool:
        return self.remaining < LOW_REMAINING_THRESHOLD

    def describe(self) -> str:
        return f"cost={self.cost} remaining={self.remaining}/{self.limit}"


def assert_canonical_graphql_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != GITHUB_GRAPHQL_HOST or parts.path != GITHUB_GRAPHQL_PATH:
        raise GitHubProtocolError(
            f"refusing non-canonical GitHub GraphQL endpoint {url!r}; "
            f"only {GITHUB_GRAPHQL_URL} is allowed"
        )


def backoff_seconds(attempt: int, rng: Callable[[], float]) -> float:
    ceiling = min(BACKOFF_BASE_SECONDS * (2**attempt), BACKOFF_CAP_SECONDS)
    return ceiling * (0.5 + 0.5 * rng())


class GitHubGraphQLClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: Callable[[], float] = random.random,
    ) -> None:
        settings.require_github()
        assert_canonical_graphql_url(GITHUB_GRAPHQL_URL)
        self._token = settings.github_token
        self._sleep = sleep
        self._rng = rng
        self._rate_limit: Optional[RateLimitSnapshot] = None
        self._client = httpx.Client(
            timeout=settings.github_timeout_s,
            follow_redirects=False,
            transport=transport,
            headers={
                "Authorization": f"bearer {self._token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )

    @property
    def rate_limit(self) -> Optional[RateLimitSnapshot]:
        return self._rate_limit

    def query(self, document: str, variables: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"query": document}
        if variables:
            payload["variables"] = variables
        last_failure = "no attempt was made"
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self._client.post(GITHUB_GRAPHQL_URL, json=payload)
            except httpx.TransportError as exc:
                last_failure = self._redact(f"transport error: {exc.__class__.__name__}")
                self._pause_unless_last(attempt)
                continue
            snapshot = self._read_rate_limit(response)
            if snapshot is not None:
                self._rate_limit = snapshot
            if response.status_code in {401, 403} and not self._looks_rate_limited(response, snapshot):
                raise GitHubAuthError(
                    self._redact(
                        f"GitHub rejected the credentials with HTTP {response.status_code}; "
                        "check that GITHUB_TOKEN is valid and not expired"
                    )
                )
            if self._is_retryable(response.status_code):
                last_failure = self._redact(f"HTTP {response.status_code}")
                self._pause_unless_last(attempt)
                continue
            if 300 <= response.status_code < 400:
                location = response.headers.get("location", "")
                target = urlsplit(location).hostname or "unknown host"
                raise GitHubProtocolError(
                    f"refusing to follow a redirect from api.github.com to {target}; "
                    "the client never leaves the canonical GraphQL host"
                )
            if response.status_code >= 400:
                raise GitHubProtocolError(
                    self._redact(f"unexpected HTTP {response.status_code}: {self._body_summary(response)}")
                )
            try:
                parsed = response.json()
            except ValueError:
                raise GitHubProtocolError("GitHub returned a response that is not valid JSON")
            if isinstance(parsed, dict) and parsed.get("errors"):
                messages = "; ".join(str(error.get("message", "")) for error in parsed["errors"])
                raise GitHubProtocolError(self._redact(f"GraphQL errors: {messages}"))
            return parsed
        raise GitHubRetryExhaustedError(
            f"giving up after {MAX_ATTEMPTS} attempts; last failure was {last_failure}"
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GitHubGraphQLClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _pause(self, attempt: int) -> None:
        self._sleep(backoff_seconds(attempt, self._rng))

    def _pause_unless_last(self, attempt: int) -> None:
        if attempt < MAX_ATTEMPTS - 1:
            self._pause(attempt)

    def _is_retryable(self, status_code: int) -> bool:
        return status_code >= 500 or status_code == 429 or status_code == 403

    def _looks_rate_limited(self, response: httpx.Response, snapshot: Optional[RateLimitSnapshot]) -> bool:
        if response.headers.get("x-ratelimit-remaining") == "0":
            return True
        return snapshot is not None and snapshot.remaining == 0

    def _read_rate_limit(self, response: httpx.Response) -> Optional[RateLimitSnapshot]:
        try:
            parsed = response.json()
        except ValueError:
            return None
        if not isinstance(parsed, dict):
            return None
        node = ((parsed.get("data") or {}) if isinstance(parsed.get("data"), dict) else {}).get("rateLimit")
        if not isinstance(node, dict):
            return None
        reset_at = None
        if isinstance(node.get("resetAt"), str):
            try:
                reset_at = datetime.fromisoformat(node["resetAt"].replace("Z", "+00:00"))
            except ValueError:
                reset_at = None
        return RateLimitSnapshot(
            cost=int(node.get("cost") or 0),
            limit=int(node.get("limit") or 0),
            remaining=int(node.get("remaining") or 0),
            reset_at=reset_at,
        )

    def _body_summary(self, response: httpx.Response) -> str:
        text = response.text.strip()
        return text[:200] if text else "<empty body>"

    def _redact(self, text: str) -> str:
        return text.replace(self._token, REDACTED) if self._token else text