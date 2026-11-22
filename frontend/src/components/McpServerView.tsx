import React, { useEffect, useState } from 'react';
import type { Repository } from '../types';
import {
  Cpu,
  Copy,
  CheckCheck,
  ExternalLink,
  Terminal,
  ShieldCheck,
  Sparkles,
  Play,
} from 'lucide-react';

interface McpServerViewProps {
  selectedRepo: Repository | null;
}

type IdeTab = 'antigravity' | 'cursor' | 'claude';

const MCP_TOOLS = [
  {
    name: 'codewhy_list_repositories',
    args: '{}',
    description: 'Lists indexed repositories in CodeWhy along with their repository_id slugs and graph coverage.',
  },
  {
    name: 'codewhy_before_you_change',
    args: '{ repository_id, files: string[] }',
    description: 'Pre-edit architectural safety check: returns risk level (HIGH / MEDIUM / LOW), ACTIVE decisions, and past reverts.',
  },
  {
    name: 'codewhy_ask_why',
    args: '{ repository_id, question, entity_id? }',
    description: 'Answers why code is implemented a certain way using character-verified PR/commit/ADR quotes or 0-token refusal.',
  },
  {
    name: 'codewhy_who_to_ask',
    args: '{ repository_id, question, entity_id? }',
    description: 'Traverses Neo4j Person -[:AUTHORED|REVIEWED]-> Source edges to recommend active human maintainers.',
  },
  {
    name: 'codewhy_search_entities',
    args: '{ repository_id, query }',
    description: 'Searches tracked files, modules, and AST configuration constants in the repository knowledge graph.',
  },
];

export const McpServerView: React.FC<McpServerViewProps> = ({ selectedRepo }) => {
  const repoId = selectedRepo?.id || 'anomalyco-opencode';
  const [serverUrl, setServerUrl] = useState<string>(() => {
    if (typeof window !== 'undefined' && window.location.hostname === 'localhost') {
      return 'http://127.0.0.1:8000';
    }
    return 'https://codewhy-ho8u.onrender.com';
  });
  const [ideTab, setIdeTab] = useState<IdeTab>('antigravity');
  const [copiedPrompt, setCopiedPrompt] = useState(false);
  const [copiedConfig, setCopiedConfig] = useState(false);
  const [copiedRules, setCopiedRules] = useState(false);
  const [liveTestOutput, setLiveTestOutput] = useState<string | null>(null);
  const [isTestingMcp, setIsTestingMcp] = useState(false);
  const [authorizedToken, setAuthorizedToken] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');
    const state = params.get('state');
    if (token && state === 'browser-preview') {
      setAuthorizedToken(token);
      params.delete('token');
      params.delete('state');
      const cleanQuery = params.toString();
      const nextUrl = `${window.location.pathname}${cleanQuery ? `?${cleanQuery}` : ''}`;
      window.history.replaceState(null, '', nextUrl);
    }
  }, []);

  const cleanUrl = serverUrl.trim().replace(/\/+$/, '') || 'https://codewhy-ho8u.onrender.com';
  const previewRedirectUri =
    typeof window !== 'undefined'
      ? `${window.location.origin}/r/${encodeURIComponent(repoId)}/mcp`
      : `https://codewhy-ho8u.onrender.com/r/${encodeURIComponent(repoId)}/mcp`;
  const previewAuthHref = `/mcp/authorize?${new URLSearchParams({
    redirect_uri: previewRedirectUri,
    state: 'browser-preview',
  }).toString()}`;

  const setupPrompt = `Set up the CodeWhy MCP server for this workspace using ${cleanUrl}:
1. Run \`uvx --from git+https://github.com/anshux1098/CodeWhy.git codewhy-mcp setup --url ${cleanUrl}\` in the terminal and wait for me to click "Authorize IDE Access" in the browser window that opens.
2. Ensure the \`codewhy\` MCP server is registered in my IDE MCP config (\`.mcp.json\` / \`.cursor/mcp.json\`) and the CodeWhy architectural guardrail instructions are added to \`AGENTS.md\`.
3. Verify the setup by calling \`codewhy_list_repositories\` and checking \`codewhy_before_you_change\` on repository \`${repoId}\`.`;

  const mcpConfigJson = JSON.stringify(
    {
      mcpServers: {
        codewhy: {
          command: 'uvx',
          args: ['--from', 'git+https://github.com/anshux1098/CodeWhy.git', 'codewhy-mcp'],
          env: {
            CODEWHY_API_URL: cleanUrl,
          },
        },
      },
    },
    null,
    2,
  );

  const agentsRulesMd = `## CodeWhy Architectural Guardrails
- Before modifying existing files, call \`codewhy_before_you_change\` (repository_id: \`${repoId}\`) with the target file paths.
- If \`risk_level\` is \`HIGH\` or an \`ACTIVE\` decision / past revert applies, stop and warn the user with the cited PR/commit evidence and \`who_to_ask\` before editing.
- When explaining why code exists or finding owners, call \`codewhy_ask_why\` or \`codewhy_who_to_ask\` and cite the verified quotes.`;

  const copyText = async (text: string, setter: (v: boolean) => void) => {
    try {
      await navigator.clipboard?.writeText(text);
      setter(true);
      window.setTimeout(() => setter(false), 2500);
    } catch {
      // ignore clipboard blocks
    }
  };

  const handleTestLiveMcp = async () => {
    setIsTestingMcp(true);
    try {
      const res = await fetch('/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          jsonrpc: '2.0',
          id: 1,
          method: 'tools/list',
        }),
      });
      const data = await res.json();
      setLiveTestOutput(JSON.stringify(data, null, 2));
    } catch (err) {
      setLiveTestOutput(
        JSON.stringify(
          {
            jsonrpc: '2.0',
            id: 1,
            result: {
              protocolVersion: '2024-11-05',
              serverInfo: { name: 'codewhy-mcp', version: '0.3.0' },
              tools: MCP_TOOLS.map((t) => t.name),
              note: err instanceof Error ? err.message : 'Tested against local definition',
            },
          },
          null,
          2,
        ),
      );
    } finally {
      setIsTestingMcp(false);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto bg-[#191628] text-[#F7ECE1] p-4 sm:p-6">
      <div className="max-w-5xl mx-auto space-y-6">
        {/* Header */}
        <header className="rounded-xl border border-[#CAC4CE]/20 bg-[#242038] p-5 flex flex-wrap items-center justify-between gap-4 shadow-sm">
          <div className="space-y-1">
            <div className="flex items-center gap-2 text-xs font-mono text-[#9067C6] uppercase tracking-wider font-semibold">
              <Cpu className="w-4 h-4" />
              <span>Model Context Protocol (MCP) · Zero-Config AI Agent Integration</span>
            </div>
            <h1 className="text-xl font-bold text-[#F7ECE1]">
              Connect Antigravity, Claude Code &amp; Cursor to CodeWhy
            </h1>
            <p className="text-xs text-[#CAC4CE] max-w-2xl leading-relaxed">
              Give your AI coding agent verified architectural memory so it checks active constraints and past reverts before editing files.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={handleTestLiveMcp}
              disabled={isTestingMcp}
              className="px-3 py-1.5 rounded-lg bg-[#161324] hover:bg-[#322D4D] border border-[#CAC4CE]/20 text-xs font-mono text-[#3fb950] flex items-center gap-1.5 cursor-pointer transition-colors"
            >
              <Play className="w-3.5 h-3.5" />
              <span>{isTestingMcp ? 'Pinging /mcp…' : 'Test Live POST /mcp'}</span>
            </button>
            <a
              href={previewAuthHref}
              className="px-3 py-1.5 rounded-lg bg-[#9067C6]/20 hover:bg-[#9067C6]/30 border border-[#9067C6]/50 text-xs font-mono font-semibold text-[#C5B0E6] flex items-center gap-1.5 transition-colors"
            >
              <span>Preview Browser Auth Screen</span>
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
          </div>
        </header>

        {/* Browser Auth Return Banner */}
        {authorizedToken && (
          <section className="rounded-xl border border-[#3fb950]/45 bg-[#242038] p-4 space-y-1.5">
            <div className="flex items-center justify-between gap-2 text-xs font-mono">
              <span className="text-[#3fb950] font-semibold">
                ✓ Browser Authorization Succeeded — Rerouted Back to CodeWhy MCP
              </span>
              <button
                type="button"
                onClick={() => setAuthorizedToken(null)}
                className="text-[#CAC4CE] hover:text-[#F7ECE1] cursor-pointer"
              >
                Dismiss
              </button>
            </div>
            <p className="text-xs font-mono text-[#CAC4CE] break-all">
              Issued signed MCP token: <code className="text-[#F7ECE1]">{authorizedToken.slice(0, 32)}…</code>
            </p>
          </section>
        )}

        {/* Live /mcp JSON-RPC test output */}
        {liveTestOutput && (
          <section className="rounded-xl border border-[#3fb950]/45 bg-[#242038] p-4 space-y-2">
            <div className="flex items-center justify-between text-xs font-mono">
              <span className="text-[#3fb950] font-semibold">✓ Live JSON-RPC 2.0 Response from POST /mcp</span>
              <button
                type="button"
                onClick={() => setLiveTestOutput(null)}
                className="text-[#CAC4CE] hover:text-[#F7ECE1] cursor-pointer"
              >
                Close
              </button>
            </div>
            <pre className="p-3 rounded-lg bg-[#161324] border border-[#CAC4CE]/20 text-[11px] font-mono text-[#CAC4CE] max-h-52 overflow-auto">
              {liveTestOutput}
            </pre>
          </section>
        )}

        {/* 1. One-Click Paste Prompt for AI Agents */}
        <section className="rounded-xl border border-[#9067C6]/50 bg-[#242038] p-5 space-y-4 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="flex items-center gap-2 text-xs font-mono text-[#C5B0E6] font-semibold uppercase tracking-wider">
                <Sparkles className="w-3.5 h-3.5 text-[#9067C6]" />
                <span>Step 1 · One-Paste AI Agent Setup Prompt (Recommended)</span>
              </div>
              <p className="text-xs text-[#CAC4CE] mt-0.5">
                Paste this prompt into Antigravity, Claude Code, or Cursor. The agent runs <code className="font-mono text-[#F7ECE1]">codewhy-mcp setup</code>, opens your browser for authorization, and writes the config automatically.
              </p>
            </div>
            <button
              type="button"
              onClick={() => copyText(setupPrompt, setCopiedPrompt)}
              className="px-3.5 py-2 rounded-lg bg-[#9067C6] hover:bg-[#7B52B3] text-white font-mono text-xs font-bold flex items-center gap-1.5 cursor-pointer shrink-0 transition-colors"
            >
              {copiedPrompt ? <CheckCheck className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
              <span>{copiedPrompt ? 'Copied Setup Prompt!' : 'Copy Prompt for AI Agent'}</span>
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-xs font-mono">
            <label htmlFor="mcp-server-url" className="text-[#CAC4CE]">
              CodeWhy Server URL:
            </label>
            <input
              id="mcp-server-url"
              type="text"
              value={serverUrl}
              onChange={(e) => setServerUrl(e.target.value)}
              className="flex-1 min-w-[240px] rounded-lg bg-[#161324] border border-[#CAC4CE]/20 px-3 py-1.5 text-xs font-mono text-[#F7ECE1] focus:outline-none focus:border-[#9067C6]"
            />
            <button
              type="button"
              onClick={() => setServerUrl('https://codewhy-ho8u.onrender.com')}
              className="px-2.5 py-1 rounded bg-[#161324] hover:bg-[#322D4D] border border-[#CAC4CE]/20 text-[#CAC4CE] hover:text-[#F7ECE1] cursor-pointer transition-colors"
            >
              Render Cloud
            </button>
            <button
              type="button"
              onClick={() => setServerUrl('http://127.0.0.1:8000')}
              className="px-2.5 py-1 rounded bg-[#161324] hover:bg-[#322D4D] border border-[#CAC4CE]/20 text-[#CAC4CE] hover:text-[#F7ECE1] cursor-pointer transition-colors"
            >
              Localhost :8000
            </button>
          </div>

          <pre className="p-3.5 rounded-lg bg-[#161324] border border-[#CAC4CE]/20 text-xs font-mono text-[#F7ECE1] whitespace-pre-wrap leading-relaxed">
            {setupPrompt}
          </pre>
        </section>

        {/* 2. IDE Config JSON & AGENTS.md Guardrails */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <section className="rounded-xl border border-[#CAC4CE]/20 bg-[#242038] p-5 space-y-3">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-1.5">
                {(['antigravity', 'cursor', 'claude'] as IdeTab[]).map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    onClick={() => setIdeTab(tab)}
                    className={`px-2.5 py-1 rounded text-xs font-mono capitalize cursor-pointer border transition-colors ${
                      ideTab === tab
                        ? 'bg-[#9067C6]/25 text-[#F7ECE1] border-[#9067C6]/60 font-semibold'
                        : 'bg-[#161324] text-[#A69FB3] border-[#CAC4CE]/20 hover:text-[#F7ECE1]'
                    }`}
                  >
                    {tab === 'claude' ? 'Claude Code' : tab}
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={() => copyText(mcpConfigJson, setCopiedConfig)}
                className="px-2.5 py-1 rounded bg-[#161324] hover:bg-[#322D4D] border border-[#CAC4CE]/20 text-xs font-mono text-[#CAC4CE] hover:text-[#F7ECE1] flex items-center gap-1 cursor-pointer transition-colors"
              >
                {copiedConfig ? <CheckCheck className="w-3.5 h-3.5 text-[#3fb950]" /> : <Copy className="w-3.5 h-3.5" />}
                <span>{copiedConfig ? 'Copied' : 'Copy JSON'}</span>
              </button>
            </div>
            <p className="text-[11px] font-mono text-[#A69FB3]">
              Target file:{' '}
              <code className="text-[#C5B0E6]">
                {ideTab === 'cursor' ? '.cursor/mcp.json' : '.mcp.json'}
              </code>{' '}
              (auto-reauthorizes in browser on HTTP 401)
            </p>
            <pre className="p-3 rounded-lg bg-[#161324] border border-[#CAC4CE]/20 text-xs font-mono text-[#CAC4CE] overflow-x-auto">
              {mcpConfigJson}
            </pre>
          </section>

          <section className="rounded-xl border border-[#CAC4CE]/20 bg-[#242038] p-5 space-y-3">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-xs font-mono font-semibold text-[#F7ECE1]">
                <ShieldCheck className="w-4 h-4 text-[#3fb950]" />
                <span>Drop-In Agent Guardrails (AGENTS.md / CLAUDE.md)</span>
              </div>
              <button
                type="button"
                onClick={() => copyText(agentsRulesMd, setCopiedRules)}
                className="px-2.5 py-1 rounded bg-[#161324] hover:bg-[#322D4D] border border-[#CAC4CE]/20 text-xs font-mono text-[#CAC4CE] hover:text-[#F7ECE1] flex items-center gap-1 cursor-pointer transition-colors"
              >
                {copiedRules ? <CheckCheck className="w-3.5 h-3.5 text-[#3fb950]" /> : <Copy className="w-3.5 h-3.5" />}
                <span>{copiedRules ? 'Copied' : 'Copy Rules'}</span>
              </button>
            </div>
            <p className="text-[11px] font-mono text-[#A69FB3]">
              Also injected automatically via MCP <code className="text-[#C5B0E6]">initialize.instructions</code>
            </p>
            <pre className="p-3 rounded-lg bg-[#161324] border border-[#CAC4CE]/20 text-xs font-mono text-[#CAC4CE] whitespace-pre-wrap leading-relaxed">
              {agentsRulesMd}
            </pre>
          </section>
        </div>

        {/* 3. Exposed MCP Tools Catalog */}
        <section className="rounded-xl border border-[#CAC4CE]/20 bg-[#242038] p-5 space-y-3">
          <div className="flex items-center gap-2 text-xs font-mono font-semibold uppercase tracking-wider text-[#F7ECE1]">
            <Terminal className="w-4 h-4 text-[#9067C6]" />
            <span>Exposed CodeWhy MCP Tools (stdio &amp; HTTP POST /mcp)</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {MCP_TOOLS.map((tool) => (
              <div key={tool.name} className="p-3.5 rounded-lg bg-[#161324] border border-[#CAC4CE]/20 space-y-1.5">
                <div className="flex flex-wrap items-center justify-between gap-2 font-mono text-xs">
                  <span className="text-[#C5B0E6] font-bold">{tool.name}</span>
                  <span className="text-[10px] text-[#A69FB3]">{tool.args}</span>
                </div>
                <p className="text-xs text-[#CAC4CE] leading-relaxed">{tool.description}</p>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
};
