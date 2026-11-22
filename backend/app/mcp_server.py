"""CodeWhy MCP Server (`codewhy-mcp` CLI + stdio JSON-RPC 2.0 + browser login & setup).

Usage:
  codewhy-mcp                        # Run stdio MCP server (local or proxied via CODEWHY_API_URL / saved login)
  codewhy-mcp login --url <url>      # Open browser to authorize and cache token in ~/.codewhy/credentials.json
  codewhy-mcp setup --url <url>      # Authorize in browser + write .mcp.json, .cursor/mcp.json, and AGENTS.md
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import secrets
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable, Optional, Sequence
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from app.config import Settings
from app.schemas.ask import AskRequest
from app.services.data_source import get_data_source
from app.services.mcp_handler import TOOLS, handle_jsonrpc_message, handle_tool_call

CREDENTIALS_PATH = Path.home() / ".codewhy" / "credentials.json"
DEFAULT_REMOTE_URL = "https://codewhy-ho8u.onrender.com"
DEFAULT_GIT_PACKAGE = "git+https://github.com/anshux1098/CodeWhy.git"

AGENTS_GUARDRAIL_HEADER = "## CodeWhy Architectural Guardrails"
AGENTS_GUARDRAIL_BLOCK = f"""{AGENTS_GUARDRAIL_HEADER}
- Before modifying existing files, call `codewhy_before_you_change` with the target file paths.
- If `risk_level` is `HIGH` or an `ACTIVE` decision / past revert applies, stop and warn the user with the cited PR/commit evidence and `who_to_ask` before editing.
- When explaining why code exists or finding owners, call `codewhy_ask_why` or `codewhy_who_to_ask` and cite the verified quotes.
"""

__all__ = [
    "CREDENTIALS_PATH",
    "DEFAULT_GIT_PACKAGE",
    "DEFAULT_REMOTE_URL",
    "HttpProxyDataSource",
    "TOOLS",
    "handle_jsonrpc_message",
    "handle_tool_call",
    "load_credentials",
    "main",
    "run_browser_login",
    "run_setup",
    "save_credentials",
]


def load_credentials(path: Path = CREDENTIALS_PATH) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_credentials(api_url: str, token: str, path: Path = CREDENTIALS_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "api_url": api_url.rstrip("/"),
        "token": token,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


class HttpProxyDataSource:
    """Lightweight DataSource-compatible proxy backed by a running CodeWhy HTTP API.

    Automatically triggers browser authorization on HTTP 401 when `auto_login=True`.
    """

    def __init__(
        self,
        base_url: str,
        *,
        token: str = "",
        client: httpx.Client | None = None,
        credentials_path: Path = CREDENTIALS_PATH,
        auto_login: bool = True,
        login_fn: Optional[Callable[[str, Path], int]] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.credentials_path = credentials_path
        self.auto_login = auto_login
        self._login_fn = login_fn
        self._client = client or httpx.Client(base_url=self.base_url, timeout=60.0)
        self._token = token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def _try_reauthorize(self) -> bool:
        if not self.auto_login:
            return False
        if self._login_fn is not None:
            rc = self._login_fn(self.base_url, self.credentials_path)
        else:
            rc = run_browser_login(self.base_url, credentials_path=self.credentials_path)
        if rc != 0:
            return False
        creds = load_credentials(self.credentials_path)
        new_token = creds.get("token", "")
        if not new_token:
            return False
        self._token = new_token
        return True

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = self._client.get(f"/api/v1{path}", params=params, headers=self._headers())
        if resp.status_code == 401 and self._try_reauthorize():
            resp = self._client.get(f"/api/v1{path}", params=params, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        resp = self._client.post(f"/api/v1{path}", json=payload, headers=self._headers())
        if resp.status_code == 401 and self._try_reauthorize():
            resp = self._client.post(f"/api/v1{path}", json=payload, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def list_repositories(self) -> dict[str, Any]:
        return self._get("/repositories")

    def audit_files(self, repository_id: str, files: Sequence[str]) -> dict[str, Any]:
        return self._post(f"/repositories/{repository_id}/audit", {"files": list(files)})

    def ask(self, repository_id: str, request: AskRequest) -> dict[str, Any]:
        return self._post(f"/repositories/{repository_id}/ask", request.model_dump(mode="json", exclude_none=True))

    def search_entities(self, repository_id: str, query: str) -> dict[str, Any]:
        return self._get(f"/repositories/{repository_id}/entities", params={"q": query})


def run_browser_login(
    api_url: str,
    *,
    credentials_path: Path = CREDENTIALS_PATH,
    open_browser: bool = True,
    timeout_seconds: float = 180.0,
) -> int:
    """Open the browser to authorize CodeWhy MCP and cache the returned token locally."""
    clean_url = api_url.rstrip("/")
    expected_state = secrets.token_urlsafe(24)
    result: dict[str, str] = {}
    done = threading.Event()

    class _CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlsplit(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            qs = parse_qs(parsed.query)
            got_state = (qs.get("state") or [""])[0]
            got_token = (qs.get("token") or [""])[0]
            if not got_token or not hmac.compare_digest(got_state, expected_state):
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"<h1>Authorization failed</h1><p>Invalid state or missing token.</p>")
                return
            result["token"] = got_token
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h1>CodeWhy MCP Authorized</h1><p>You can close this tab and return to your IDE.</p>")
            done.set()

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

    server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    port = server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}/callback"
    auth_url = f"{clean_url}/mcp/authorize?{urlencode({'redirect_uri': redirect_uri, 'state': expected_state})}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        print(f"Opening browser to authorize CodeWhy MCP:\n  {auth_url}", file=sys.stderr, flush=True)
        if open_browser:
            webbrowser.open(auth_url)
        deadline = time.monotonic() + timeout_seconds
        while not done.is_set() and time.monotonic() < deadline:
            done.wait(timeout=0.25)
    finally:
        server.shutdown()
        server.server_close()

    token = result.get("token")
    if not token:
        print("Authorization timed out or failed.", file=sys.stderr)
        return 1
    saved = save_credentials(clean_url, token, path=credentials_path)
    print(f"Authorized! Credentials saved to {saved}", file=sys.stderr)
    return 0


def _merge_mcp_config_file(config_path: Path, api_url: str, git_package: str = DEFAULT_GIT_PACKAGE) -> None:
    existing: dict[str, Any] = {}
    if config_path.is_file():
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, ValueError):
            existing = {}
    servers = existing.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
        existing["mcpServers"] = servers
    servers["codewhy"] = {
        "command": "uvx",
        "args": ["--from", git_package, "codewhy-mcp"],
        "env": {"CODEWHY_API_URL": api_url.rstrip("/")},
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")


def _ensure_agents_guardrails(workspace: Path) -> Path:
    agents_md = workspace / "AGENTS.md"
    if agents_md.is_file():
        content = agents_md.read_text(encoding="utf-8", errors="replace")
        if AGENTS_GUARDRAIL_HEADER not in content:
            sep = "\n" if content.endswith("\n") else "\n\n"
            agents_md.write_text(content + sep + AGENTS_GUARDRAIL_BLOCK, encoding="utf-8")
    else:
        agents_md.write_text("# Agent Instructions\n\n" + AGENTS_GUARDRAIL_BLOCK, encoding="utf-8")
    return agents_md


def run_setup(
    api_url: str,
    *,
    workspace: Path = Path("."),
    credentials_path: Path = CREDENTIALS_PATH,
    open_browser: bool = True,
    skip_login: bool = False,
) -> int:
    """One-command setup: browser login + write .mcp.json, .cursor/mcp.json, and AGENTS.md."""
    clean_url = api_url.rstrip("/")
    if not skip_login:
        rc = run_browser_login(clean_url, credentials_path=credentials_path, open_browser=open_browser)
        if rc != 0:
            return rc

    ws = workspace.resolve()
    mcp_json = ws / ".mcp.json"
    cursor_mcp_json = ws / ".cursor" / "mcp.json"
    _merge_mcp_config_file(mcp_json, clean_url)
    _merge_mcp_config_file(cursor_mcp_json, clean_url)
    agents_md = _ensure_agents_guardrails(ws)

    print(f"Updated MCP configs:\n  - {mcp_json}\n  - {cursor_mcp_json}\n  - {agents_md}", file=sys.stderr)
    return 0


def _resolve_source(credentials_path: Path = CREDENTIALS_PATH) -> Any:
    env_url = os.environ.get("CODEWHY_API_URL", "").strip()
    env_token = os.environ.get("CODEWHY_MCP_TOKEN", "").strip()
    creds = load_credentials(credentials_path)
    if env_url:
        token = env_token or (creds.get("token", "") if creds.get("api_url") == env_url.rstrip("/") else "")
        return HttpProxyDataSource(env_url, token=token, credentials_path=credentials_path)
    if not os.environ.get("DATA_SOURCE") and creds.get("api_url") and creds.get("token"):
        return HttpProxyDataSource(creds["api_url"], token=creds["token"], credentials_path=credentials_path)
    return get_data_source(Settings())


def main(argv: Optional[Sequence[str]] = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list and args_list[0] == "login":
        parser = argparse.ArgumentParser(prog="codewhy-mcp login")
        parser.add_argument("--url", default=os.environ.get("CODEWHY_API_URL") or DEFAULT_REMOTE_URL)
        parser.add_argument("--no-browser", action="store_true")
        parsed = parser.parse_args(args_list[1:])
        return run_browser_login(parsed.url, open_browser=not parsed.no_browser)

    if args_list and args_list[0] == "setup":
        parser = argparse.ArgumentParser(prog="codewhy-mcp setup")
        parser.add_argument("--url", default=os.environ.get("CODEWHY_API_URL") or DEFAULT_REMOTE_URL)
        parser.add_argument("--workspace", default=".")
        parser.add_argument("--no-browser", action="store_true")
        parser.add_argument("--skip-login", action="store_true")
        parsed = parser.parse_args(args_list[1:])
        return run_setup(
            parsed.url,
            workspace=Path(parsed.workspace),
            open_browser=not parsed.no_browser,
            skip_login=parsed.skip_login,
        )

    # Reserve the original stdout exclusively for JSON-RPC frames so library logs
    # or progress bars (e.g., sentence-transformers / tqdm) cannot corrupt stdio.
    jsonrpc_out = sys.stdout
    sys.stdout = sys.stderr

    source = _resolve_source()
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            err_resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}}
            jsonrpc_out.write(json.dumps(err_resp) + "\n")
            jsonrpc_out.flush()
            continue

        if not isinstance(req, dict):
            err_resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
            jsonrpc_out.write(json.dumps(err_resp) + "\n")
            jsonrpc_out.flush()
            continue

        req_id = req.get("id")
        try:
            response = handle_jsonrpc_message(source, req)
            if response is not None:
                jsonrpc_out.write(json.dumps(response) + "\n")
                jsonrpc_out.flush()
        except Exception as exc:  # noqa: BLE001
            err_resp = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(exc)}}
            jsonrpc_out.write(json.dumps(err_resp) + "\n")
            jsonrpc_out.flush()
    return 0
