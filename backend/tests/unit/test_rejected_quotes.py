"""A quote the model proposed and verification dropped must not vanish silently.

The reply is gone once the call returns, so a rejected candidate was previously
indistinguishable from one the model never offered: the run counted an
`unverified_quote` but kept none of the text, the rung it failed at, or the
decision it belonged to. These tests pin the recording of that candidate.

`verify_quote` is not touched and nothing about acceptance is loosened.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.providers.llm_provider import MockLLMProvider
from app.services.extraction import (
    extract_decisions_from_source,
    last_rejected_quotes,
)
from app.services.quote_check import deepest_rung_over_sources, quote_match_rung
from app.stores.sqlite_cache import SqliteCache

import scripts.extract as extract_module

REPO = "urllib3/urllib3"

BODY = (
    "This pull request bumps DEFAULT_TIMEOUT to 30 seconds to reduce dropped "
    "connections under load."
)
REAL_QUOTE = "bumps DEFAULT_TIMEOUT to 30 seconds"
FABRICATED_QUOTE = "The model invented this sentence and it appears nowhere."

SOURCE = {
    "source_id": "pr:urllib3/urllib3#1234",
    "source_type": "pr",
    "source_url": "https://github.com/urllib3/urllib3/pull/1234",
    "repo": REPO,
    "title": "Tune the connection timeout",
    "body": BODY,
}


def reply(quote: str) -> str:
    return json.dumps({
        "no_decision": False,
        "decisions": [{
            "summary": "Raise the connection timeout",
            "decision_type": "Configuration",
            "rationale": "Fewer dropped connections under load.",
            "supporting_evidence": [{"quote": quote, "claim": "supports the change"}],
        }],
    })


def extract(quote: str):
    provider = MockLLMProvider(canned_response=reply(quote))
    return extract_decisions_from_source(provider=provider, **SOURCE)


# --- the rung classifier (reporting only) -----------------------------------


def test_the_rung_classifier_reports_the_deepest_match() -> None:
    assert quote_match_rung("exact words", "some exact words here") == "exact"
    assert quote_match_rung("EXACT WORDS", "some exact words here") == "case"
    assert quote_match_rung("exact   words", "some exact\nwords here") == "whitespace"
    assert quote_match_rung("exact words", "some **exact** [words](http://x) here") == "markdown"
    assert quote_match_rung("nowhere to be seen", "some exact words here") == "none"


def test_the_rung_classifier_never_decides_acceptance() -> None:
    """A `markdown` rung is still a quote verify_quote would accept; `none` is not."""
    assert quote_match_rung("exact words", "some **exact** words here") == "markdown"


def test_deepest_rung_takes_the_best_across_sources() -> None:
    assert deepest_rung_over_sources("needle", ["no match", "a NEEDLE here"]) == "case"
    assert deepest_rung_over_sources(FABRICATED_QUOTE, [BODY, "another"]) == "none"


# --- the module buffer ------------------------------------------------------


def test_a_fabricated_quote_is_recorded_with_its_rung() -> None:
    extract(FABRICATED_QUOTE)

    rejected = last_rejected_quotes()
    assert len(rejected) == 1
    entry = rejected[0]
    assert entry["candidate"] == FABRICATED_QUOTE
    assert entry["failed_rung"] == "none"
    assert entry["decision_summary"] == "Raise the connection timeout"
    assert entry["decision_id"].startswith("dec_")


def test_a_verified_quote_records_nothing() -> None:
    extract(REAL_QUOTE)

    assert last_rejected_quotes() == []


def test_the_buffer_does_not_leak_between_calls() -> None:
    extract(FABRICATED_QUOTE)
    assert len(last_rejected_quotes()) == 1

    extract(REAL_QUOTE)
    assert last_rejected_quotes() == []


def test_the_buffer_is_returned_as_a_copy() -> None:
    extract(FABRICATED_QUOTE)

    first = last_rejected_quotes()
    first.clear()

    assert len(last_rejected_quotes()) == 1


# --- persistence ------------------------------------------------------------


def test_rejected_candidates_survive_into_the_cache() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with SqliteCache(Path(tmp) / "cache.sqlite3") as cache:
            written = cache.put_rejected_quotes([{
                "run_id": "run-1", "repo": REPO, "source_id": SOURCE["source_id"],
                "decision_id": "dec_abc", "decision_summary": "Raise the timeout",
                "candidate": FABRICATED_QUOTE, "failed_rung": "none",
                "failure_reason": "Quote not found in any source section",
                "claim": "supports the change",
                "source_url": SOURCE["source_url"], "created_at": "2026-01-01T00:00:00Z",
            }])
            assert written == 1

            rows = cache.rejected_quotes(source_id=SOURCE["source_id"])

    assert len(rows) == 1
    row = rows[0]
    assert row["candidate"] == FABRICATED_QUOTE
    assert row["failed_rung"] == "none"
    assert row["decision_summary"] == "Raise the timeout"
    assert row["run_id"] == "run-1"


def test_rejected_candidates_are_filtered_by_source() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with SqliteCache(Path(tmp) / "cache.sqlite3") as cache:
            cache.put_rejected_quotes([
                {"run_id": "r", "repo": REPO, "source_id": "pr:x#1",
                 "candidate": "one", "failed_rung": "none", "created_at": "t"},
                {"run_id": "r", "repo": REPO, "source_id": "pr:x#2",
                 "candidate": "two", "failed_rung": "none", "created_at": "t"},
            ])

            assert [r["candidate"] for r in cache.rejected_quotes(source_id="pr:x#1")] == ["one"]
            assert {r["candidate"] for r in cache.rejected_quotes(repo=REPO)} == {"one", "two"}


# --- end to end through the script ------------------------------------------


def test_the_extraction_run_persists_rejected_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cache_path = Path(tmp) / "cache.sqlite3"
        with SqliteCache(cache_path) as cache:
            cache.put_raw(
                "pr", REPO, "1234",
                {"number": 1234, "title": "Tune the connection timeout",
                 "body": BODY, "files": ["src/urllib3/connectionpool.py"],
                 "author": {"login": "a"}, "mergedAt": "2024-01-01T00:00:00Z"},
            )

        monkeypatch.setattr(
            extract_module, "get_llm_provider",
            lambda **kw: MockLLMProvider(canned_response=reply(FABRICATED_QUOTE)),
        )
        monkeypatch.setattr(extract_module, "build_links", lambda *a, **k: 0)
        monkeypatch.setattr(extract_module, "summarise_injection_flags", lambda rows: {
            "sources_total": len(rows), "sources_flagged": 0,
        })

        code = extract_module.main([
            "--cache", str(cache_path), "--repo", REPO, "--sources", "1234",
        ])
        assert code == 0

        with SqliteCache(cache_path) as cache:
            rows = cache.rejected_quotes(source_id=f"pr:{REPO}#1234")

    assert len(rows) == 1
    assert rows[0]["candidate"] == FABRICATED_QUOTE
    assert rows[0]["failed_rung"] == "none"
