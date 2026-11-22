"""Shared Model Context Protocol (MCP) tool definitions and JSON-RPC 2.0 handler.

Used by both the local stdio server (`scripts/mcp_server.py`) and the FastAPI
HTTP endpoint (`POST /mcp`).
"""
from __future__ import annotations

import json
from typing import Any, Optional

from app.schemas.ask import AskRequest

DEFAULT_PROTOCOL_VERSION = "2024-11-05"
SUPPORTED_PROTOCOL_VERSIONS = frozenset({"2024-11-05", "2025-03-26"})

SERVER_INSTRUCTIONS = (
    "CodeWhy provides verified architectural memory (decisions, past reverts, verbatim PR/commit "
    "evidence, and maintainer recommendations) for indexed repositories.\n"
    "Follow this workflow when working on a codebase:\n"
    "1. If you do not know the repository_id slug, call `codewhy_list_repositories` first.\n"
    "2. Before modifying existing files, call `codewhy_before_you_change` with the target file paths. "
    "If `risk_level` is HIGH or ACTIVE decisions / past reverts apply, pause and warn the user with "
    "the cited PR/commit evidence before editing.\n"
    "3. When asked why code is written a certain way or who owns a module, call `codewhy_ask_why` "
    "or `codewhy_who_to_ask` and cite only the returned verified evidence."
)

PROMPTS: list[dict[str, Any]] = [
    {
        "name": "codewhy-guardrails",
        "description": "Audit target files for active architectural constraints and past reverts before editing.",
        "arguments": [
            {"name": "repository_id", "description": "Repository slug (e.g. anomalyco-opencode)", "required": True},
            {"name": "files", "description": "Comma-separated relative file paths to check", "required": True},
        ],
    },
    {
        "name": "codewhy-explain",
        "description": "Explain why a file, symbol, or config key exists using verified PR/commit quotes.",
        "arguments": [
            {"name": "repository_id", "description": "Repository slug (e.g. anomalyco-opencode)", "required": True},
            {"name": "question", "description": "Question about the code or design decision", "required": True},
        ],
    },
]

TOOLS: list[dict[str, Any]] = [
    {
        "name": "codewhy_list_repositories",
        "description": "List repositories indexed in CodeWhy along with their repository_id slugs and decision/entity counts.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "codewhy_before_you_change",
        "description": "Audit changed file paths for active architectural constraints, past reverts, and risk level before modifying code.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository_id": {"type": "string", "description": "Repository slug e.g. anomalyco-opencode"},
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


def _dump(value: Any) -> dict[str, Any]:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def handle_tool_call(source: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute one MCP tool against a CodeWhy DataSource or HTTP proxy."""
    if name == "codewhy_list_repositories":
        return _dump(source.list_repositories())

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
        return _dump(res)

    if name == "codewhy_who_to_ask":
        res = source.ask(
            repo_id,
            AskRequest(question=str(arguments.get("question") or ""), entity_id=arguments.get("entity_id")),
        )
        data = _dump(res)
        return {
            "entity": data.get("entity"),
            "who_to_ask": data.get("who_to_ask") or [],
        }

    if name == "codewhy_search_entities":
        res = source.search_entities(repo_id, str(arguments.get("query") or ""))
        return _dump(res)

    raise ValueError(f"Unknown tool: {name}")


def handle_jsonrpc_message(source: Any, req: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Process one JSON-RPC 2.0 request. Returns None for notifications (no response)."""
    method = req.get("method")
    has_id = "id" in req and req.get("id") is not None
    if not has_id or (isinstance(method, str) and method.startswith("notifications/")):
        return None

    req_id = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": version,
                "serverInfo": {"name": "codewhy-mcp", "version": "0.3.0"},
                "capabilities": {"tools": {}, "prompts": {}},
                "instructions": SERVER_INSTRUCTIONS,
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"prompts": PROMPTS}}

    if method == "prompts/get":
        prompt_name = params.get("name", "")
        args = params.get("arguments") or {}
        if prompt_name == "codewhy-guardrails":
            repo_id = args.get("repository_id", "<repository_id>")
            files = args.get("files", "<file_paths>")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "description": "Pre-edit architectural guardrails check",
                    "messages": [
                        {
                            "role": "user",
                            "content": {
                                "type": "text",
                                "text": (
                                    f"Before editing {files} in repository `{repo_id}`, call "
                                    f"`codewhy_before_you_change` with repository_id={repo_id!r} and "
                                    "summarize any ACTIVE decisions, past reverts, and recommended reviewers."
                                ),
                            },
                        }
                    ],
                },
            }
        if prompt_name == "codewhy-explain":
            repo_id = args.get("repository_id", "<repository_id>")
            question = args.get("question", "<question>")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "description": "Explain code using verified engineering history",
                    "messages": [
                        {
                            "role": "user",
                            "content": {
                                "type": "text",
                                "text": (
                                    f"Call `codewhy_ask_why` on repository `{repo_id}` with question: "
                                    f"{question!r}. Cite the verified PR/commit quotes in your explanation."
                                ),
                            },
                        }
                    ],
                },
            }
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32602, "message": f"Unknown prompt: {prompt_name}"},
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments") or {}
        try:
            payload = handle_tool_call(source, tool_name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
                    "isError": False,
                },
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Error: {exc}"}],
                    "isError": True,
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }
