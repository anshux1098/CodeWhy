"""HTTP JSON-RPC 2.0 endpoint (`POST /mcp`) and lightweight browser login (`/mcp/authorize`)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.api.deps import get_source
from app.services.data_source import DataSource
from app.services.mcp_handler import handle_jsonrpc_message

router = APIRouter(tags=["mcp"])

_PROCESS_SECRET = secrets.token_hex(32)
_DEFAULT_TOKEN_TTL_SECONDS = 30 * 24 * 3600


def _signing_secret() -> bytes:
    raw = os.environ.get("CODEWHY_MCP_TOKEN", "").strip() or os.environ.get("CODEWHY_MCP_SECRET", "").strip()
    return (raw or _PROCESS_SECRET).encode("utf-8")


def issue_mcp_token(ttl_seconds: int = _DEFAULT_TOKEN_TTL_SECONDS) -> str:
    payload = json.dumps({"exp": int(time.time()) + ttl_seconds, "nonce": secrets.token_hex(8)}, separators=(",", ":"))
    b64 = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    sig = hmac.new(_signing_secret(), b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"cw_{b64}.{sig}"


def verify_mcp_token(token: str) -> bool:
    expected_static = os.environ.get("CODEWHY_MCP_TOKEN", "").strip()
    if expected_static and hmac.compare_digest(token, expected_static):
        return True
    if not token.startswith("cw_") or "." not in token:
        return False
    b64, sig = token[3:].split(".", 1)
    expected_sig = hmac.new(_signing_secret(), b64.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return False
    padded = b64 + "=" * (-len(b64) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return False
    return int(data.get("exp", 0)) >= int(time.time())


def _is_valid_localhost_redirect(redirect_uri: str) -> bool:
    parsed = urlsplit(redirect_uri)
    return (
        parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost"}
        and parsed.port is not None
        and parsed.path == "/callback"
        and not parsed.query
        and not parsed.fragment
    )


def _check_mcp_token(authorization: str | None) -> None:
    expected = os.environ.get("CODEWHY_MCP_TOKEN", "").strip()
    require_auth = os.environ.get("CODEWHY_MCP_REQUIRE_AUTH", "").strip().lower() == "true"
    if not expected and not require_auth:
        return
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token or not verify_mcp_token(token):
        raise HTTPException(status_code=401, detail="Invalid or missing MCP bearer token")


@router.get("/mcp/authorize", include_in_schema=False)
async def mcp_authorize_page(
    redirect_uri: str = Query(...),
    state: str = Query(...),
) -> HTMLResponse:
    if not _is_valid_localhost_redirect(redirect_uri):
        raise HTTPException(status_code=400, detail="redirect_uri must be http://127.0.0.1:<port>/callback or http://localhost:<port>/callback")
    safe_redirect = html.escape(redirect_uri, quote=True)
    safe_state = html.escape(state, quote=True)
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Authorize CodeWhy MCP</title>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; background: #0b1020; color: #e5e7eb; display: grid; place-items: center; min-height: 100vh; margin: 0; }}
    .card {{ background: #131a2e; border: 1px solid #26314d; border-radius: 12px; padding: 28px; max-width: 440px; width: 90%; box-shadow: 0 12px 32px rgba(0,0,0,.4); }}
    h1 {{ margin: 0 0 8px; font-size: 20px; }}
    p {{ color: #9ca3af; font-size: 14px; line-height: 1.5; }}
    ul {{ color: #cbd5e1; font-size: 13px; padding-left: 18px; margin: 14px 0 20px; }}
    button {{ width: 100%; background: #3b82f6; color: #fff; border: 0; border-radius: 8px; padding: 11px 16px; font-size: 14px; font-weight: 600; cursor: pointer; }}
    button:hover {{ background: #2563eb; }}
    .target {{ font-family: ui-monospace, monospace; font-size: 12px; color: #93c5fd; word-break: break-all; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Authorize CodeWhy MCP</h1>
    <p>An AI coding client on your machine is requesting access to your CodeWhy architectural memory tools:</p>
    <ul>
      <li><code>codewhy_list_repositories</code> &amp; <code>codewhy_search_entities</code></li>
      <li><code>codewhy_before_you_change</code> (pre-edit guardrail check)</li>
      <li><code>codewhy_ask_why</code> &amp; <code>codewhy_who_to_ask</code></li>
    </ul>
    <p class="target">Callback: {safe_redirect}</p>
    <form method="post" action="/mcp/authorize">
      <input type="hidden" name="redirect_uri" value="{safe_redirect}" />
      <input type="hidden" name="state" value="{safe_state}" />
      <button type="submit">Authorize IDE Access</button>
    </form>
  </div>
</body>
</html>"""
    return HTMLResponse(content=page)


@router.post("/mcp/authorize", include_in_schema=False)
async def mcp_authorize_submit(request: Request) -> RedirectResponse:
    raw = (await request.body()).decode("utf-8", errors="replace")
    form = parse_qs(raw)
    redirect_uri = (form.get("redirect_uri") or [""])[0]
    state = (form.get("state") or [""])[0]
    if not _is_valid_localhost_redirect(redirect_uri) or not state:
        raise HTTPException(status_code=400, detail="Invalid redirect_uri or state")
    token = issue_mcp_token()
    qs = urlencode({"token": token, "state": state})
    return RedirectResponse(url=f"{redirect_uri}?{qs}", status_code=303)


@router.post("/mcp", include_in_schema=False)
async def mcp_endpoint(
    request: Request,
    authorization: str | None = Header(default=None),
    source: DataSource = Depends(get_source),
) -> Response:
    _check_mcp_token(authorization)
    try:
        body: Any = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse(
            status_code=200,
            content={"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
        )

    if isinstance(body, list):
        responses = []
        for item in body:
            if isinstance(item, dict):
                resp = handle_jsonrpc_message(source, item)
                if resp is not None:
                    responses.append(resp)
        if not responses:
            return Response(status_code=202)
        return JSONResponse(status_code=200, content=responses)

    if not isinstance(body, dict):
        return JSONResponse(
            status_code=200,
            content={"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}},
        )

    resp = handle_jsonrpc_message(source, body)
    if resp is None:
        return Response(status_code=202)
    return JSONResponse(status_code=200, content=resp)
