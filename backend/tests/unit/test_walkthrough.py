"""The guided walkthrough runs offline against a tiny cache.

The walkthrough is meant to be safe to run in front of a demo: read only, no
network, no model call. This test pins the two properties that make that true and
that a reader depends on:

* stages 0 to 3 print their title and their real numbers from a small cache, and
* no value read from the environment is ever printed, whatever it looks like.

It builds a throwaway SQLite cache and a small in-memory graph, so nothing here
reads the developer's `.env` or reaches a service.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

import scripts.walkthrough as walkthrough
from app.config import Settings

REPO = "acme/netclient"

#: Sentinel values that must never appear in the output. Each is distinctive so a
#: substring check cannot pass by accident.
SECRETS = {
    "GITHUB_TOKEN": "ghp_walkthroughsecretsentinel0000000000",
    "LLM_API_KEY": "sk-walkthroughsecretsentinel0000000000",
    "NEO4J_PASSWORD": "walkthroughsecretsentinelpassword",
}

STAGE_TITLES = [
    "STAGE 0",
    "STAGE 1",
    "STAGE 2",
    "STAGE 3",
]


def _build_cache(path) -> None:
    cache = walkthrough.SqliteCache(path)
    connection = cache._connection

    pr = {
        "number": 1,
        "title": "Add a retry loop",
        "body": "The retry loop was added because the timeout was too short for mobile clients.",
        "state": "MERGED",
        "merged": True,
        "mergedAt": "2024-01-01T00:00:00Z",
        "author": "octo",
        "merge_commit": "abc123",
        "files": ["src/netclient/retry.py"],
    }
    issue = {"number": 7, "title": "Timeouts on mobile", "body": "Mobile clients time out."}
    doc = {"path": "docs/architecture.md", "title": "Architecture", "body": "Retry design."}

    for object_id, kind, key, payload in (
        ("pr:acme/netclient#1", "pr", "1", pr),
        ("issue:acme/netclient#7", "issue", "7", issue),
        ("doc:acme/netclient:docs/architecture.md", "doc", "docs/architecture.md", doc),
    ):
        connection.execute(
            "INSERT INTO raw_objects (id, kind, repo, fetched_at, content_hash, json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (object_id, kind, REPO, "2024-01-01T00:00:00+00:00", key, json.dumps(payload)),
        )

    connection.execute(
        "INSERT INTO commits (sha, repo, authored_at, committed_at, author_name, subject, "
        "message, parent_shas, pull_requests, closing, mentions, trailers) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "abc123",
            REPO,
            "2024-01-01T00:00:00+00:00",
            "2024-01-01T00:00:00+00:00",
            "octo",
            "Add a retry loop",
            "Add a retry loop\n\nThis reverts commit def456.",
            "[]",
            "[1]",
            "[]",
            "[]",
            "[]",
        ),
    )
    connection.execute(
        "INSERT INTO commit_files (sha, path, old_path, status, diff, diff_truncated) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("abc123", "src/netclient/retry.py", None, "added", "", 0),
    )

    connection.execute(
        "INSERT INTO decisions (id, source_id, repo, summary, decision_type, rationale, state, "
        "affected_entities, source_references, decision_date, source_author, "
        "explicit_reversal_language, unknown_fields, quote_verified, extraction_version, "
        "content_hash, created_at, reason_unstated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "?, ?, ?, ?, ?, ?)",
        (
            "dec_1",
            "pr:acme/netclient#1",
            REPO,
            "Add a retry loop",
            "design",
            "The timeout was too short for mobile clients.",
            "ACTIVE",
            json.dumps(["file:acme/netclient:src/netclient/retry.py"]),
            json.dumps(["pr:acme/netclient#1"]),
            "2024-01-01",
            "octo",
            0,
            "[]",
            1,
            "v1",
            "hash1",
            "2024-01-01T00:00:00+00:00",
            0,
        ),
    )
    connection.execute(
        "INSERT INTO decisions (id, source_id, repo, summary, decision_type, rationale, state, "
        "affected_entities, source_references, decision_date, source_author, "
        "explicit_reversal_language, unknown_fields, quote_verified, extraction_version, "
        "content_hash, created_at, reason_unstated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "?, ?, ?, ?, ?, ?)",
        (
            "dec_placeholder",
            "pr:acme/netclient#2",
            REPO,
            "change recorded, rationale unknown",
            "unknown",
            None,
            "ACTIVE",
            json.dumps([]),
            json.dumps(["pr:acme/netclient#2"]),
            None,
            None,
            0,
            "[]",
            0,
            "v1",
            "hash2",
            "2024-01-02T00:00:00+00:00",
            1,
        ),
    )

    connection.execute(
        "INSERT INTO evidence (id, decision_id, source_id, source_type, source_url, quote, "
        "author, timestamp, classification, claim, quote_verified, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "ev_1",
            "dec_1",
            "pr:acme/netclient#1",
            "pull_request",
            "https://github.com/acme/netclient/pull/1",
            "the timeout was too short for mobile clients",
            "octo",
            "2024-01-01T00:00:00+00:00",
            "rationale",
            "States why the retry loop was added.",
            1,
            "2024-01-01T00:00:00+00:00",
        ),
    )

    for link_id, source_id, source_type, rel_type, target_id, target_type, derivation in (
        (
            "link:commit:abc123:PART_OF:pr:acme/netclient#1",
            "commit:abc123",
            "Commit",
            "PART_OF",
            "pr:acme/netclient#1",
            "PullRequest",
            "pr_reference",
        ),
        (
            "link:commit:abc123:REVERTS:commit:def456",
            "commit:abc123",
            "Commit",
            "REVERTS",
            "commit:def456",
            "Commit",
            "revert_message",
        ),
    ):
        connection.execute(
            "INSERT INTO links (id, repo, source_id, source_type, rel_type, target_id, "
            "target_type, is_direct, derivation_method, confidence, metadata_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                link_id,
                REPO,
                source_id,
                source_type,
                rel_type,
                target_id,
                target_type,
                1,
                derivation,
                1.0,
                "{}",
                "2024-01-01T00:00:00+00:00",
            ),
        )

    connection.execute(
        "INSERT INTO skips (run_id, repo, kind, reason, count, created_at, bound) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("run1", REPO, "issue", "max_ingestion_issues", 5, "2024-01-01T00:00:00+00:00", 2),
    )
    connection.execute(
        "INSERT INTO extraction_runs (run_id, repo, tokens, decisions, evidence, failures, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("run1", REPO, 100, 1, 1, 0, "2024-01-01T00:00:00+00:00"),
    )
    connection.execute(
        "INSERT INTO extraction_sources (run_id, repo, source_id, extraction_version, status, "
        "model, response_format_mode, finish_reason, decisions, tokens, detail, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("run1", REPO, "pr:acme/netclient#1", "v1", "ok", "test-model", "json_schema",
         "stop", 1, 100, "", "2024-01-01T00:00:00+00:00"),
    )
    connection.execute(
        "INSERT INTO rejected_quotes (run_id, repo, source_id, decision_id, decision_summary, "
        "candidate, failed_rung, failure_reason, claim, source_url, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "run1",
            REPO,
            "pr:acme/netclient#1",
            "dec_1",
            "Add a retry loop",
            "The retry loop was added.",
            "complete_quote",
            "could not be completed to a whole sentence",
            "States why.",
            "https://github.com/acme/netclient/pull/1",
            "2024-01-01T00:00:00+00:00",
        ),
    )
    connection.commit()
    cache.close()


def _seeded_store():
    from app.stores.graph_store import InMemoryGraphStore

    store = InMemoryGraphStore()
    store.merge_node("Repository", {"id": REPO, "repo": REPO, "name": "netclient"})
    store.source_texts["pr:acme/netclient#1"] = (
        "The retry loop was added because the timeout was too short for mobile clients."
    )
    return store


@pytest.fixture()
def walkthrough_env(tmp_path):
    for name, value in SECRETS.items():
        import os

        os.environ[name] = value
    db_path = tmp_path / "tiny.sqlite3"
    _build_cache(db_path)
    report = tmp_path / "walkthrough_report.txt"
    return db_path, report


def test_offline_stages_print_their_titles_and_numbers(walkthrough_env, capsys):
    db_path, report = walkthrough_env

    code = walkthrough.main(
        [
            "--stage", "3", "--cache", str(db_path), "--out", str(report),
            "--no-color", "--repo", REPO,
        ],
        store=_seeded_store(),
        settings=Settings(_env_file=None),
    )

    assert code == 0
    text = report.read_text(encoding="utf-8")
    for title in STAGE_TITLES:
        assert title in text
    # A real number from the cache, not a placeholder.
    assert "acme/netclient" in text
    assert "retry loop" in text.lower()


def test_no_environment_secret_is_printed(walkthrough_env, capsys):
    db_path, report = walkthrough_env

    walkthrough.main(
        [
            "--stage", "3", "--cache", str(db_path), "--out", str(report),
            "--no-color", "--repo", REPO,
        ],
        store=_seeded_store(),
        settings=Settings(_env_file=None),
    )

    captured = capsys.readouterr()
    combined = captured.out + captured.err + report.read_text(encoding="utf-8")
    for name, value in SECRETS.items():
        assert value not in combined, f"{name} leaked into the walkthrough output"


def test_the_report_is_plain_text_without_ansi(walkthrough_env, capsys):
    db_path, report = walkthrough_env

    walkthrough.main(
        [
            "--stage", "3", "--cache", str(db_path), "--out", str(report),
            "--no-color", "--repo", REPO,
        ],
        store=_seeded_store(),
        settings=Settings(_env_file=None),
    )

    assert "\x1b[" not in report.read_text(encoding="utf-8")
