from __future__ import annotations

import io
import json
import sys

from fastapi.testclient import TestClient

from app.config import Settings
from app.fixtures.dataset import REPOSITORY_ID
from app.fixtures.source import FixtureDataSource
from app.main import create_app
from app.mcp_server import (
    HttpProxyDataSource,
    _resolve_source,
    load_credentials,
    main,
    run_setup,
    save_credentials,
)
from app.services.mcp_handler import SERVER_INSTRUCTIONS, TOOLS, handle_jsonrpc_message


def test_initialize_negotiates_version_and_ping() -> None:
    ds = FixtureDataSource(Settings(_env_file=None))
    init = handle_jsonrpc_message(
        ds,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
    )
    assert init is not None
    assert init["result"]["protocolVersion"] == "2025-03-26"
    assert init["result"]["serverInfo"]["name"] == "codewhy-mcp"
    assert init["result"]["instructions"] == SERVER_INSTRUCTIONS
    assert "prompts" in init["result"]["capabilities"]

    prompts_list = handle_jsonrpc_message(ds, {"jsonrpc": "2.0", "id": 10, "method": "prompts/list"})
    assert prompts_list is not None
    assert [p["name"] for p in prompts_list["result"]["prompts"]] == ["codewhy-guardrails", "codewhy-explain"]

    prompt_get = handle_jsonrpc_message(
        ds,
        {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "prompts/get",
            "params": {"name": "codewhy-guardrails", "arguments": {"repository_id": "acme-app", "files": "src/retry.py"}},
        },
    )
    assert prompt_get is not None
    assert "codewhy_before_you_change" in prompt_get["result"]["messages"][0]["content"]["text"]

    ping = handle_jsonrpc_message(ds, {"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert ping == {"jsonrpc": "2.0", "id": 2, "result": {}}


def test_notifications_return_none() -> None:
    ds = FixtureDataSource(Settings(_env_file=None))
    assert handle_jsonrpc_message(ds, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert handle_jsonrpc_message(ds, {"jsonrpc": "2.0", "id": None, "method": "notifications/cancelled"}) is None


def test_unknown_method_and_tool_error_shape() -> None:
    ds = FixtureDataSource(Settings(_env_file=None))
    unknown = handle_jsonrpc_message(ds, {"jsonrpc": "2.0", "id": 3, "method": "resources/list"})
    assert unknown is not None
    assert unknown["error"]["code"] == -32601

    tool_err = handle_jsonrpc_message(
        ds,
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "no_such_tool", "arguments": {}}},
    )
    assert tool_err is not None
    assert tool_err["result"]["isError"] is True
    assert "Unknown tool" in tool_err["result"]["content"][0]["text"]


def test_tools_list_and_all_five_tools() -> None:
    ds = FixtureDataSource(Settings(_env_file=None))
    listed = handle_jsonrpc_message(ds, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert listed is not None
    names = [t["name"] for t in listed["result"]["tools"]]
    assert names == [t["name"] for t in TOOLS]
    assert "codewhy_list_repositories" in names

    repos_resp = handle_jsonrpc_message(
        ds,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "codewhy_list_repositories", "arguments": {}}},
    )
    assert repos_resp is not None
    assert repos_resp["result"]["isError"] is False
    repos_json = json.loads(repos_resp["result"]["content"][0]["text"])
    assert repos_json["items"][0]["id"] == REPOSITORY_ID

    entities_resp = handle_jsonrpc_message(
        ds,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "codewhy_search_entities", "arguments": {"repository_id": REPOSITORY_ID, "query": "ssl"}},
        },
    )
    assert entities_resp is not None
    assert entities_resp["result"]["isError"] is False
    entities_payload = json.loads(entities_resp["result"]["content"][0]["text"])
    assert "entities" in entities_payload

    ask_resp = handle_jsonrpc_message(
        ds,
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "codewhy_ask_why",
                "arguments": {"repository_id": REPOSITORY_ID, "question": "Why is ALPN_PROTOCOLS configured in ssl_.py?"},
            },
        },
    )
    assert ask_resp is not None
    assert ask_resp["result"]["isError"] is False

    who_resp = handle_jsonrpc_message(
        ds,
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "codewhy_who_to_ask",
                "arguments": {"repository_id": REPOSITORY_ID, "question": "Who knows ssl_.py?"},
            },
        },
    )
    assert who_resp is not None
    assert "who_to_ask" in json.loads(who_resp["result"]["content"][0]["text"])


def test_http_proxy_and_fastapi_mcp_endpoint(monkeypatch) -> None:
    cfg = Settings(_env_file=None, data_source="fixture", offline=True)
    app = create_app(config=cfg)
    tc = TestClient(app)

    # 1. Test HttpProxyDataSource against TestClient
    proxy = HttpProxyDataSource("http://testserver", client=tc)  # type: ignore[arg-type]
    listed = handle_jsonrpc_message(
        proxy,
        {"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": {"name": "codewhy_list_repositories", "arguments": {}}},
    )
    assert listed is not None
    assert json.loads(listed["result"]["content"][0]["text"])["items"][0]["id"] == REPOSITORY_ID

    audit = handle_jsonrpc_message(
        proxy,
        {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {"name": "codewhy_before_you_change", "arguments": {"repository_id": REPOSITORY_ID, "files": ["src/urllib3/util/ssl_.py"]}},
        },
    )
    assert audit is not None
    assert audit["result"]["isError"] is False

    # 2. Test POST /mcp endpoint directly
    r_notif = tc.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r_notif.status_code == 202

    r_list = tc.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r_list.status_code == 200
    assert len(r_list.json()["result"]["tools"]) == 5

    # 3. Optional bearer token guard
    monkeypatch.setenv("CODEWHY_MCP_TOKEN", "secret-token")
    assert tc.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401
    assert (
        tc.post(
            "/mcp",
            headers={"Authorization": "Bearer secret-token"},
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        ).status_code
        == 200
    )


def test_stdio_main_isolates_stdout_and_handles_parse_error(monkeypatch) -> None:
    monkeypatch.delenv("CODEWHY_API_URL", raising=False)
    monkeypatch.setenv("DATA_SOURCE", "fixture")
    monkeypatch.setenv("OFFLINE", "true")

    fake_stdin = io.StringIO(
        "not-json\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 99, "method": "ping"}) + "\n"
    )
    fake_stdout = io.StringIO()
    fake_stderr = io.StringIO()

    monkeypatch.setattr(sys, "stdin", fake_stdin)
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    monkeypatch.setattr(sys, "stderr", fake_stderr)

    rc = main([])
    assert rc == 0
    lines = [json.loads(line) for line in fake_stdout.getvalue().strip().splitlines()]
    assert len(lines) == 2
    assert lines[0]["error"]["code"] == -32700
    assert lines[1] == {"jsonrpc": "2.0", "id": 99, "result": {}}


def test_browser_authorize_flow_and_credentials_store(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CODEWHY_MCP_REQUIRE_AUTH", "true")
    monkeypatch.setenv("CODEWHY_MCP_SECRET", "unit-test-signing-secret")
    cfg = Settings(_env_file=None, data_source="fixture", offline=True)
    tc = TestClient(create_app(config=cfg))

    # Reject non-localhost redirect_uri (open-redirect protection)
    bad = tc.get("/mcp/authorize", params={"redirect_uri": "https://evil.example/callback", "state": "s1"})
    assert bad.status_code == 400

    # Render consent page for valid localhost callback
    good = tc.get("/mcp/authorize", params={"redirect_uri": "http://127.0.0.1:54321/callback", "state": "s1"})
    assert good.status_code == 200
    assert "Authorize CodeWhy MCP" in good.text

    # Submit consent form -> 303 redirect with signed token
    submit = tc.post(
        "/mcp/authorize",
        data={"redirect_uri": "http://127.0.0.1:54321/callback", "state": "s1"},
        follow_redirects=False,
    )
    assert submit.status_code == 303
    location = submit.headers["location"]
    assert location.startswith("http://127.0.0.1:54321/callback?")
    assert "state=s1" in location
    from urllib.parse import parse_qs, urlsplit
    token = parse_qs(urlsplit(location).query)["token"][0]
    assert token.startswith("cw_")

    # Signed token authenticates POST /mcp
    assert tc.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401
    assert (
        tc.post("/mcp", headers={"Authorization": f"Bearer {token}"}, json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code
        == 200
    )

    # Save & resolve credentials
    creds_file = tmp_path / "credentials.json"
    save_credentials("http://127.0.0.1:8000/", token, path=creds_file)
    loaded = load_credentials(creds_file)
    assert loaded["api_url"] == "http://127.0.0.1:8000"
    assert loaded["token"] == token

    monkeypatch.delenv("CODEWHY_API_URL", raising=False)
    monkeypatch.delenv("DATA_SOURCE", raising=False)
    src = _resolve_source(credentials_path=creds_file)
    assert isinstance(src, HttpProxyDataSource)
    assert src.base_url == "http://127.0.0.1:8000"


def test_setup_writes_mcp_configs_and_agents_md_idempotently(tmp_path) -> None:
    # Pre-seed an existing server in .mcp.json to verify merge preserves it
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"existing": {"command": "node"}}}), encoding="utf-8")

    rc = run_setup("https://codewhy-ho8u.onrender.com/", workspace=tmp_path, skip_login=True)
    assert rc == 0

    mcp_cfg = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert "existing" in mcp_cfg["mcpServers"]
    assert mcp_cfg["mcpServers"]["codewhy"]["env"]["CODEWHY_API_URL"] == "https://codewhy-ho8u.onrender.com"

    cursor_cfg = json.loads((tmp_path / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert "codewhy" in cursor_cfg["mcpServers"]

    agents_text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "codewhy_before_you_change" in agents_text

    # Running a second time does not duplicate the AGENTS.md guardrail block
    run_setup("https://codewhy-ho8u.onrender.com", workspace=tmp_path, skip_login=True)
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8").count("## CodeWhy Architectural Guardrails") == 1


def test_http_proxy_auto_reauthorizes_on_401(tmp_path) -> None:
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        auth = request.headers.get("Authorization", "")
        if auth != "Bearer fresh-token":
            import httpx as _httpx
            return _httpx.Response(401, json={"detail": "Unauthorized"})
        import httpx as _httpx
        return _httpx.Response(200, json={"items": [{"id": REPOSITORY_ID}]})

    import httpx as _httpx
    transport = _httpx.MockTransport(handler)
    client = _httpx.Client(base_url="https://codewhy.example", transport=transport)
    creds_file = tmp_path / "credentials.json"

    def fake_login(url: str, path):
        save_credentials(url, "fresh-token", path=path)
        return 0

    proxy = HttpProxyDataSource(
        "https://codewhy.example",
        token="expired-token",
        client=client,
        credentials_path=creds_file,
        auto_login=True,
        login_fn=fake_login,
    )
    res = proxy.list_repositories()
    assert res["items"][0]["id"] == REPOSITORY_ID
    assert calls == 2
