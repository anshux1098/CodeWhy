from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.providers.llm_provider import MockLLMProvider
from app.schemas.common import SourceType
from app.services.data_source import GraphDataSource, from_source_id
from app.stores.graph_store import InMemoryGraphStore
from scripts.mcp_server import handle_tool_call


def test_from_source_id_supports_doc_commit_discussion_and_incident():
    url, num, kind = from_source_id("doc:acme/app:docs/adr/001.md")
    assert url == "https://github.com/acme/app/blob/main/docs/adr/001.md"
    assert num == 0
    assert kind == SourceType.DOCUMENT

    url, num, kind = from_source_id("commit:acme/app:abcdef1234567")
    assert url == "https://github.com/acme/app/commit/abcdef1234567"
    assert kind == SourceType.COMMIT

    url, num, kind = from_source_id("discussion:acme/app#42")
    assert url == "https://github.com/acme/app/discussions/42"
    assert num == 42
    assert kind == SourceType.ISSUE

    url, num, kind = from_source_id("incident:acme/app:INC-901")
    assert "INC-901" in url
    assert kind == SourceType.ISSUE


def test_prompts_audit_and_mcp_tools():
    store = InMemoryGraphStore()
    store.merge_node("Repository", {
        "id": "acme-app", "repo": "acme-app", "name": "app", "full_name": "acme/app",
        "decisions_count": 2, "entities_count": 2, "pull_requests_count": 5, "commits_count": 10,
    })
    store.merge_node("CodeEntity", {
        "id": "file:acme/app:src/retry.py", "repo": "acme-app", "name": "src/retry.py",
        "path": "src/retry.py", "entity_type": "File", "decision_count": 2,
    })
    store.merge_node("CodeEntity", {
        "id": "file:acme/app:src/unused.py", "repo": "acme-app", "name": "src/unused.py",
        "path": "src/unused.py", "entity_type": "File", "decision_count": 0,
    })
    store.merge_node("Decision", {
        "id": "dec_1", "repo": "acme-app", "summary": "Pin retry budget to 5",
        "rationale": "Avoid timeout cascade", "state": "ACTIVE", "source_id": "pr:acme/app#10",
    })
    store.merge_node("Decision", {
        "id": "dec_2", "repo": "acme-app", "summary": "Old retry budget 3",
        "rationale": "Legacy", "state": "SUPERSEDED", "source_id": "pr:acme/app#5",
    })
    store.merge_relationship("GOVERNS", "dec_1", "file:acme/app:src/retry.py")
    store.merge_relationship("GOVERNS", "dec_2", "file:acme/app:src/retry.py")

    ds = GraphDataSource(cfg=Settings(_env_file=None, offline=True), store=store)
    ds.provider = MockLLMProvider()

    # Pre-stored counts
    repo_resp = ds.get_repository("acme-app")
    assert repo_resp.counts.decisions == 2
    assert repo_resp.counts.commits == 10

    # Dynamic prompts
    prompts = ds.suggest_prompts("acme-app")
    assert len(prompts["prompts"]) >= 2

    # Audit endpoint
    audit = ds.audit_files("acme-app", ["src/retry.py"])
    assert audit["risk_level"] == "HIGH"
    assert audit["active_constraints_count"] == 1
    assert audit["superseded_or_reverted_count"] == 1

    # MCP tool call
    mcp_res = handle_tool_call(ds, "codewhy_before_you_change", {"repository_id": "acme-app", "files": ["src/retry.py"]})
    assert mcp_res["risk_level"] == "HIGH"


def test_api_routes_prompts_and_audit_fixture_mode():
    cfg = Settings(_env_file=None, data_source="fixture", offline=True)
    client = TestClient(create_app(config=cfg))
    repos = client.get("/api/v1/repositories").json()["items"]
    repo_id = repos[0]["id"]
    r1 = client.get(f"/api/v1/repositories/{repo_id}/prompts")
    assert r1.status_code == 200
    assert "prompts" in r1.json()

    r2 = client.post(f"/api/v1/repositories/{repo_id}/audit", json={"files": ["src/urllib3/util/ssl_.py"]})
    assert r2.status_code == 200
    assert "risk_level" in r2.json()
