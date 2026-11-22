#!/usr/bin/env python3
"""Compatibility entry point for `python scripts/mcp_server.py`."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.mcp_server import (  # noqa: E402, F401
    CREDENTIALS_PATH,
    DEFAULT_GIT_PACKAGE,
    DEFAULT_REMOTE_URL,
    HttpProxyDataSource,
    TOOLS,
    handle_jsonrpc_message,
    handle_tool_call,
    load_credentials,
    main,
    run_browser_login,
    run_setup,
    save_credentials,
)

if __name__ == "__main__":
    raise SystemExit(main())
