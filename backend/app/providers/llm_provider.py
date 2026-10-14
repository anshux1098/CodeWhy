from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Final, Optional, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings, settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LLMProviderError(RuntimeError):
    """Base error for LLM provider operations."""
    pass


class TokenBudgetExhaustedError(LLMProviderError):
    """Raised when an LLM operation would exceed or exceeds the allotted token budget."""

    def __init__(self, limit: int, used: int, requested: int = 0):
        super().__init__(
            f"LLM token budget exhausted: limit={limit}, used={used}, "
            f"requested={requested}. Stopping run."
        )
        self.limit = limit
        self.used = used
        self.requested = requested


class LLMTimeoutError(LLMProviderError):
    """Raised when an LLM call exceeds the configured timeout."""
    pass


class LLMSchemaValidationError(LLMProviderError):
    """Raised when an LLM response fails validation against the expected Pydantic schema."""

    def __init__(self, raw_content: str, errors: Any):
        super().__init__(f"LLM output failed Pydantic schema validation: {errors}")
        self.raw_content = raw_content
        self.validation_errors = errors


class LLMNonRetryableError(LLMProviderError):
    """Raised for a status that must not be retried.

    The retry loop catches every other exception to try again, so this type exists
    purely to escape that loop: a 400, 401, 403 or 404 fails the same way every
    time, and repeating the call only turns a clear error into a slow one.
    """

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Token Budget Guard
# ---------------------------------------------------------------------------

@dataclass
class TokenBudget:
    """Tracks token consumption for an execution run and enforces MAX_LLM_TOKENS_PER_RUN."""

    max_tokens: int = field(default_factory=lambda: settings.max_llm_tokens_per_run)
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def remaining(self) -> int:
        return max(0, self.max_tokens - self.total_tokens)

    @property
    def is_exhausted(self) -> bool:
        return self.total_tokens >= self.max_tokens

    def can_afford(self, estimated_tokens: int = 0) -> bool:
        """Returns True if the budget has room for estimated_tokens."""
        return (self.total_tokens + estimated_tokens) <= self.max_tokens

    def consume(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Records token usage and raises TokenBudgetExhaustedError if the limit is exceeded."""
        requested = prompt_tokens + completion_tokens
        if self.total_tokens + requested > self.max_tokens:
            used_before = self.total_tokens
            # Still record what we tried to consume for auditability
            self.prompt_tokens += prompt_tokens
            self.completion_tokens += completion_tokens
            raise TokenBudgetExhaustedError(
                limit=self.max_tokens,
                used=self.total_tokens,
                requested=requested,
            )
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens

    def summary(self) -> dict[str, Any]:
        return {
            "max_tokens": self.max_tokens,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "remaining": self.remaining,
            "exhausted": self.is_exhausted,
        }


# ---------------------------------------------------------------------------
# Response Model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LLMResponse:
    """Encapsulates the text completion, token metrics, and metadata."""

    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: str
    status_code: int = 200
    #: True only when the server actually reported usage. Estimated fallback values
    #: never count as reported.
    usage_reported: bool = False
    raw_response: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------

#: Transient upstream conditions. A provider overloaded or briefly down answers with
#: one of these, and the same request usually succeeds later, so they are retried.
RETRYABLE_STATUSES: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})

#: Client-side mistakes. Retrying cannot change the answer: the request, the
#: credentials or the model name is wrong, so the call fails immediately and the
#: message is surfaced instead of being buried under minutes of waiting.
NON_RETRYABLE_STATUSES: Final[frozenset[int]] = frozenset({400, 401, 403, 404})

#: One wait after each retry, so six retries use six different pauses. The last two
#: are equal on purpose: a long outage needs patience, not a growing delay.
RETRY_BACKOFF_SECONDS: Final[tuple[int, ...]] = (5, 15, 30, 60, 120, 120)

#: Attempts allowed per call: the first try plus one per backoff step.
MAX_ATTEMPTS: Final[int] = len(RETRY_BACKOFF_SECONDS) + 1


def _retry_after_seconds(response: httpx.Response) -> Optional[float]:
    """Seconds the server asked us to wait, from its Retry-After header.

    Only the delta-seconds form is honoured; an HTTP-date is ignored rather than
    guessed at, because the request is about to be sent anyway and a wrong delay
    is worse than the default schedule.
    """
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        value = float(raw.strip())
    except ValueError:
        return None
    return value if value >= 0 else None


# ---------------------------------------------------------------------------
# Abstract LLM Provider
# ---------------------------------------------------------------------------

class BaseLLMProvider(ABC):
    #: True only for a provider that calls a real model. A mock must keep this
    #: False so any response built with it can declare itself a fixture.
    is_real: bool = True

    """Abstract interface for LLM providers."""

    def __init__(
        self,
        budget: Optional[TokenBudget] = None,
        timeout_s: Optional[int] = None,
        max_retries: int = MAX_ATTEMPTS,
    ) -> None:
        self.budget = budget or TokenBudget()
        self.timeout_s = timeout_s if timeout_s is not None else settings.llm_timeout_s
        self.max_retries = max_retries

    @abstractmethod
    def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """Execute a text completion, tracking token budget and retries."""
        ...

    def complete_structured(
        self,
        schema: type[T],
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> tuple[T, LLMResponse]:
        """Calls the LLM expecting JSON output, parses it, and validates against a Pydantic model.

        Extracts JSON from markdown fences if the model wraps it in ```json ... ```.
        """
        response = self.complete(
            prompt=prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        raw = response.content.strip()
        # Strip potential markdown fences
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
        json_str = fence_match.group(1).strip() if fence_match else raw

        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise LLMSchemaValidationError(
                raw_content=raw,
                errors=f"JSON parsing error: {exc}",
            ) from exc

        try:
            validated = schema.model_validate(parsed)
            return validated, response
        except ValidationError as exc:
            raise LLMSchemaValidationError(
                raw_content=raw,
                errors=exc.errors(),
            ) from exc


# ---------------------------------------------------------------------------
# Mock / Local LLM Provider (for tests and offline local runs)
# ---------------------------------------------------------------------------

def _redact(value: object) -> str:
    """Never let a credential reach an error message."""
    text = str(value)
    for secret in (settings.llm_api_key, settings.github_token, settings.neo4j_password):
        if secret and len(secret) >= 8 and secret in text:
            text = text.replace(secret, "<redacted>")
    return text


def _safe_error_body(response: httpx.Response, limit: int = 400) -> str:
    """A short excerpt of an error body, with anything that looks like a key removed."""
    try:
        body = response.text
    except Exception:  # noqa: BLE001
        return "<no body>"
    body = " ".join(body.split())[:limit]
    return _redact(body) or "<empty body>"


class MockLLMProvider(BaseLLMProvider):
    is_real: bool = False

    """Mock provider with canned responses, customizable completion handler, and token tracking."""

    def __init__(
        self,
        canned_response: Optional[str] = None,
        response_factory: Optional[Callable[[str, Optional[str]], str]] = None,
        budget: Optional[TokenBudget] = None,
        timeout_s: Optional[int] = None,
        tokens_per_call: int = 150,
    ) -> None:
        super().__init__(budget=budget, timeout_s=timeout_s)
        self.canned_response = canned_response or "{}"
        self.response_factory = response_factory
        self.tokens_per_call = tokens_per_call
        self.call_history: list[dict[str, Any]] = []

    def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        self.call_history.append({"prompt": prompt, "system": system})

        # Calculate mock token usage: approx 1 token per 4 chars for prompt, fixed or ratio for output
        prompt_toks = max(1, len(prompt) // 4)
        if self.response_factory:
            content = self.response_factory(prompt, system)
        else:
            content = self.canned_response
        completion_toks = max(1, len(content) // 4)

        # Enforce budget guard
        self.budget.consume(prompt_toks, completion_toks)

        return LLMResponse(
            content=content,
            prompt_tokens=prompt_toks,
            completion_tokens=completion_toks,
            total_tokens=prompt_toks + completion_toks,
            model="mock-model",
            status_code=200,
            usage_reported=True,
            raw_response={"mock": True},
        )


# ---------------------------------------------------------------------------
# OpenAI-Compatible Provider (HTTP REST)
# ---------------------------------------------------------------------------

class OpenAICompatibleProvider(BaseLLMProvider):
    """Calls any OpenAI-compatible API (OpenAI, Ollama, vLLM, OpenRouter, Groq)."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        budget: Optional[TokenBudget] = None,
        timeout_s: Optional[int] = None,
        max_retries: int = MAX_ATTEMPTS,
    ) -> None:
        super().__init__(budget=budget, timeout_s=timeout_s, max_retries=max_retries)
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        # Check budget before dispatching call
        if not self.budget.can_afford():
            raise TokenBudgetExhaustedError(
                limit=self.budget.max_tokens,
                used=self.budget.total_tokens,
            )

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        url = f"{self.base_url}/chat/completions"
        last_error: Optional[Exception] = None
        last_status: Optional[int] = None

        for attempt in range(self.max_retries):
            try:
                with httpx.Client(timeout=float(self.timeout_s)) as client:
                    resp = client.post(url, json=payload, headers=headers)

                last_status = resp.status_code
                if resp.status_code in RETRYABLE_STATUSES:
                    # Remember why, so a retry loop that never succeeds can still say
                    # what the service actually answered.
                    last_error = LLMProviderError(
                        f"HTTP {resp.status_code}: {_safe_error_body(resp)}"
                    )
                    # The last attempt has nothing left to wait for.
                    if attempt < self.max_retries - 1:
                        scheduled = (
                            RETRY_BACKOFF_SECONDS[attempt]
                            if attempt < len(RETRY_BACKOFF_SECONDS)
                            else RETRY_BACKOFF_SECONDS[-1]
                        )
                        wait_time = _retry_after_seconds(resp)
                        source = "Retry-After"
                        if wait_time is None:
                            wait_time = float(scheduled)
                            source = "schedule"
                        logger.info(
                            "LLM attempt %d/%d got HTTP %d; retrying in %ss (%s)",
                            attempt + 1, self.max_retries, resp.status_code, wait_time, source,
                        )
                        time.sleep(wait_time)
                    continue

                if resp.status_code in NON_RETRYABLE_STATUSES:
                    logger.info(
                        "LLM attempt %d/%d got HTTP %d; not retrying",
                        attempt + 1, self.max_retries, resp.status_code,
                    )
                    raise LLMNonRetryableError(
                        f"HTTP {resp.status_code}: {_safe_error_body(resp)}",
                        status_code=resp.status_code,
                    )

                if resp.status_code >= 400:
                    raise LLMNonRetryableError(
                        f"HTTP {resp.status_code}: {_safe_error_body(resp)}",
                        status_code=resp.status_code,
                    )

                logger.info(
                    "LLM attempt %d/%d got HTTP %d", attempt + 1, self.max_retries, resp.status_code
                )
                resp.raise_for_status()
                data = resp.json()

                choices = data.get("choices", [])
                if not choices:
                    raise LLMProviderError("Empty choices received from OpenAI API")

                content = choices[0].get("message", {}).get("content", "")

                usage = data.get("usage")
                usage_reported = isinstance(usage, dict)
                if usage_reported:
                    prompt_toks = int(usage.get("prompt_tokens", len(prompt) // 4))
                    comp_toks = int(usage.get("completion_tokens", len(content) // 4))
                else:
                    # The server gave no usage; keep an estimate for budget tracking only.
                    prompt_toks = max(1, len(prompt) // 4)
                    comp_toks = max(1, len(content) // 4)

                # Track budget
                self.budget.consume(prompt_toks, comp_toks)

                return LLMResponse(
                    content=content,
                    prompt_tokens=prompt_toks,
                    completion_tokens=comp_toks,
                    total_tokens=prompt_toks + comp_toks,
                    model=self.model,
                    status_code=resp.status_code,
                    usage_reported=usage_reported,
                    raw_response=data,
                )
            except LLMNonRetryableError:
                # A status that must not be retried: leave the loop immediately.
                raise
            except httpx.TimeoutException as exc:
                last_error = LLMTimeoutError(f"OpenAI call timed out after {self.timeout_s}s: {exc}")
            except Exception as exc:
                last_error = exc

        status_note = f" (last HTTP status {last_status})" if last_status else ""
        raise LLMProviderError(
            f"LLM request failed after {self.max_retries} attempts{status_note}: "
            f"{_redact(last_error)}"
        )


# ---------------------------------------------------------------------------
#: Default endpoint per provider. An explicit LLM_BASE_URL always wins, so a key
#: is only ever sent to the host an operator configured. Google exposes an
#: OpenAI-compatible surface for Gemini, which is why it uses this client.
PROVIDER_BASE_URLS: Final[dict[str, str]] = {
    "openai": "https://api.openai.com/v1",
    "ollama": "http://localhost:11434/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "vllm": "http://localhost:8000/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


#: Names that resolve to the offline mock. Listed in errors so the message is complete.
MOCK_PROVIDER_NAMES: Final[frozenset[str]] = frozenset({"mock", "fixture", "test"})


# Factory
# ---------------------------------------------------------------------------

def get_llm_provider(
    provider_name: Optional[str] = None,
    budget: Optional[TokenBudget] = None,
    mock_canned_response: Optional[str] = None,
    cfg: Optional[Settings] = None,
) -> BaseLLMProvider:
    """Factory selecting the provider implementation.

    `cfg` is the caller's Settings. It is required for anything but the mock
    provider, because reading the module-level global would make every caller
    depend on whatever the operator happens to have in their .env, and would make
    unit tests impossible to isolate.
    """
    config = cfg or settings
    name = (provider_name or config.llm_provider or "mock").strip().lower()

    if name in MOCK_PROVIDER_NAMES:
        return MockLLMProvider(canned_response=mock_canned_response, budget=budget)

    if name in PROVIDER_BASE_URLS:
        config.require_llm()
        base_url = (config.llm_base_url or "").strip() or PROVIDER_BASE_URLS[name]
        return OpenAICompatibleProvider(
            api_key=config.llm_api_key,
            model=config.llm_model,
            base_url=base_url,
            budget=budget,
        )

    supported = sorted(set(PROVIDER_BASE_URLS) | MOCK_PROVIDER_NAMES)
    raise ValueError(
        f"Unsupported LLM provider: {name!r}. Supported: {', '.join(supported)}"
    )
