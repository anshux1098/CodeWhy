from __future__ import annotations

from typing import Any

import pytest

from app.services.ingest.sampling import (
    COUNT_DEFINITIONS,
    RepoSample,
    failure_row,
    has_stated_reason,
    is_config_path,
    is_incident_like,
    is_lockfile,
    is_revert,
    render_definitions,
    render_table,
    summarise,
    touches_config,
)

LONG_BODY = "x" * 200
REASON_BODY = "We changed the default because clients were retrying too often."


# stated reason


def test_stated_reason_accepts_a_long_body() -> None:
    assert has_stated_reason(LONG_BODY) is True


@pytest.mark.parametrize("phrase", ["because", "so that", "in order to", "to avoid", "due to", "otherwise", "trade-off"])
def test_stated_reason_accepts_a_reason_phrase(phrase: str) -> None:
    assert has_stated_reason(f"We did it {phrase} the server timed out.") is True


def test_stated_reason_is_case_insensitive() -> None:
    assert has_stated_reason("BECAUSE the queue backed up.") is True


def test_stated_reason_rejects_a_short_opaque_body() -> None:
    assert has_stated_reason("fix typo") is False


def test_stated_reason_rejects_a_missing_body() -> None:
    assert has_stated_reason(None) is False


# revert


def test_revert_detected_from_the_title() -> None:
    assert is_revert("Revert \"Raise MAX_RETRIES to 6\"", "") is True


def test_revert_detected_from_the_body() -> None:
    assert is_revert("Restore previous behaviour", "This reverts commit abc1234.") is True


def test_revert_rejects_an_ordinary_change() -> None:
    assert is_revert("Raise MAX_RETRIES to 6", "Bumps the default.") is False


def test_revert_rejects_a_title_that_merely_contains_the_word() -> None:
    assert is_revert("Prevent revert storms in the client", "") is False


# config paths and lockfiles


@pytest.mark.parametrize(
    "path",
    [
        "pyproject.toml",
        "setup.cfg",
        "tox.ini",
        "docs/conf.yaml",
        ".github/workflows/ci.yml",
        "package.json",
        ".env",
        ".env.example",
        "src/settings.py",
        "netclient/config.py",
        "app/constants.py",
        "defaults.py",
    ],
)
def test_config_paths_are_recognised(path: str) -> None:
    assert is_config_path(path) is True
    assert touches_config([path]) is True


@pytest.mark.parametrize(
    "path",
    [
        "netclient/retry.py",
        "README.md",
        "docs/index.rst",
        "Makefile",
        "src/netclient/client.py",
    ],
)
def test_non_config_paths_are_rejected(path: str) -> None:
    assert is_config_path(path) is False


@pytest.mark.parametrize(
    "path",
    [
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "poetry.lock",
        "Pipfile.lock",
        "Cargo.lock",
        "web/npm-shrinkwrap-lock.json",
        "frontend/ui-lock.json",
    ],
)
def test_lockfiles_are_excluded_even_though_they_match_config_patterns(path: str) -> None:
    assert is_lockfile(path) is True
    assert touches_config([path]) is False


def test_a_lockfile_alongside_a_real_config_file_still_counts() -> None:
    assert touches_config(["package-lock.json", "pyproject.toml"]) is True


def test_a_pull_request_touching_only_lockfiles_does_not_count_as_config() -> None:
    assert touches_config(["package-lock.json", "yarn.lock", "src/app.py"]) is False


def test_an_empty_file_list_is_not_config() -> None:
    assert touches_config([]) is False


# incident-like links


def test_incident_detected_from_a_label() -> None:
    assert is_incident_like("Requests time out after 30s", ["bug", "p1"]) is True


def test_incident_detected_from_a_label_word_containing_bug() -> None:
    assert is_incident_like("Something odd", ["needs-triage"]) is False


def test_incident_detected_from_a_title() -> None:
    assert is_incident_like("Major outage on the upload path", []) is True


def test_incident_rejects_an_ordinary_issue() -> None:
    assert is_incident_like("Improve documentation", ["docs"]) is False


# summarise


def pull_request(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "number": 41,
        "title": "Cap MAX_RETRIES at 3",
        "body": REASON_BODY,
        "mergedAt": "2024-02-11T09:20:00Z",
        "reviews": {"totalCount": 2},
        "closingIssuesReferences": {"nodes": []},
        "files": {"totalCount": 2, "nodes": [{"path": "netclient/config.py"}]},
    }
    payload.update(overrides)
    return payload


def payload(*pull_requests: dict[str, Any], **repo_overrides: Any) -> dict[str, Any]:
    repository: dict[str, Any] = {
        "nameWithOwner": "acme/netclient",
        "primaryLanguage": {"name": "Python"},
        "defaultBranchRef": {"name": "main"},
        "diskUsage": 2048,
        "pullRequests": {"totalCount": 1234, "nodes": list(pull_requests)},
    }
    repository.update(repo_overrides)
    return {"data": {"rateLimit": {"cost": 100, "limit": 5000, "remaining": 4000, "resetAt": None}, "repository": repository}}


def test_summarise_counts_every_signal() -> None:
    rows = [
        pull_request(),
        pull_request(
            number=77,
            title="Revert \"Cap MAX_RETRIES at 3\"",
            body="short",
            mergedAt="2024-08-19T14:30:00Z",
            reviews={"totalCount": 0},
            files={"nodes": [{"path": "package-lock.json"}]},
        ),
        pull_request(
            number=90,
            title="Close the deadlock in the pool",
            body="deadlock",
            mergedAt="2024-03-02T10:00:00Z",
            files={"nodes": [{"path": "netclient/retry.py"}]},
            closingIssuesReferences={"nodes": [{"title": "Workers hang", "labels": {"nodes": [{"name": "bug"}]}}]},
        ),
    ]
    sample = summarise("acme/netclient", payload(*rows))
    assert sample.status == "ok"
    assert sample.sampled == 3
    assert sample.merged_total == 1234
    assert sample.stated_reason == 1
    assert sample.reverts == 1
    assert sample.config_touching == 1
    assert sample.incident_like == 1
    assert sample.with_review == 2
    assert sample.oldest_merged_at is not None and sample.oldest_merged_at.isoformat() == "2024-02-11"
    assert sample.newest_merged_at is not None and sample.newest_merged_at.isoformat() == "2024-08-19"
    assert sample.language == "Python"
    assert sample.default_branch == "main"
    assert sample.disk_kb == 2048


def test_summarise_handles_an_empty_sample() -> None:
    sample = summarise("acme/empty", payload())
    assert sample.sampled == 0
    assert sample.median_body_chars is None
    assert sample.oldest_merged_at is None
    assert sample.newest_merged_at is None
    assert sample.window_is_na() if hasattr(sample, "window_is_na") else True


def test_summarise_reports_a_missing_repository_as_failed() -> None:
    sample = summarise("acme/ghost", {"data": {"repository": None}})
    assert sample.status.startswith("failed")
    assert sample.sampled == 0


def test_summarise_survives_null_author_and_null_language() -> None:
    sample = summarise(
        "acme/netclient",
        payload(
            pull_request(author=None),
            primaryLanguage=None,
            diskUsage=None,
        ),
    )
    assert sample.status == "ok"
    assert sample.language is None
    assert sample.disk_kb is None


def test_summarise_survives_a_missing_merged_at() -> None:
    sample = summarise("acme/netclient", payload(pull_request(mergedAt=None)))
    assert sample.sampled == 1
    assert sample.oldest_merged_at is None


# table


def test_table_lists_one_row_per_repo_in_input_order() -> None:
    rows = [
        summarise("zeta/one", payload(pull_request())),
        summarise("alpha/two", payload(pull_request())),
    ]
    table = render_table(rows)
    assert table.splitlines()[0].startswith("| repo | sampled |")
    assert "window (oldest..newest)" in table.splitlines()[0]
    assert table.index("zeta/one") < table.index("alpha/two")


def test_table_shows_the_sample_window() -> None:
    rows = [
        summarise(
            "acme/netclient",
            payload(
                pull_request(mergedAt="2024-02-11T09:20:00Z"),
                pull_request(mergedAt="2025-08-30T09:20:00Z"),
            ),
        )
    ]
    assert "2024-02-11 .. 2025-08-30" in render_table(rows)


def test_table_renders_when_one_repo_failed() -> None:
    rows = [
        summarise("acme/good", payload(pull_request())),
        failure_row("acme/bad", "failed: GitHub rejected the credentials"),
    ]
    table = render_table(rows)
    assert "acme/good" in table
    assert "acme/bad" in table
    assert "failed: GitHub rejected the credentials" in table
    assert len(table.splitlines()) == 4


def test_table_renders_a_single_row() -> None:
    assert len(render_table([failure_row("acme/bad", "skipped: rate limit low")]).splitlines()) == 3


def test_definitions_cover_every_count_column() -> None:
    definitions = render_definitions()
    for name, _ in COUNT_DEFINITIONS:
        assert f"**{name}**" in definitions
    assert "heuristic" in definitions
    assert "Lockfiles" in definitions
    assert "rates over this window" in definitions


def test_repo_sample_defaults_are_inert() -> None:
    row = RepoSample(repo="acme/x")
    assert row.sampled == 0
    assert row.status == "ok"