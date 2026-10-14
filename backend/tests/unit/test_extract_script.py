"""Stage 2 must survive a bad source and be able to resume.

The first real run stopped at the very first source because the model endpoint was
overloaded, and every source queued behind it was lost with no record of why.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Iterator, Optional

import pytest

from app.stores.sqlite_cache import SqliteCache

import scripts.extract as extract_module


# --- ordering ---------------------------------------------------------------


def pr_row(number: int, files: list[str], kind: str = "pr") -> dict[str, Any]:
    return {
        "id": f"pr:urllib3/urllib3#{number}",
        "kind": kind,
        "payload": json.dumps({
            "number": number,
            "title": f"Change {number}",
            "files": files,
        }),
    }


def doc_row(name: str) -> dict[str, Any]:
    return {
        "id": f"doc:urllib3/urllib3:{name}",
        "kind": "doc",
        "payload": json.dumps({"content": "docs", "files": []}),
    }


def test_the_two_pinned_pull_requests_come_first_in_order() -> None:
    rows = [
        doc_row("CHANGES.rst"),
        pr_row(3466, ["src/urllib3/util/ssl_.py"]),
        pr_row(900, ["src/urllib3/connectionpool.py"]),
        pr_row(3456, ["src/urllib3/util/ssl_.py"]),
    ]

    chosen = [row["id"] for row in extract_module.select_sources(rows, 10)]

    assert chosen[:2] == ["pr:urllib3/urllib3#3456", "pr:urllib3/urllib3#3466"]


def test_a_pull_request_touching_a_target_file_outranks_one_that_does_not() -> None:
    rows = [
        pr_row(100, ["README.md"]),
        pr_row(200, ["src/urllib3/connection.py"]),
    ]

    chosen = [row["id"] for row in extract_module.select_sources(rows, 2)]

    assert chosen == ["pr:urllib3/urllib3#200", "pr:urllib3/urllib3#100"]


def test_documentation_is_considered_last() -> None:
    rows = [
        doc_row("CHANGES.rst"),
        pr_row(100, ["README.md"]),
        pr_row(3456, ["changelog/3456.feature.rst"]),
    ]

    chosen = [row["id"] for row in extract_module.select_sources(rows, 10)]

    assert chosen[-1] == "doc:urllib3/urllib3:CHANGES.rst"


def test_a_path_without_the_source_prefix_still_matches_the_target_file() -> None:
    """GitHub reported `urllib3/connectionpool.py` where git said `src/urllib3/...`."""
    rows = [pr_row(100, ["README.md"]), pr_row(200, ["urllib3/connectionpool.py"])]

    chosen = [row["id"] for row in extract_module.select_sources(rows, 2)]

    assert chosen[0] == "pr:urllib3/urllib3#200"


def test_the_limit_cuts_the_list_rather_than_the_candidates() -> None:
    rows = [pr_row(n, ["src/urllib3/connectionpool.py"]) for n in range(50)]

    chosen = extract_module.select_sources(rows, 10)

    assert len(chosen) == 10
    assert len(rows) == 50, "the caller's list must not be mutated in place"


def test_a_malformed_payload_does_not_break_the_ranking() -> None:
    rows = [
        {"id": "pr:urllib3/urllib3#1", "kind": "pr", "payload": "not json at all"},
        pr_row(3456, []),
    ]

    chosen = [row["id"] for row in extract_module.select_sources(rows, 10)]

    assert chosen[0] == "pr:urllib3/urllib3#3456"


# --- source urls ------------------------------------------------------------


@pytest.mark.parametrize(
    ("source_id", "expected"),
    [
        ("pr:urllib3/urllib3#3456", "https://github.com/urllib3/urllib3/pull/3456"),
        ("issue:urllib3/urllib3#50", "https://github.com/urllib3/urllib3/issues/50"),
        ("commit:abc123", "https://github.com/urllib3/urllib3/commit/abc123"),
        ("doc:urllib3/urllib3:CHANGES.rst", "https://github.com/urllib3/urllib3/blob/main/CHANGES.rst"),
    ],
)
def test_a_citation_points_at_the_source_and_not_the_repository(
    source_id: str, expected: str
) -> None:
    url = extract_module.source_url_for(source_id, "urllib3/urllib3", {})
    assert url == expected


def test_a_stored_url_is_preferred_over_a_derived_one() -> None:
    url = extract_module.source_url_for(
        "pr:urllib3/urllib3#3456", "urllib3/urllib3",
        {"url": "https://example.invalid/custom"},
    )
    assert url == "https://example.invalid/custom"


# --- run behaviour ----------------------------------------------------------


@pytest.fixture
def cache_with_sources() -> Iterator[SqliteCache]:
    with tempfile.TemporaryDirectory() as tmp:
        opened = SqliteCache(Path(tmp) / "cache.sqlite3")
        for number in (3456, 3466):
            opened.put_raw(
                "pr", "urllib3/urllib3", str(number),
                {"number": number, "title": f"PR {number}", "body": "body text",
                 "files": ["src/urllib3/util/ssl_.py"], "author": {"login": "someone"},
                 "mergedAt": "2024-01-01T00:00:00Z"},
            )
        try:
            yield opened
        finally:
            opened.close()


class RecordingProvider:
    """Stands in for the model so the loop can be exercised without one."""

    is_real = False

    def complete_structured(self, schema, prompt, system=None, **kwargs):  # noqa: ANN001
        raise AssertionError("the extractor should not reach a raw completion here")

    def complete(self, prompt, system=None, **kwargs):  # noqa: ANN001
        raise AssertionError("unused")


def run_main(
    cache: SqliteCache,
    monkeypatch: pytest.MonkeyPatch,
    *,
    failing: Optional[set[str]] = None,
    store_decision_for: Optional[set[str]] = None,
    **extra: str,
) -> int:
    """Run the script's main against a prepared cache, recording what it touched."""
    calls: list[str] = []

    def fake_extract(**kwargs: Any) -> list[Any]:
        source_id = kwargs["source_id"]
        calls.append(source_id)
        if failing and source_id in failing:
            from app.providers.llm_provider import LLMProviderError

            error = LLMProviderError("HTTP 503: model overloaded")
            error.status_code = 503  # type: ignore[attr-defined]
            raise error
        if store_decision_for and source_id in store_decision_for:
            cache.put_decision({
                "id": f"dec-{source_id}", "source_id": source_id, "repo": kwargs["repo"],
                "summary": "Raised the cap", "decision_type": "Reliability",
                "rationale": "clients timed out", "state": "ACTIVE",
                "alternatives_considered": [], "constraints": [], "affected_entities": [],
                "source_references": [], "decision_date": None, "source_author": None,
                "explicit_reversal_language": False, "unknown_fields": [],
                "quote_verified": True, "extraction_version": kwargs["extraction_version"],
                "content_hash": "h", "created_at": "",
            })
        return []

    monkeypatch.setattr(extract_module, "get_llm_provider", lambda **kw: RecordingProvider())
    monkeypatch.setattr(extract_module, "extract_decisions_from_source", fake_extract)
    monkeypatch.setattr(extract_module, "build_links", lambda *a, **k: 0)
    monkeypatch.setattr(extract_module, "summarise_injection_flags", lambda rows: {
        "sources_total": len(rows), "sources_flagged": 0,
    })
    RUNS.append(calls)

    argv = ["--cache", str(cache.path), "--repo", "urllib3/urllib3", "--limit", "10",
            "--token-budget", "60000", "--sample-review-file", str(cache.path) + ".md"]
    for key, value in extra.items():
        flag = f"--{key.replace('_', '-')}"
        # A store_true flag takes no value.
        argv += [flag] if value == "" else [flag, value]
    return extract_module.main(argv)


#: Every set of sources each run_extraction call actually sent to the model.
RUNS: list[list[str]] = []


@pytest.fixture(autouse=True)
def _clear_runs() -> Iterator[None]:
    RUNS.clear()
    yield
    RUNS.clear()


def test_a_failing_source_does_not_stop_the_next_one(
    cache_with_sources: SqliteCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    code = run_main(
        cache_with_sources, monkeypatch, failing={"pr:urllib3/urllib3#3456"}
    )

    assert code == 0, "a partial run still succeeds"
    assert RUNS[0] == ["pr:urllib3/urllib3#3456", "pr:urllib3/urllib3#3466"], (
        "the source after the failure must still be attempted"
    )


def test_a_failed_source_is_recorded_with_its_status(
    cache_with_sources: SqliteCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_main(cache_with_sources, monkeypatch, failing={"pr:urllib3/urllib3#3456"})

    rows = cache_with_sources.extraction_failures("urllib3/urllib3")
    assert [r["source_id"] for r in rows] == ["pr:urllib3/urllib3#3456"]
    assert rows[0]["final_status"] == "503"


def test_exiting_non_zero_when_every_source_failed(
    cache_with_sources: SqliteCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    code = run_main(
        cache_with_sources, monkeypatch,
        failing={"pr:urllib3/urllib3#3456", "pr:urllib3/urllib3#3466"},
    )
    assert code == 1


def test_a_recovered_source_is_no_longer_recorded_as_failed(
    cache_with_sources: SqliteCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_main(cache_with_sources, monkeypatch, failing={"pr:urllib3/urllib3#3456"})
    assert cache_with_sources.failed_source_ids("urllib3/urllib3")

    run_main(cache_with_sources, monkeypatch)

    assert "pr:urllib3/urllib3#3456" not in cache_with_sources.failed_source_ids("urllib3/urllib3")


def test_retry_failed_touches_only_the_recorded_failures(
    cache_with_sources: SqliteCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    # First pass: one source fails, the other is stored successfully.
    run_main(cache_with_sources, monkeypatch, failing={"pr:urllib3/urllib3#3466"},
             store_decision_for={"pr:urllib3/urllib3#3456"})
    assert cache_with_sources.failed_source_ids("urllib3/urllib3") == {"pr:urllib3/urllib3#3466"}

    # Second pass with --retry-failed: only the failed source is attempted.
    run_main(cache_with_sources, monkeypatch, retry_failed="")

    assert RUNS[1] == ["pr:urllib3/urllib3#3466"], (
        "retrying must not redo the source that already succeeded"
    )


def test_a_rerun_skips_a_source_that_already_has_a_stored_result(
    cache_with_sources: SqliteCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_main(cache_with_sources, monkeypatch, store_decision_for={"pr:urllib3/urllib3#3456"})
    assert RUNS[0] == ["pr:urllib3/urllib3#3456", "pr:urllib3/urllib3#3466"]

    run_main(cache_with_sources, monkeypatch)

    assert RUNS[1] == ["pr:urllib3/urllib3#3466"], (
        "a source with a stored decision must not be extracted again"
    )


def test_tokens_from_earlier_runs_are_included_in_the_total(
    cache_with_sources: SqliteCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_with_sources.record_extraction_run(
        "urllib3/urllib3", "earlier-run", tokens=1234, decisions=0, evidence=0, failures=0
    )
    assert cache_with_sources.total_extraction_tokens("urllib3/urllib3") == 1234

    run_main(cache_with_sources, monkeypatch)

    # The new run is recorded too, and the earlier spend is not lost.
    assert cache_with_sources.total_extraction_tokens("urllib3/urllib3") >= 1234


def test_a_dry_run_makes_no_model_call_and_no_failure(
    cache_with_sources: SqliteCache, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    def explode(**kwargs: Any) -> list[Any]:
        raise AssertionError("a dry run must not call the model")

    monkeypatch.setattr(extract_module, "get_llm_provider", lambda **kw: RecordingProvider())
    monkeypatch.setattr(extract_module, "extract_decisions_from_source", explode)
    monkeypatch.setattr(extract_module, "build_links", lambda *a, **k: 0)
    monkeypatch.setattr(extract_module, "summarise_injection_flags", lambda rows: {
        "sources_total": len(rows), "sources_flagged": 0,
    })

    code = extract_module.main([
        "--cache", str(cache_with_sources.path), "--repo", "urllib3/urllib3",
        "--limit", "10", "--dry-run",
        "--sample-review-file", str(cache_with_sources.path) + ".md",
    ])

    assert code == 0
    assert cache_with_sources.extraction_failures("urllib3/urllib3") == []
