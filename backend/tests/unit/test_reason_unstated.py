"""A decision that says what happened but not why must be marked as such.

The #1429 extraction produced a verified quote that read "Requests and pip have
already dropped Python 2.6." That is a fact, not a reason. Storing it as the
supporting evidence for "Drop support for Python 2.6" is circular: the quote
restates the summary, so the reader learns nothing about the motivation.

The prompt now asks for the reason explicitly, and a decision whose evidence
carries no reason is marked `reason_unstated` rather than being presented as
explained. `verify_quote` is untouched and nothing is loosened.
"""

from __future__ import annotations

import json

import pytest

from app.services.extraction import (
    LLMExtractionPayload,
    extract_decisions_from_source,
)
from app.providers.llm_provider import MockLLMProvider

BODY = (
    "Requests and pip have already dropped Python 2.6.\n"
    "We removed the last 2.6-only branch so the codebase reads the same as pip."
)

SOURCE = {
    "source_id": "pr:urllib3/urllib3#1429",
    "source_type": "pr",
    "source_url": "https://github.com/urllib3/urllib3/pull/1429",
    "repo": "urllib3/urllib3",
    "title": "Drop support for Python 2.6",
    "body": BODY,
}

#: A quote that only restates what changed.
ACTION_ONLY_QUOTE = "Requests and pip have already dropped Python 2.6."

#: A quote that states the reason.
REASON_QUOTE = "We removed the last 2.6-only branch so the codebase reads the same as pip."


def reply(rationale: str | None, quote: str) -> str:
    decision: dict = {
        "summary": "Drop support for Python 2.6",
        "decision_type": "Compatibility",
        "supporting_evidence": [{"quote": quote, "claim": "c"}],
    }
    if rationale is not None:
        decision["rationale"] = rationale
    return json.dumps({"decisions": [decision]})


def extract(quote: str, rationale: str | None):
    provider = MockLLMProvider(canned_response=reply(rationale, quote))
    return extract_decisions_from_source(provider=provider, **SOURCE)[0]


# --- the prompt -------------------------------------------------------------


def test_the_prompt_asks_for_the_reason() -> None:
    from app.prompts.extract_decision import build_extraction_prompt

    _, prompt = build_extraction_prompt(
        source_type="pr", source_id="pr:acme/widget#1", title="t", body="b",
    )
    lowered = prompt.lower()
    assert "rationale" in lowered
    assert "why" in lowered
    assert "one or two sentences" in lowered


def test_the_prompt_requires_a_complete_sentence_as_the_quote() -> None:
    from app.prompts.extract_decision import build_extraction_prompt

    _, prompt = build_extraction_prompt(
        source_type="pr", source_id="pr:acme/widget#1", title="t", body="b",
    )
    lowered = prompt.lower()
    assert "complete sentence" in lowered or "whole sentence" in lowered
    assert "mid-sentence" in lowered or "middle of a sentence" in lowered


def test_the_prompt_example_carries_a_rationale() -> None:
    from app.prompts.extract_decision import EXAMPLE_REPLY

    assert EXAMPLE_REPLY["decisions"][0].get("rationale"), (
        "the worked example must show a rationale, or the model copies its absence"
    )


# --- the flag ---------------------------------------------------------------


def test_a_decision_without_a_rationale_is_marked_reason_unstated() -> None:
    record = extract(ACTION_ONLY_QUOTE, rationale=None)

    assert record.reason_unstated is True


def test_an_empty_rationale_is_also_reason_unstated() -> None:
    record = extract(ACTION_ONLY_QUOTE, rationale="   ")

    assert record.reason_unstated is True


def test_a_decision_with_a_rationale_is_not_marked() -> None:
    record = extract(
        REASON_QUOTE,
        rationale="Pip and Requests already dropped Python 2.6, so the branch was dead weight.",
    )

    assert record.reason_unstated is False
    assert record.rationale


def test_the_rationale_is_kept_verbatim() -> None:
    record = extract(REASON_QUOTE, rationale="Pip already dropped 2.6.")

    assert record.rationale == "Pip already dropped 2.6."


def test_the_reason_unstated_flag_does_not_disturb_quote_verification() -> None:
    """The quote still verifies; the flag is about the why, not the match."""
    record = extract(ACTION_ONLY_QUOTE, rationale=None)

    assert record.quote_verified is True
    assert record.evidence[0].quote_verified is True
    assert record.evidence[0].quote == ACTION_ONLY_QUOTE


def test_the_flag_is_absent_from_the_prompt_schema_by_default() -> None:
    """The model is asked for a rationale; the flag is decided in code."""
    payload = LLMExtractionPayload.model_validate({"decisions": []})

    assert payload.decisions == []
    assert not hasattr(payload, "reason_unstated")


def test_the_flag_survives_into_the_cache() -> None:
    """A decision that records no reason must say so at rest, not only in memory."""
    import tempfile
    from pathlib import Path

    from app.stores.sqlite_cache import SqliteCache

    record = extract(ACTION_ONLY_QUOTE, rationale=None)

    with tempfile.TemporaryDirectory() as tmp:
        with SqliteCache(Path(tmp) / "c.sqlite3") as cache:
            cache.put_decision({
                "id": record.id, "source_id": record.source_id, "repo": record.repo,
                "summary": record.summary, "decision_type": record.decision_type,
                "rationale": record.rationale, "state": record.state.value,
                "alternatives_considered": [], "constraints": [],
                "affected_entities": [], "source_references": [],
                "decision_date": None, "source_author": None,
                "explicit_reversal_language": False, "unknown_fields": [],
                "quote_verified": record.quote_verified,
                "reason_unstated": record.reason_unstated,
                "extraction_version": record.extraction_version,
                "content_hash": record.content_hash, "created_at": "",
            })
            stored = cache.decision_by_id(record.id)

    assert stored["reason_unstated"] == 1


def test_a_decision_with_a_reason_stores_zero() -> None:
    import tempfile
    from pathlib import Path

    from app.stores.sqlite_cache import SqliteCache

    record = extract(REASON_QUOTE, rationale="Pip already dropped 2.6.")

    with tempfile.TemporaryDirectory() as tmp:
        with SqliteCache(Path(tmp) / "c.sqlite3") as cache:
            cache.put_decision({
                "id": record.id, "source_id": record.source_id, "repo": record.repo,
                "summary": record.summary, "decision_type": record.decision_type,
                "rationale": record.rationale, "state": record.state.value,
                "alternatives_considered": [], "constraints": [],
                "affected_entities": [], "source_references": [],
                "decision_date": None, "source_author": None,
                "explicit_reversal_language": False, "unknown_fields": [],
                "quote_verified": record.quote_verified,
                "reason_unstated": record.reason_unstated,
                "extraction_version": record.extraction_version,
                "content_hash": record.content_hash, "created_at": "",
            })
            stored = cache.decision_by_id(record.id)

    assert stored["reason_unstated"] == 0