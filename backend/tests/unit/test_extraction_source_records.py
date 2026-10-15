"""Every source outcome must leave a record, including "no decision".

PRs #3456 and #3466 answered correctly with zero decisions. The run called
`clear_extraction_failure`, so their failure row was deleted, and because they
produced no decision row either, they appeared in neither set. `--retry-failed`
skipped them, the resume filter could not see them, and they were never selected
again: a source that had been fully processed looked identical to one nobody had
tried.

Recording the outcome per source, with the model and the response_format mode,
also makes two models comparable on the same source.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Iterator

import pytest

from app.stores.sqlite_cache import SqliteCache

REPO = "urllib3/urllib3"


@pytest.fixture()
def cache() -> Iterator[SqliteCache]:
    with tempfile.TemporaryDirectory() as tmp:
        opened = SqliteCache(Path(tmp) / "cache.sqlite3")
        try:
            yield opened
        finally:
            opened.close()


def record(cache: SqliteCache, source_id: str, status: str, **kwargs) -> None:
    cache.record_extraction_source(
        repo=REPO,
        source_id=source_id,
        extraction_version="v1",
        status=status,
        run_id=kwargs.pop("run_id", "run-1"),
        model=kwargs.pop("model", "model-a"),
        response_format_mode=kwargs.pop("response_format_mode", "json_schema"),
        finish_reason=kwargs.pop("finish_reason", "stop"),
        decisions=kwargs.pop("decisions", 0),
        tokens=kwargs.pop("tokens", 100),
        detail=kwargs.pop("detail", ""),
    )


def test_a_source_with_no_decision_is_still_recorded(cache: SqliteCache) -> None:
    record(cache, "pr:urllib3/urllib3#3456", "no_decision")

    done = cache.processed_source_ids(REPO, "v1")
    assert "pr:urllib3/urllib3#3456" in done, (
        "a completed source with nothing to extract is still processed"
    )


def test_a_source_with_decisions_is_recorded(cache: SqliteCache) -> None:
    record(cache, "pr:urllib3/urllib3#1397", "ok", decisions=2, tokens=4096)

    done = cache.processed_source_ids(REPO, "v1")
    assert "pr:urllib3/urllib3#1397" in done


def test_a_failed_source_is_not_counted_as_processed(cache: SqliteCache) -> None:
    record(cache, "pr:urllib3/urllib3#1440", "failed")

    assert cache.processed_source_ids(REPO, "v1") == set()


def test_a_schema_rejected_source_is_not_counted_as_processed(cache: SqliteCache) -> None:
    record(cache, "pr:urllib3/urllib3#1463", "schema_rejected")

    assert cache.processed_source_ids(REPO, "v1") == set()


def test_the_model_and_mode_are_stored_for_comparison(cache: SqliteCache) -> None:
    record(cache, "pr:urllib3/urllib3#1429", "ok",
           model="google/gemma-4-31b-it:free", response_format_mode="json_object")

    rows = cache.extraction_sources(REPO)
    assert rows[0]["model"] == "google/gemma-4-31b-it:free"
    assert rows[0]["response_format_mode"] == "json_object"


def test_two_models_can_be_compared_on_one_source(cache: SqliteCache) -> None:
    """Re-running the same source with --force must keep the earlier run."""
    record(cache, "pr:urllib3/urllib3#1429", "ok", run_id="run-a", model="model-a")
    record(cache, "pr:urllib3/urllib3#1429", "ok", run_id="run-b", model="model-b")

    rows = cache.extraction_sources(REPO)
    assert len(rows) == 2
    assert {r["model"] for r in rows} == {"model-a", "model-b"}


def test_repeating_a_source_within_a_run_updates_rather_than_duplicates(cache: SqliteCache) -> None:
    """A source retried inside one run keeps a single row reflecting the final state."""
    record(cache, "pr:urllib3/urllib3#1429", "failed", run_id="run-a")
    record(cache, "pr:urllib3/urllib3#1429", "ok", run_id="run-a", decisions=1)

    rows = cache.extraction_sources(REPO)
    assert len(rows) == 1
    assert rows[0]["status"] == "ok", "the later attempt is the one that counts"


def test_the_tokens_and_finish_reason_are_recorded(cache: SqliteCache) -> None:
    record(cache, "pr:urllib3/urllib3#1440", "ok",
           tokens=5124, finish_reason="length", decisions=0)

    row = cache.extraction_sources(REPO)[0]
    assert row["tokens"] == 5124
    assert row["finish_reason"] == "length"


def test_a_detail_note_never_stores_repository_text(cache: SqliteCache) -> None:
    """The detail column is a status note, not a place to park untrusted prose."""
    record(cache, "pr:urllib3/urllib3#1", "schema_rejected",
           detail="keys received: decision_summary, no_decision")

    row = cache.extraction_sources(REPO)[0]
    assert "decision_summary" in row["detail"]