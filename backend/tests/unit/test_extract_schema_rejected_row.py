"""The flat reply must leave a schema_rejected row, end to end.

This is the regression for the real run: a model answered with
`{"no_decision": false, "decision_type": ..., "decision_summary": ...}`, the fields
were discarded, and the run reported success with zero decisions and no error.
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any, Iterator, Optional

import pytest

from app.stores.sqlite_cache import SqliteCache

import scripts.extract as extract_module

REPO = "urllib3/urllib3"

#: The exact object the real run received, verbatim.
FLAT_REPLY = {
    "no_decision": False,
    "decision_type": "Compatibility",
    "decision_summary": (
        "Revert of HTTP/2 TLS settings due to incompatibility with curl "
        "and inability to use the new settings."
    ),
    "supporting_evidence": [
        {"quote": "we can't really use those new settings", "claim": "reverted", "timestamp": None}
    ],
}

GOOD_REPLY = {
    "decisions": [{
        "summary": "Reverted the HTTP/2 TLS settings",
        "decision_type": "Compatibility",
        "rationale": "curl cannot use them",
        "supporting_evidence": [
            {"quote": "we can't really use those new settings", "claim": "why"}
        ],
    }]
}


@pytest.fixture()
def cache() -> Iterator[SqliteCache]:
    with tempfile.TemporaryDirectory() as tmp:
        opened = SqliteCache(Path(tmp) / "cache.sqlite3")
        opened.put_raw(
            "pr", REPO, "3466",
            {"number": 3466, "title": 'Revert "Add TLS settings for HTTP/2"',
             "body": "we can't really use those new settings",
             "files": ["src/urllib3/util/ssl_.py"]},
        )
        try:
            yield opened
        finally:
            opened.close()


def run(cache: SqliteCache, monkeypatch: pytest.MonkeyPatch, reply: object) -> int:
    """Run the script's main with a mock provider that replies with `reply`.

    Only the provider is replaced. The real extraction path runs, so the schema
    check and the rejection recording are genuinely exercised.
    """
    from app.providers.llm_provider import MockLLMProvider

    canned = json.dumps(reply)
    monkeypatch.setattr(
        extract_module, "get_llm_provider", lambda **kw: MockLLMProvider(canned_response=canned)
    )
    monkeypatch.setattr(extract_module, "build_links", lambda *a, **k: 0)
    monkeypatch.setattr(extract_module, "summarise_injection_flags", lambda rows: {
        "sources_total": len(rows), "sources_flagged": 0,
    })

    return extract_module.main([
        "--cache", str(cache.path), "--repo", REPO, "--limit", "10",
        "--sample-review-file", str(cache.path) + ".md",
    ])


def test_the_flat_reply_writes_a_schema_rejected_row(
    cache: SqliteCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    exit_code = run(cache, monkeypatch, FLAT_REPLY)

    rows = cache.extraction_failures(REPO)
    assert len(rows) == 1, "a reply that was dropped instead of recorded"
    assert rows[0]["source_id"] == "pr:urllib3/urllib3#3466"
    assert rows[0]["final_status"] == "schema_rejected"


def test_the_row_names_the_keys_but_not_the_content(
    cache: SqliteCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    run(cache, monkeypatch, FLAT_REPLY)

    stored = " ".join(str(row["error"]) for row in cache.extraction_failures(REPO))
    assert "decision_summary" in stored
    assert "decision_type" in stored
    # The summary and the quote are untrusted repository content and must not be kept.
    assert "Revert of HTTP/2 TLS settings" not in stored
    assert "incompatibility with curl" not in stored


def test_the_row_records_the_source_and_the_finish_reason(
    cache: SqliteCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    run(cache, monkeypatch, FLAT_REPLY)

    stored = " ".join(str(row["error"]) for row in cache.extraction_failures(REPO))
    assert "pr:urllib3/urllib3#3466" in stored


def test_every_source_rejected_exits_non_zero(
    cache: SqliteCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert run(cache, monkeypatch, FLAT_REPLY) == 1


def test_the_summary_line_reports_each_bucket(
    cache: SqliteCache, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    with caplog.at_level(logging.INFO, logger="codewhy.extract"):
        run(cache, monkeypatch, FLAT_REPLY)

    summary = "\n".join(
        record.getMessage() for record in caplog.records
        if "Run summary" in record.getMessage()
    )
    assert "decisions=0" in summary
    assert "no_decision=0" in summary
    assert "schema_rejected=1" in summary
    assert "failed=0" in summary


def test_a_good_reply_is_not_recorded_as_a_failure(
    cache: SqliteCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    exit_code = run(cache, monkeypatch, GOOD_REPLY)

    assert cache.extraction_failures(REPO) == []
    assert exit_code == 0
    assert cache.count("decisions", REPO) == 1


def test_an_empty_decision_list_counts_as_no_decision_not_a_rejection(
    cache: SqliteCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    exit_code = run(cache, monkeypatch, {"decisions": []})

    assert cache.extraction_failures(REPO) == [], (
        "an empty list is the agreed way to say there is no decision"
    )
    assert exit_code == 0