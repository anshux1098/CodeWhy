from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.fixtures.dataset import REPOSITORY_ID
from app.main import create_app


def _client() -> TestClient:
    cfg = Settings(_env_file=None, data_source="fixture", offline=True)
    return TestClient(create_app(config=cfg))


def test_hallucination_duel_endpoint() -> None:
    tc = _client()
    r = tc.post(
        f"/api/v1/repositories/{REPOSITORY_ID}/duel",
        json={"question": "Why was the retry limit changed in retry.py?"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["repository_id"] == REPOSITORY_ID
    assert body["plain_llm"]["unverified_claims_count"] >= 1
    assert "codewhy" in body
    assert "verdict" in body


def test_line_why_blame_endpoint() -> None:
    tc = _client()
    r = tc.get(
        f"/api/v1/repositories/{REPOSITORY_ID}/blame",
        params={"path": "pkg/retry.py", "line": 3},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["repository_id"] == REPOSITORY_ID
    assert body["total_lines"] >= 2
    assert isinstance(body["lines"], list)
    assert body["selected_line"] is not None


def test_preflight_diff_and_constant_timeline_endpoint() -> None:
    tc = _client()
    diff = (
        "diff --git a/pkg/retry.py b/pkg/retry.py\n"
        "--- a/pkg/retry.py\n"
        "+++ b/pkg/retry.py\n"
        "@@ -1,3 +1,3 @@\n"
        "-MAX_RETRIES = 3\n"
        "+MAX_RETRIES = 10\n"
    )
    r = tc.post(
        f"/api/v1/repositories/{REPOSITORY_ID}/preflight",
        json={"diff": diff, "files": ["pkg/retry.py"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["risk_badge"] in ("HIGH RISK", "CAUTION", "LOW RISK")
    assert "MAX_RETRIES" in body["constants_touched"]
    assert isinstance(body["hotspots"], list)
    assert isinstance(body["constant_timeline"], list)


def test_adrs_export_endpoint() -> None:
    tc = _client()
    r = tc.get(f"/api/v1/repositories/{REPOSITORY_ID}/adrs/export")
    assert r.status_code == 200
    body = r.json()
    assert body["total_adrs"] >= 1
    assert body["files"][0]["path"].startswith("docs/adr/0001-")
    assert "Verbatim Verified Evidence" in body["combined_markdown"]


def test_trust_scoreboard_endpoint() -> None:
    tc = _client()
    r = tc.get("/api/v1/eval/scoreboard")
    assert r.status_code == 200
    body = r.json()
    assert body["citation_precision_pct"] == 100.0
    assert body["tokens_on_refusal"] == 0
    assert len(body["benchmark_cases"]) == 5
