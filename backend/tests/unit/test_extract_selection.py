"""--limit must always take the priority order among sources still to do.

PRs #3456 and #3466 answered correctly with zero decisions. Their failure rows were
cleared and they produced no decision rows, so they appeared in neither the failed
set nor the already-extracted set: `--retry-failed` skipped them, the resume filter
could not see them, and they were never selected again. A finished source looked
exactly like one nobody had tried.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Iterator, Optional

import pytest

from app.stores.sqlite_cache import SqliteCache

import scripts.extract as extract_module

REPO = "urllib3/urllib3"


def pr_payload(number: int, files: list[str]) -> dict[str, Any]:
    return {
        "id": f"pr:{REPO}#{number}",
        "kind": "pr",
        "payload": json.dumps({"number": number, "title": f"PR {number}", "files": files}),
    }


@pytest.fixture()
def cache() -> Iterator[SqliteCache]:
    with tempfile.TemporaryDirectory() as tmp:
        opened = SqliteCache(Path(tmp) / "cache.sqlite3")
        for number in (3456, 3466, 1356, 1397):
            opened.put_raw(
                "pr", REPO, str(number),
                {"number": number, "title": f"PR {number}", "body": "text",
                 "files": ["src/urllib3/connectionpool.py"],
                 "author": {"login": "a"}, "mergedAt": "2024-01-01T00:00:00Z"},
            )
        try:
            yield opened
        finally:
            opened.close()


def run(
    cache: SqliteCache,
    monkeypatch: pytest.MonkeyPatch,
    *extra: str,
) -> tuple[int, list[str]]:
    """Run the script with a mock provider, returning (exit code, sources attempted)."""
    from app.providers.llm_provider import MockLLMProvider

    attempted: list[str] = []
    monkeypatch.setattr(
        extract_module, "get_llm_provider",
        lambda **kw: MockLLMProvider(canned_response=json.dumps({"decisions": []})),
    )
    monkeypatch.setattr(extract_module, "build_links", lambda *a, **k: 0)
    monkeypatch.setattr(extract_module, "summarise_injection_flags", lambda rows: {
        "sources_total": len(rows), "sources_flagged": 0,
    })

    def fake_extract(**kwargs):
        attempted.append(kwargs["source_id"])
        return []

    monkeypatch.setattr(extract_module, "extract_decisions_from_source", fake_extract)
    code = extract_module.main([
        "--cache", str(cache.path), "--repo", REPO,
        "--sample-review-file", str(cache.path) + ".md",
        *extra,
    ])
    return code, attempted


def mark_done(cache: SqliteCache, source_id: str, status: str = "no_decision") -> None:
    cache.record_extraction_source(
        repo=REPO, source_id=source_id, extraction_version="v1",
        status=status, run_id="older-run", model="m",
    )


def test_changed_files_from_payload_drops_blanks_and_duplicates() -> None:
    """The payload is untrusted JSON: only non-empty strings are kept, once each."""
    assert extract_module.changed_files_from_payload(
        {"files": ["a.py", "", None, "a.py", "   ", "b.py"]}
    ) == ["a.py", "b.py"]
    assert extract_module.changed_files_from_payload({"files": "not-a-list"}) == []
    assert extract_module.changed_files_from_payload({}) == []


def test_payload_files_reach_the_extractor_as_changed_files(
    cache: SqliteCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    """affected_entities is built from changed_files, so the payload's file list has
    to reach the extractor. Without it every decision carries no entity, the graph
    gets no GOVERNS edges, and /ask cannot resolve anything."""
    from app.providers.llm_provider import MockLLMProvider

    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        extract_module, "get_llm_provider",
        lambda **kw: MockLLMProvider(canned_response=json.dumps({"decisions": []})),
    )
    monkeypatch.setattr(extract_module, "build_links", lambda *a, **k: 0)
    monkeypatch.setattr(extract_module, "summarise_injection_flags", lambda rows: {
        "sources_total": len(rows), "sources_flagged": 0,
    })

    def fake_extract(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(extract_module, "extract_decisions_from_source", fake_extract)

    extract_module.main([
        "--cache", str(cache.path), "--repo", REPO, "--sources", f"pr:{REPO}#1397",
    ])

    assert captured["changed_files"] == ["src/urllib3/connectionpool.py"]


def test_the_priority_sources_are_chosen_first(
    cache: SqliteCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, attempted = run(cache, monkeypatch, "--limit", "2")

    assert attempted == [f"pr:{REPO}#3456", f"pr:{REPO}#3466"], (
        "the limit must follow the priority order, not alphabetical order"
    )


def test_a_source_that_reported_no_decision_is_not_processed_again(
    cache: SqliteCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    """This is the #3456 case: completed, empty answer, must not be redone."""
    mark_done(cache, f"pr:{REPO}#3456", "no_decision")
    mark_done(cache, f"pr:{REPO}#3466", "no_decision")

    _, attempted = run(cache, monkeypatch, "--limit", "2")

    assert attempted == [f"pr:{REPO}#1356", f"pr:{REPO}#1397"]


def test_a_failed_source_is_chosen_again_by_a_normal_run(
    cache: SqliteCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache.record_extraction_failure(
        f"pr:{REPO}#3456", REPO, "v1", "503", "overloaded"
    )
    mark_done(cache, f"pr:{REPO}#3466", "no_decision")

    _, attempted = run(cache, monkeypatch, "--limit", "2")

    assert f"pr:{REPO}#3456" in attempted, (
        "a failed source must come back on an ordinary run, not only with --retry-failed"
    )


def test_limit_ranks_failures_and_unprocessed_together(
    cache: SqliteCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unprocessed and failed sources compete in one priority ranking."""
    cache.record_extraction_failure(f"pr:{REPO}#1397", REPO, "v1", "503", "x")

    _, attempted = run(cache, monkeypatch, "--limit", "4")

    # The two pinned pull requests lead; the rest share one tier and are ordered by
    # id, so a failure is not privileged over an untried source of equal standing.
    assert attempted == [
        f"pr:{REPO}#3456", f"pr:{REPO}#3466", f"pr:{REPO}#1356", f"pr:{REPO}#1397",
    ]


def test_sources_selects_exactly_the_named_ones(
    cache: SqliteCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, attempted = run(cache, monkeypatch, "--sources", f"pr:{REPO}#1397", f"pr:{REPO}#3456")

    assert sorted(attempted) == [f"pr:{REPO}#1397", f"pr:{REPO}#3456"]


def test_sources_accepts_a_bare_pull_request_number(
    cache: SqliteCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, attempted = run(cache, monkeypatch, "--sources", "1397")

    assert attempted == [f"pr:{REPO}#1397"]


def test_sources_rejects_a_number_that_is_not_in_the_cache(
    cache: SqliteCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, attempted = run(cache, monkeypatch, "--sources", "9999")

    assert attempted == []


def test_force_re_extracts_a_source_already_done(
    cache: SqliteCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    mark_done(cache, f"pr:{REPO}#3456", "no_decision")
    mark_done(cache, f"pr:{REPO}#3466", "no_decision")

    _, attempted = run(cache, monkeypatch, "--sources", f"pr:{REPO}#3456", "--force")

    assert attempted == [f"pr:{REPO}#3456"], "--force must ignore the completed record"


def test_without_force_a_named_source_already_done_is_skipped(
    cache: SqliteCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    mark_done(cache, f"pr:{REPO}#3456", "no_decision")

    _, attempted = run(cache, monkeypatch, "--sources", f"pr:{REPO}#3456")

    assert attempted == []