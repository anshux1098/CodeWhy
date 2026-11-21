from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.ingest.auto_targets import auto_discover_targets, is_candidate_source_file
from app.services.ingest.connectors import (
    detect_incident_from_source,
    extract_external_tickets,
    parse_document_metadata,
)
from app.services.ingest.git_probe import InvalidRepositoryError, normalize_repo_slug
from app.services.ingest.github_objects import (
    build_discussions_query,
    build_preflight_query,
    normalise_discussion,
)


def test_normalize_repo_slug_accepts_urls_and_slugs():
    assert normalize_repo_slug("pallets/flask") == "pallets/flask"
    assert normalize_repo_slug("https://github.com/pallets/flask") == "pallets/flask"
    assert normalize_repo_slug("https://github.com/pallets/flask.git") == "pallets/flask"
    assert normalize_repo_slug("https://github.com/pallets/flask/") == "pallets/flask"
    with pytest.raises(InvalidRepositoryError):
        normalize_repo_slug("https://gitlab.com/org/repo")
    with pytest.raises(InvalidRepositoryError):
        normalize_repo_slug("just-one-word")


def test_is_candidate_source_file_filters_noise():
    assert is_candidate_source_file("src/pkg/retry.py") is True
    assert is_candidate_source_file("app/routes.ts") is True
    assert is_candidate_source_file("tests/test_retry.py") is False
    assert is_candidate_source_file("docs/index.md") is False
    assert is_candidate_source_file("package-lock.json") is False
    assert is_candidate_source_file("node_modules/pkg/index.js") is False


def test_auto_discover_targets_zero_config(tmp_path: Path):
    repo_dir = tmp_path / "sample"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "dev@example.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo_dir, check=True)

    pkg = repo_dir / "src" / "app"
    pkg.mkdir(parents=True)
    (pkg / "retry.py").write_text("DEFAULT_RETRIES = 3\nBACKOFF_FACTOR = 0.5\n", encoding="utf-8")
    (repo_dir / "docs" / "adr").mkdir(parents=True)
    (repo_dir / "docs" / "adr" / "001-retry.md").write_text("Status: Accepted\n", encoding="utf-8")
    (repo_dir / "tests").mkdir()
    (repo_dir / "tests" / "test_retry.py").write_text("def test_ok(): pass\n", encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True, capture_output=True)

    out_json = tmp_path / "targets.json"
    targets = auto_discover_targets("acme/sample", repo_dir, top_n=5, save_path=out_json)

    assert targets.repo == "acme/sample"
    assert "src/app/retry.py" in targets.files
    assert "tests/test_retry.py" not in targets.files
    assert "docs" in targets.dirs
    assert {k.name for k in targets.config_keys} == {"DEFAULT_RETRIES", "BACKOFF_FACTOR"}
    assert out_json.exists()


def test_connectors_tickets_adr_and_incidents():
    tickets = extract_external_tickets("Fixes ENG-1420 and CORE-88 over HTTP-2 with UTF-8 and SHA-256")
    assert tickets == ["ENG-1420", "CORE-88"]

    doc = "---\nstatus: Superseded\nsuperseded_by: ADR-004\n---\n# ADR-001\nRelated to ENG-99 and INC-404.\n"
    meta = parse_document_metadata("docs/adr/001-cache.md", doc)
    assert meta.doc_kind == "adr"
    assert meta.status == "Superseded"
    assert meta.superseded_by == "ADR-004"
    assert meta.external_tickets == ["ENG-99"]
    assert meta.incident_keys == ["INC-404"]

    inc = detect_incident_from_source(
        repo="acme/sample",
        source_id="pr:acme/sample#55",
        title="Hotfix SEV-1 outage (INC-501)",
        body="Emergency rollback",
        source_url="https://github.com/acme/sample/pull/55",
    )
    assert inc is not None
    assert inc.key == "INC-501"
    assert inc.severity == "SEV-1"


def test_preflight_and_discussions_queries():
    assert "diskUsage" in build_preflight_query()
    assert "hasDiscussionsEnabled" in build_preflight_query()
    assert "discussions(" in build_discussions_query()
    norm = normalise_discussion({
        "number": 12,
        "title": "RFC: Retry Budget",
        "body": "Proposal",
        "url": "https://github.com/acme/sample/discussions/12",
        "createdAt": "2026-01-01T00:00:00Z",
        "author": {"login": "alice"},
        "category": {"name": "RFCs"},
        "comments": {"nodes": [{"author": {"login": "bob"}, "body": "LGTM", "createdAt": "2026-01-02T00:00:00Z"}]},
    })
    assert norm["number"] == 12
    assert norm["category"] == "RFCs"
    assert len(norm["comments"]) == 1


def test_ingest_endpoint_normalizes_url_and_mode():
    cfg = Settings(data_source="fixture", offline=True)
    client = TestClient(create_app(config=cfg))
    with patch("app.api.routes_ingest._run_ingest_background") as bg:
        resp = client.post(
            "/api/v1/repositories/ingest",
            json={"repo": "https://github.com/pallets/flask.git", "mode": "quick"},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["repo"] == "pallets/flask"
        assert body["mode"] == "quick"
        bg.assert_called_once()
