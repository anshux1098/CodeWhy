# CodeWhy MCP Setup

Connect **Antigravity**, **Claude Code**, **Cursor**, or any MCP-compatible coding agent to CodeWhy's architectural memory.

---

## 1. Zero-Config Setup (Paste This Prompt Into Your AI Agent)

Copy and paste this single prompt into **Antigravity, Claude Code, or Cursor**:

```text
Set up the CodeWhy MCP server for this workspace using https://codewhy-ho8u.onrender.com:
1. Run `uvx --from git+https://github.com/anshux1098/CodeWhy.git codewhy-mcp setup --url https://codewhy-ho8u.onrender.com` in the terminal and wait for me to click "Authorize IDE Access" in the browser window that opens.
2. Ensure the `codewhy` MCP server is registered in my IDE MCP config (`.mcp.json` / `.cursor/mcp.json`) and the CodeWhy architectural guardrail instructions are added to `AGENTS.md`.
3. Verify the setup by calling `codewhy_list_repositories` and showing me the indexed repositories.
```

*(What `codewhy-mcp setup` does automatically: opens `/mcp/authorize` in your browser, saves the signed token to `~/.codewhy/credentials.json`, merges `"codewhy"` into `.mcp.json` and `.cursor/mcp.json`, and appends the CodeWhy guardrail rules to `AGENTS.md`. Also, if a token ever expires, `codewhy-mcp` automatically pops open the browser on `401` and retries the call.)*

---

## 2. Manual CLI Commands (Optional)

### One-Time Browser Login + Workspace Setup
```bash
uvx --from git+https://github.com/anshux1098/CodeWhy.git codewhy-mcp setup --url https://codewhy-ho8u.onrender.com
```

Or from a local clone against a local backend:
```powershell
.venv\Scripts\python.exe scripts/mcp_server.py setup --url http://127.0.0.1:8000
```

---

## 3. IDE `mcpServers` Config (Written Automatically by `setup`)

```json
{
  "mcpServers": {
    "codewhy": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/anshux1098/CodeWhy.git", "codewhy-mcp"],
      "env": {
        "CODEWHY_API_URL": "https://codewhy-ho8u.onrender.com"
      }
    }
  }
}
```
