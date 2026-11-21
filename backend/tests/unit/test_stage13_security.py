from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_security_headers_present_on_api_responses():
    cfg = Settings(_env_file=None, data_source="fixture", offline=True)
    client = TestClient(create_app(config=cfg))
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "max-age=31536000" in (resp.headers.get("Strict-Transport-Security") or "")
