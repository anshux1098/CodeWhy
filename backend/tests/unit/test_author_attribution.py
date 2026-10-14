"""Author attribution comes from the source, never from the model.

An author is a factual claim about a person. Letting the model write one means a
hostile pull request can make the system attribute a quote to whoever it likes.
"""

from __future__ import annotations

import json
import re

import pytest

from app.providers.llm_provider import MockLLMProvider
from app.services.extraction import RawEvidenceItem, extract_decisions_from_source

REPO = "acme/netclient"
BODY = "Increase the timeout to 30s because upstream services were slow."

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def llm_returning(evidence: list[dict]) -> MockLLMProvider:
    payload = {
        "no_decision": False,
        "decisions": [
            {
                "summary": "Raised connect timeout",
                "decision_type": "Other",
                "rationale": "upstream was slow",
                "supporting_evidence": evidence,
                "opposing_evidence": [],
                "explicit_reversal_language": False,
                "unknown_fields": [],
            }
        ],
    }
    return MockLLMProvider(canned_response=json.dumps(payload))


def extract(provider: MockLLMProvider, *, author: str) -> list:
    return extract_decisions_from_source(
        provider=provider,
        source_type="pull_request",
        source_id="pr_99",
        repo=REPO,
        title="Raise timeout",
        body=BODY,
        diff_or_patch=None,
        comments=[],
        changed_files=["pkg/http.py"],
        config_keys=[],
        author=author,
        created_at="2026-01-01T00:00:00Z",
        source_url=f"https://github.com/{REPO}/pull/99",
        extraction_version="v1",
    )


def test_the_model_cannot_supply_an_author() -> None:
    """The schema itself must not accept an author from the model."""
    assert "author" not in RawEvidenceItem.model_fields, (
        "RawEvidenceItem still accepts an author from the model"
    )


def test_an_invented_author_is_ignored_and_the_real_author_is_kept() -> None:
    provider = llm_returning(
        [
            {
                "quote": "Increase the timeout to 30s because upstream services were slow.",
                "claim": "timeout raised",
                "author": "Totally Not An Author <attacker@evil.example>",
                "timestamp": "2026-01-01T00:00:00Z",
            }
        ]
    )
    records = extract(provider, author="real-reviewer")
    assert records, "extraction should still succeed"

    stored_authors = {ev.author for rec in records for ev in rec.evidence}
    assert stored_authors == {"real-reviewer"}
    assert "attacker@evil.example" not in json.dumps(
        [r.__dict__ for r in records], default=str
    )


def test_no_email_shaped_value_reaches_any_author_field() -> None:
    provider = llm_returning(
        [
            {
                "quote": "Increase the timeout to 30s because upstream services were slow.",
                "claim": "timeout raised",
                "author": "someone@evil.example",
                "timestamp": "2026-01-01T00:00:00Z",
            }
        ]
    )
    records = extract(provider, author="real-reviewer")
    for record in records:
        for value in (record.source_author, *(ev.author for ev in record.evidence)):
            if value:
                assert not EMAIL.search(value), f"email-shaped author survived: {value!r}"


def test_a_missing_author_is_left_absent_rather_than_invented() -> None:
    provider = llm_returning(
        [
            {
                "quote": "Increase the timeout to 30s because upstream services were slow.",
                "claim": "timeout raised",
            }
        ]
    )
    records = extract(provider, author="real-reviewer")
    assert {ev.author for rec in records for ev in rec.evidence} == {"real-reviewer"}


def test_the_quote_itself_is_never_redacted() -> None:
    """A quote must stay a verbatim substring of its source, so no redaction
    happens inside quote or claim."""
    provider = llm_returning(
        [
            {
                "quote": "Increase the timeout to 30s because upstream services were slow.",
                "claim": "Signed-off-by: Jo Example <jo@example.com>",
            }
        ]
    )
    records = extract(provider, author="real-reviewer")
    quotes = [ev.quote for rec in records for ev in rec.evidence]
    assert quotes, "the verified quote should be kept"
    for quote in quotes:
        assert quote in BODY, "a quote must remain a verbatim substring of its source"


def test_source_author_itself_is_not_email_shaped() -> None:
    """If the ingested record itself carried an address it must not be stored."""
    provider = llm_returning(
        [
            {
                "quote": "Increase the timeout to 30s because upstream services were slow.",
                "claim": "timeout raised",
            }
        ]
    )
    records = extract(provider, author="maintainer@example.com")
    for record in records:
        assert not EMAIL.search(record.source_author or "")
        for ev in record.evidence:
            assert not EMAIL.search(ev.author or "")


@pytest.mark.parametrize("payload_field", ["author"])
def test_unknown_fields_in_evidence_are_ignored(payload_field: str) -> None:
    provider = llm_returning(
        [
            {
                "quote": "Increase the timeout to 30s because upstream services were slow.",
                "claim": "timeout raised",
                payload_field: "Someone Else",
            }
        ]
    )
    records = extract(provider, author="real-reviewer")
    for rec in records:
        for ev in rec.evidence:
            assert ev.author == "real-reviewer"
