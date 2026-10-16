"""A re-run must never degrade a stored decision.

make_decision_id is deterministic on (source_id, extraction_version, index), so a
second extraction of the same source writes the same decision row. put_decision used
to overwrite unconditionally, so a later run that produced a placeholder ("change
recorded, rationale unknown", no verified quote) replaced a good record while its
verified evidence stayed behind, attached to a decision that now claimed no quote.

The rule: a stored decision that is quote-verified is replaced only by a record that
is at least as good, and evidence is only ever added or kept.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest

from app.stores.sqlite_cache import SqliteCache

REPO = "urllib3/urllib3"
SOURCE = f"pr:{REPO}#1397"
DEC = "dec_degradation"


def good_decision(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": DEC,
        "source_id": SOURCE,
        "repo": REPO,
        "summary": "Default to TLS 1.2",
        "decision_type": "Security",
        "rationale": "Older TLS is unsafe.",
        "state": "ACTIVE",
        "alternatives_considered": [],
        "constraints": [],
        "affected_entities": ["src/urllib3/util/ssl_.py"],
        "source_references": [],
        "decision_date": "2024-01-01T00:00:00Z",
        "source_author": "alice",
        "explicit_reversal_language": False,
        "unknown_fields": [],
        "quote_verified": True,
        "reason_unstated": False,
        "extraction_version": "v1",
        "content_hash": "hash_good",
        "created_at": "2024-01-01T00:00:00Z",
    }
    row.update(over)
    return row


def placeholder_decision(**over: Any) -> dict[str, Any]:
    """What a run with no surviving verified quote produces."""
    row = good_decision(
        summary="change recorded, rationale unknown",
        rationale=None,
        quote_verified=False,
        reason_unstated=True,
        content_hash="hash_empty",
    )
    row.update(over)
    return row


def evidence(ev_id: str = "ev_1", quote: str = "Older TLS is unsafe.", verified: bool = True) -> dict[str, Any]:
    return {
        "id": ev_id,
        "decision_id": DEC,
        "source_id": SOURCE,
        "source_type": "pull_request",
        "source_url": "https://github.com/urllib3/urllib3/pull/1397",
        "quote": quote,
        "author": "alice",
        "timestamp": "2024-01-01T00:00:00Z",
        "classification": "explicit",
        "claim": "tls",
        "quote_verified": verified,
        "created_at": "2024-01-01T00:00:00Z",
    }


@pytest.fixture()
def cache(tmp_path: Path) -> Iterator[SqliteCache]:
    with SqliteCache(tmp_path / "c.sqlite3") as opened:
        yield opened


# ---------------------------------------------------------------------------
# Scenario (a): a good run followed by an empty or failed run
# ---------------------------------------------------------------------------

def test_a_placeholder_run_does_not_replace_a_verified_decision(cache: SqliteCache) -> None:
    cache.put_decision(good_decision())
    cache.put_evidence(evidence())

    # The same source is extracted again and no quote survives verification.
    cache.put_decision(placeholder_decision())

    row = cache.decision_by_id(DEC)
    assert row["summary"] == "Default to TLS 1.2"
    assert row["rationale"] == "Older TLS is unsafe."
    assert row["quote_verified"] == 1
    assert row["content_hash"] == "hash_good"

    # Evidence is kept, still verified, and still attached: no orphan.
    kept = cache.evidence_for_decision(DEC)
    assert len(kept) == 1
    assert kept[0]["quote_verified"] == 1


def test_a_failed_run_leaves_the_decision_untouched(cache: SqliteCache) -> None:
    """A failed source never reaches put_decision; the stored record must survive."""
    cache.put_decision(good_decision())
    cache.put_evidence(evidence())

    # Nothing is written for a failed source. Assert the record is intact.
    row = cache.decision_by_id(DEC)
    assert row["summary"] == "Default to TLS 1.2"
    assert row["quote_verified"] == 1
    assert len(cache.evidence_for_decision(DEC)) == 1


def test_a_verified_run_with_a_blank_rationale_does_not_replace_a_full_one(
    cache: SqliteCache,
) -> None:
    cache.put_decision(good_decision())
    cache.put_decision(good_decision(rationale=None, content_hash="hash_blank"))

    row = cache.decision_by_id(DEC)
    assert row["rationale"] == "Older TLS is unsafe."
    assert row["content_hash"] == "hash_good"


# ---------------------------------------------------------------------------
# Scenario (b): a good run followed by a better run
# ---------------------------------------------------------------------------

def test_a_better_run_replaces_a_good_one_and_keeps_all_evidence(
    cache: SqliteCache,
) -> None:
    cache.put_decision(good_decision(content_hash="hash_1"))
    cache.put_evidence(evidence(ev_id="ev_1"))

    # A better run: still verified, a fuller summary, and a second quote.
    cache.put_decision(good_decision(summary="Require TLS 1.2 for every connection", content_hash="hash_2"))
    cache.put_evidence(evidence(ev_id="ev_2", quote="We require TLS 1.2 for every connection."))

    row = cache.decision_by_id(DEC)
    assert row["summary"] == "Require TLS 1.2 for every connection"
    assert row["content_hash"] == "hash_2"
    assert row["quote_verified"] == 1

    # Both quotes are present: a re-run adds, it does not replace the set.
    assert len(cache.evidence_for_decision(DEC)) == 2


def test_an_unverified_stored_decision_is_still_upgraded(cache: SqliteCache) -> None:
    """The guard protects good records; it must not freeze a placeholder forever."""
    cache.put_decision(placeholder_decision())
    cache.put_decision(good_decision())

    row = cache.decision_by_id(DEC)
    assert row["summary"] == "Default to TLS 1.2"
    assert row["quote_verified"] == 1


# ---------------------------------------------------------------------------
# Evidence is only added or kept
# ---------------------------------------------------------------------------

def test_verified_evidence_is_never_downgraded(cache: SqliteCache) -> None:
    cache.put_evidence(evidence(ev_id="ev_1", verified=True))
    cache.put_evidence(evidence(ev_id="ev_1", verified=False))

    kept = cache.evidence_for_decision(DEC)
    assert len(kept) == 1
    assert kept[0]["quote_verified"] == 1
