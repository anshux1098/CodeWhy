from __future__ import annotations

from typing import Any, Optional

import pytest

from app.services.ingest.github_client import (
    GitHubAuthError,
    RateLimitSnapshot,
)
from scripts.sample_repos import (
    DEFAULT_CANDIDATES,
    build_report,
    collect,
    main,
    parse_candidate,
)


class FakeClient:
    def __init__(self, behaviour: dict[str, Any], rate_limit: Optional[RateLimitSnapshot] = None) -> None:
        self.behaviour = behaviour
        self.rate_limit = rate_limit
        self.queried: list[str] = []

    def query(self, document: str, variables: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        owner = (variables or {}).get("owner", "?")
        name = (variables or {}).get("name", "?")
        repo = f"{owner}/{name}"
        self.queried.append(repo)
        outcome = self.behaviour[repo]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def envelope(repo: str, count: int = 3) -> dict[str, Any]:
    nodes = [
        {
            "number": index,
            "title": f"Change {index}",
            "body": "because the queue backed up" if index == 0 else "small fix",
            "mergedAt": f"2024-0{index + 1}-01T00:00:00Z",
            "reviews": {"totalCount": 1},
            "closingIssuesReferences": {"nodes": []},
            "files": {"nodes": [{"path": "pyproject.toml"}]},
        }
        for index in range(count)
    ]
    return {
        "data": {
            "rateLimit": {"cost": 250, "limit": 5000, "remaining": 4000, "resetAt": None},
            "repository": {
                "nameWithOwner": repo,
                "primaryLanguage": {"name": "Python"},
                "defaultBranchRef": {"name": "main"},
                "diskUsage": 1024,
                "pullRequests": {"totalCount": 500, "nodes": nodes},
            },
        }
    }


def test_default_candidates_are_the_five_from_the_brief() -> None:
    assert DEFAULT_CANDIDATES == (
        "urllib3/urllib3",
        "psf/requests",
        "encode/httpx",
        "pallets/flask",
        "celery/celery",
    )


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        ("psf/requests", ("psf", "requests")),
        ("/psf/requests/", ("psf", "requests")),
        ("not-a-repo", None),
        ("a/b/c", None),
        ("/requests", None),
    ],
)
def test_candidate_parsing(candidate: str, expected: Optional[tuple[str, str]]) -> None:
    assert parse_candidate(candidate) == expected


def test_collect_queries_once_per_candidate_in_order() -> None:
    client = FakeClient({repo: envelope(repo) for repo in ("acme/one", "acme/two")})
    rows, notes = collect(client, ("acme/one", "acme/two"), 50)
    assert client.queried == ["acme/one", "acme/two"]
    assert [row.repo for row in rows] == ["acme/one", "acme/two"]
    assert notes == []
    assert rows[0].sampled == 3


def test_collect_records_a_failure_and_keeps_sampling_the_rest() -> None:
    client = FakeClient(
        {
            "acme/broken": GitHubAuthError("GitHub rejected the credentials"),
            "acme/good": envelope("acme/good"),
        }
    )
    rows, notes = collect(client, ("acme/broken", "acme/good"), 50)
    assert [row.status for row in rows] == [
        rows[0].status,
        "ok",
    ]
    assert rows[0].status.startswith("failed:")
    assert rows[1].status == "ok"
    assert len(notes) == 1
    assert "acme/broken" in notes[0]


def test_collect_skips_a_malformed_candidate_without_calling_the_api() -> None:
    client = FakeClient({})
    rows, notes = collect(client, ("nonsense",), 50)
    assert client.queried == []
    assert rows[0].status.startswith("skipped:")
    assert "not in owner/name form" in notes[0]


def test_collect_stops_when_the_rate_limit_is_low() -> None:
    low = RateLimitSnapshot(cost=200, limit=5000, remaining=12, reset_at=None)
    client = FakeClient({"acme/one": envelope("acme/one")}, rate_limit=low)
    rows, notes = collect(client, ("acme/one", "acme/two"), 50)
    assert client.queried == []
    assert all(row.status.startswith("skipped:") for row in rows)
    assert all("rate limit low" in row.status for row in rows)
    assert len(notes) == 2


def test_collect_keeps_going_while_the_budget_is_healthy() -> None:
    healthy = RateLimitSnapshot(cost=200, limit=5000, remaining=4800, reset_at=None)
    client = FakeClient({"acme/one": envelope("acme/one")}, rate_limit=healthy)
    rows, _ = collect(client, ("acme/one",), 50)
    assert rows[0].status == "ok"
    assert client.queried == ["acme/one"]


def test_report_contains_the_table_definitions_cost_and_notes() -> None:
    client = FakeClient(
        {
            "acme/one": envelope("acme/one"),
            "acme/two": GitHubAuthError("GitHub rejected the credentials"),
        }
    )
    rows, notes = collect(client, ("acme/one", "acme/two"), 50)
    report = build_report(rows, notes, "250", 50)
    assert "| repo | sampled |" in report
    assert "the 50 most recently created merged pull requests" in report
    assert "acme/one" in report
    assert "acme/two" in report
    assert "## Definitions" in report
    assert "Total cost reported by the API" in report
    assert "## Failures and skips" in report
    assert "acme/two" in report.split("## Failures and skips")[1]
    assert "No ranking" in report


def test_report_says_so_when_nothing_failed() -> None:
    client = FakeClient({"acme/one": envelope("acme/one")})
    rows, notes = collect(client, ("acme/one",), 50)
    report = build_report(rows, notes, "250", 50)
    assert "None. Every candidate returned a row." in report


def test_the_sampler_never_writes_a_token_into_the_report() -> None:
    client = FakeClient({"acme/one": envelope("acme/one")})
    rows, notes = collect(client, ("acme/one",), 50)
    report = build_report(rows, notes, "250", 50)
    for marker in ("ghp_", "github_pat_", "Authorization", "bearer "):
        assert marker not in report


def test_dry_run_makes_no_api_call(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("dry run must not touch the network")

    # A dummy token, supplied here rather than inherited from `.env`: the dry run
    # refuses to start without one, so depending on the developer's file would make
    # this test fail on a machine that has none. It is never sent anywhere.
    monkeypatch.setenv("GITHUB_TOKEN", "test-token-not-a-real-secret")
    monkeypatch.setattr("scripts.sample_repos.GitHubGraphQLClient", explode)
    exit_code = main(["--dry-run"])
    assert exit_code == 0
    assert "configuration is valid" in capsys.readouterr().out