"""Answer-time quote integrity.

A quote must be re-verified against its source text when the answer is built. A
stored ``quote_verified`` flag is a record of what was true at extraction time; it
is not authorisation to repeat the claim.
"""

from __future__ import annotations

import json
from typing import Optional

import pytest

from app.schemas.common import Outcome
from app.services import answer as answer_module
from app.services.answer import generate_answer
from app.services.entity_resolution import resolve_entity
from app.services.retrieval import EvidenceBundle, RetrievedEvidenceItem

REPO = "acme/netclient"
QUESTION = "Why is MAX_RETRIES 3?"

# The real pull request body. Only this text is evidence.
REAL_PR_BODY = (
    "We raised MAX_RETRIES to 3 because the mobile clients kept timing out on "
    "flaky cellular networks in the field."
)

# The quote an attacker, or a bad extraction, would like us to believe.
FABRICATED_QUOTE = "MAX_RETRIES is 9 because the CEO demanded it for the quarterly demo."
GENUINE_QUOTE = "mobile clients kept timing out on flaky cellular networks"

ENTITIES = [{"id": "e1", "name": "MAX_RETRIES", "path": "pkg/config.py", "entity_type": "ConfigKey"}]


class RecordingProvider:
    """A well-behaved mock LLM that records whether it was reached at all."""

    def __init__(self, answer: str = "raised to 3 for flaky networks") -> None:
        from app.providers.llm_provider import MockLLMProvider

        self.calls = 0
        self._inner = MockLLMProvider(
            canned_response=json.dumps({"answer": answer, "cited_evidence_ids": ["ev1"]})
        )

    def complete_structured(self, schema, prompt, system=None, **kwargs):  # noqa: ANN001
        self.calls += 1
        return self._inner.complete_structured(schema=schema, prompt=prompt, system=system, **kwargs)


def build_bundle(
    quote: str, *, source_text: Optional[str], stale_flag: bool = True
) -> EvidenceBundle:
    texts = {f"pr:{REPO}#7": source_text} if source_text is not None else {}
    return EvidenceBundle(
        question=QUESTION,
        resolved_entity=ENTITIES[0],
        decisions=[
            {
                "id": "d1",
                "repo": REPO,
                "summary": "Raised the retry cap",
                "rationale": "mobile clients kept timing out",
                "state": "ACTIVE",
            }
        ],
        evidence_items=[
            RetrievedEvidenceItem(
                id="ev1",
                decision_id="d1",
                source_id=f"pr:{REPO}#7",
                source_type="pull_request",
                source_url=f"https://github.com/{REPO}/pull/7",
                quote=quote,
                claim="timeout raised",
                author="real-reviewer",
                timestamp="2025-01-01T00:00:00Z",
                quote_verified=stale_flag,
                similarity_score=0.95,
            )
        ],
        best_similarity_score=0.95,
        source_texts=texts,
    )


@pytest.fixture(autouse=True)
def _low_gate_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(answer_module.settings, "min_score", 0.5)


def test_a_fabricated_quote_is_not_returned_as_a_citation() -> None:
    """The core regression: a stale quote_verified=True must not authorise a lie."""
    resolution = resolve_entity(QUESTION, ENTITIES)
    assert resolution.entity is not None

    bundle = build_bundle(FABRICATED_QUOTE, source_text=REAL_PR_BODY)
    provider = RecordingProvider()

    response = generate_answer(
        question=QUESTION,
        resolution=resolution,
        bundle=bundle,
        provider=provider,
    )

    assert response.outcome is not Outcome.FULL, (
        "a quote absent from its source must never produce a full answer"
    )
    assert response.citations == []
    assert FABRICATED_QUOTE not in json.dumps(
        response.model_dump(mode="json"), default=str
    ), "the fabricated quote must not appear anywhere in the response"
    assert provider.calls == 0, "the LLM must not run when no quote survives verification"


def test_a_fabricated_quote_is_reported_as_no_verified_quote() -> None:
    resolution = resolve_entity(QUESTION, ENTITIES)
    bundle = build_bundle(FABRICATED_QUOTE, source_text=REAL_PR_BODY)
    provider = RecordingProvider()

    response = generate_answer(
        question=QUESTION,
        resolution=resolution,
        bundle=bundle,
        provider=provider,
    )

    assert response.outcome is Outcome.PARTIAL
    assert response.reason_code == "no_verified_quote"
    assert provider.calls == 0


def test_a_genuine_quote_is_still_cited() -> None:
    """The guarantee must not be so blunt that real evidence stops working."""
    resolution = resolve_entity(QUESTION, ENTITIES)
    bundle = build_bundle(GENUINE_QUOTE, source_text=REAL_PR_BODY)
    provider = RecordingProvider()

    response = generate_answer(
        question=QUESTION,
        resolution=resolution,
        bundle=bundle,
        provider=provider,
    )

    assert provider.calls == 1
    assert response.outcome is Outcome.FULL
    assert [c.quote for c in response.citations] == [GENUINE_QUOTE]


def test_missing_source_text_does_not_authorise_the_stale_flag() -> None:
    """If the source cannot be loaded the quote cannot be verified, so it is dropped."""
    resolution = resolve_entity(QUESTION, ENTITIES)
    bundle = build_bundle(FABRICATED_QUOTE, source_text=None, stale_flag=True)
    provider = RecordingProvider()

    response = generate_answer(
        question=QUESTION,
        resolution=resolution,
        bundle=bundle,
        provider=provider,
    )

    assert response.citations == []
    assert response.outcome is not Outcome.FULL
    assert provider.calls == 0


def test_verify_quote_runs_once_per_candidate_citation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolution = resolve_entity(QUESTION, ENTITIES)
    bundle = build_bundle(FABRICATED_QUOTE, source_text=REAL_PR_BODY)

    calls: list[tuple] = []
    original = answer_module.verify_quote

    def spy(quote: str, source_text: str):  # noqa: ANN001
        calls.append((quote, source_text))
        return original(quote, source_text)

    monkeypatch.setattr(answer_module, "verify_quote", spy)

    generate_answer(
        question=QUESTION,
        resolution=resolution,
        bundle=bundle,
        provider=RecordingProvider(),
    )

    assert len(calls) == 1, f"expected one verification per candidate citation, got {len(calls)}"
    assert calls[0][0] == FABRICATED_QUOTE
    assert REAL_PR_BODY in calls[0][1]


def test_a_tampered_flag_never_bypasses_the_check() -> None:
    """Flipping quote_verified in either direction must not change the outcome."""
    resolution = resolve_entity(QUESTION, ENTITIES)
    provider = RecordingProvider()

    flagged = generate_answer(
        question=QUESTION,
        resolution=resolution,
        bundle=build_bundle(FABRICATED_QUOTE, source_text=REAL_PR_BODY, stale_flag=True),
        provider=provider,
    )
    unflagged = generate_answer(
        question=QUESTION,
        resolution=resolution,
        bundle=build_bundle(FABRICATED_QUOTE, source_text=REAL_PR_BODY, stale_flag=False),
        provider=provider,
    )

    assert flagged.citations == unflagged.citations == []
    assert flagged.outcome is unflagged.outcome
