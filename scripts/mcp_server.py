#!/usr/bin/env python3
"""CodeWhy MCP Server (stdio JSON-RPC 2.0) — Roadmap A.1.

Exposes CodeWhy architectural memory tools to Cursor, Claude Code, Copilot, and Antigravity:
  - codewhy_before_you_change
  - codewhy_ask_why
  - codewhy_who_to_ask
  - codewhy_search_entities
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import Settings
from app.schemas.ask import AskRequest
from app.services.data_source import get_data_source

TOOLS: list[dict[str, Any]] = [
    {
        "name": "codewhy_before_you_change",
        "description": "Audit changed file paths for active architectural constraints, past reverts, and risk level before modifying code.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository_id": {"type": "string", "description": "Repository slug e.g. urllib3-urllib3"},
                "files": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["repository_id", "files"],
        },
    },
    {
        "name": "codewhy_ask_why",
        "description": "Ask CodeWhy why code is implemented a certain way, backed by verbatim verified quotes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository_id": {"type": "string"},
                "question": {"type": "string"},
                "entity_id": {"type": "string"},
            },
            "required": ["repository_id", "question"],
        },
    },
    {
        "name": "codewhy_who_to_ask",
        "description": "Find the recommended maintainers/reviewers for a question or code entity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository_id": {"type": "string"},
                "question": {"type": "string"},
                "entity_id": {"type": "string"},
            },
            "required": ["repository_id", "question"],
        },
    },
    {
        "name": "codewhy_search_entities",
        "description": "Search tracked files, modules, and configuration keys in a repository.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository_id": {"type": "string"},
                "query": {"type": "string"},
            },
            "required": ["repository_id", "query"],
        },
    },
]


def handle_tool_call(source: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    repo_id = str(arguments.get("repository_id") or "")
    if name == "codewhy_before_you_change":
        files = [str(f) for f in (arguments.get("files") or [])]
        if hasattr(source, "audit_files"):
            return source.audit_files(repo_id, files)
        return {"repository_id": repo_id, "files_checked": len(files), "risk_level": "LOW", "decisions": []}
    if name == "codewhy_ask_why":
        res = source.ask(
            repo_id,
            AskRequest(question=str(arguments.get("question") or ""), entity_id=arguments.get("entity_id")),
        )
        return res.model_dump(mode="json")
    if name == "codewhy_who_to_ask":
        res = source.ask(
            repo_id,
            AskRequest(question=str(arguments.get("question") or ""), entity_id=arguments.get("entity_id")),
        )
        return {"entity": res.entity.model_dump(mode="json") if res.entity else None, "who_to_ask": [w.model_dump(mode="json") for w in res.who_to_ask]}
    if name == "codewhy_search_entities":
        res = source.search_entities(repo_id, str(arguments.get("query") or ""))
        return res.model_dump(mode="json")
    raise ValueError(f"Unknown tool: {name}")


def main() -> int:
    source = get_data_source(Settings())
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        req = json.loads(line)
        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}
        try:
            if method == "initialize":
                result: Any = {"protocolVersion": "2024-11-05", "serverInfo": {"name": "codewhy-mcp", "version": "0.1.0"}, "capabilities": {"tools": {}}}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                payload = handle_tool_call(source, params.get("name", ""), params.get("arguments") or {})
                result = {"content": [{"type": "text", "text": json.dumps(payload, indent=2)}]}
            else:
                result = {}
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}) + "\n")
            sys.stdout.flush()
        except Exception as exc:  # noqa: BLE001
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(exc)}}) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
