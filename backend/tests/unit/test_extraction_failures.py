"""A source that fails must be remembered, not silently dropped.

The first real extraction run died on the very first source because the model
endpoint was overloaded. Everything queued behind that source was lost with no
record of why, so a rerun had no way to know what to redo.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

from app.stores.sqlite_cache import SqliteCache


@pytest.fixture
def cache() -> Iterator[SqliteCache]:
    with tempfile.TemporaryDirectory() as tmp:
        opened = SqliteCache(Path(tmp) / "cache.sqlite3")
        try:
            yield opened
        finally:
            opened.close()


def store_decision(cache: SqliteCache, source_id: str, version: str = "v1") -> None:
    cache.put_decision({
        "id": f"dec-{source_id}",
        "source_id": source_id,
        "repo": "urllib3/urllib3",
        "summary": "Raised the cap",
        "decision_type": "Reliability",
        "rationale": "mobile clients timed out",
        "state": "ACTIVE",
        "alternatives_considered": [],
        "constraints": [],
        "affected_entities": [],
        "source_references": [],
        "decision_date": "2024-01-01T00:00:00Z",
        "source_author": "someone",
        "explicit_reversal_language": False,
        "unknown_fields": [],
        "quote_verified": True,
        "extraction_version": version,
        "content_hash": "abc",
        "created_at": "2024-01-01T00:00:00Z",
    })


def test_a_failure_records_the_source_status_and_error(cache: SqliteCache) -> None:
    cache.record_extraction_failure(
        "pr:urllib3/urllib3#3456", "urllib3/urllib3", "v1", "503", "model overloaded"
    )

    rows = cache.extraction_failures("urllib3/urllib3")
    assert len(rows) == 1
    assert rows[0]["source_id"] == "pr:urllib3/urllib3#3456"
    assert rows[0]["final_status"] == "503"
    assert rows[0]["error"] == "model overloaded"
    assert rows[0]["attempts"] == 1


def test_the_same_source_failing_twice_counts_two_attempts(cache: SqliteCache) -> None:
    for _ in range(2):
        cache.record_extraction_failure(
            "pr:urllib3/urllib3#3456", "urllib3/urllib3", "v1", "503", "still overloaded"
        )

    row = cache.extraction_failures("urllib3/urllib3")[0]
    assert row["attempts"] == 2


def test_a_recovered_source_no_longer_counts_as_failed(cache: SqliteCache) -> None:
    cache.record_extraction_failure(
        "pr:urllib3/urllib3#3456", "urllib3/urllib3", "v1", "503", "overloaded"
    )
    assert "pr:urllib3/urllib3#3456" in cache.failed_source_ids("urllib3/urllib3")

    cache.clear_extraction_failure("pr:urllib3/urllib3#3456")

    assert cache.failed_source_ids("urllib3/urllib3") == set()
    assert cache.extraction_failures("urllib3/urllib3") == []


def test_failures_are_scoped_to_one_repo(cache: SqliteCache) -> None:
    cache.record_extraction_failure("pr:a/b#1", "a/b", "v1", "503", "x")
    cache.record_extraction_failure("pr:c/d#1", "c/d", "v1", "503", "y")

    assert cache.failed_source_ids("a/b") == {"pr:a/b#1"}
    assert cache.failed_source_ids("c/d") == {"pr:c/d#1"}
    assert len(cache.extraction_failures()) == 2


def test_a_source_with_a_stored_decision_counts_as_extracted(cache: SqliteCache) -> None:
    store_decision(cache, "pr:urllib3/urllib3#3456")

    done = cache.extracted_source_ids("urllib3/urllib3", "v1")
    assert done == {"pr:urllib3/urllib3#3456"}


def test_a_different_extraction_version_is_not_treated_as_done(cache: SqliteCache) -> None:
    """Re-running a newer prompt must redo the work, not skip it."""
    store_decision(cache, "pr:urllib3/urllib3#3456", version="v1")

    assert cache.extracted_source_ids("urllib3/urllib3", "v1") == {"pr:urllib3/urllib3#3456"}
    assert cache.extracted_source_ids("urllib3/urllib3", "v2") == set()


def test_the_table_is_created_on_an_existing_cache_file() -> None:
    """A cache written before this table existed must still gain it on open."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "old.sqlite3"
        # The shape an older cache really had: raw_objects with its columns, and no
        # extraction_failures table.
        opened = SqliteCache(path)
        try:
            opened._connection.execute("DROP TABLE extraction_failures")
            opened._connection.commit()
            assert not opened.has_table("extraction_failures")
        finally:
            opened.close()

        reopened = SqliteCache(path)
        try:
            assert reopened.has_table("extraction_failures")
            reopened.record_extraction_failure("pr:a/b#1", "a/b", "v1", "503", "x")
            assert len(reopened.extraction_failures("a/b")) == 1
        finally:
            reopened.close()


def test_a_failure_never_stores_a_credential(cache: SqliteCache) -> None:
    """An upstream error can echo the key back; the cache must not keep it."""
    cache.record_extraction_failure(
        "pr:a/b#1", "a/b", "v1", "401",
        "rejected key sk-live-AAAABBBBCCCCDDDDEEEEFFFF1234",
    )

    blob = " ".join(str(row["error"]) for row in cache.extraction_failures("a/b"))
    assert "sk-live-AAAABBBBCCCCDDDDEEEEFFFF1234" not in blob
