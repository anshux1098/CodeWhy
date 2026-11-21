# CodeWhy — Recommended Features & Hackathon Add-Ons (`featureaddon.md`)

A prioritized catalog of **Backend**, **Frontend**, **Developer-Workflow (MCP / CLI)**, and **Demo-Polish** features designed to maximize hackathon winning chances and long-term product-market fit.

---

## 1. Backend Features

| # | Feature | Endpoint / Module | Effort | Why It Wins |
| :--- | :--- | :--- | :---: | :--- |
| **B1** | **Hallucination Duel Engine** | `POST /api/v1/repositories/{id}/duel` | `S` | Runs the same question through **(a) a plain ungrounded LLM** and **(b) CodeWhy's 4-gate verified pipeline** in parallel, then cross-checks every sentence of the plain LLM reply against raw repo text to flag unverifiable claims. Turns the 4-gate refusal architecture into an instant 10-second "aha" moment. |
| **B2** | **Line-Level "Why Does This Line Exist?"** | `GET /api/v1/repositories/{id}/blame?path=...&line=...` | `M` | Runs `git blame -L <line>,<line>` on the local clone → maps the commit SHA via `PART_OF` links to its PR → returns the governing `Decision`, `ACTIVE`/`SUPERSEDED` lineage, and character-verified quote. Makes the tagline *"Every line has a history"* literal. |
| **B3** | **Trust Scoreboard Eval Harness** | `GET /api/v1/eval/scoreboard` | `S` | Evaluates a 20–30 question gold benchmark (expected `full` / `partial` / `refusal`) and reports **Citation Precision (100% verbatim)**, **Refusal Accuracy**, **Hallucinations Blocked** (from `rejected_quotes`), and **p50/p95 Latency** / **Tokens per Answer**. |
| **B4** | **Auto-Generated ADR Exporter** | `GET /api/v1/repositories/{id}/adrs/export` | `S` | Compiles verified graph decisions into downloadable `docs/adr/0001-*.md` files (Status `ACTIVE`/`SUPERSEDED`, Context, Decision, Verbatim Evidence, PR links). Repositories without ADRs get formal architecture docs for free. |
| **B5** | **Live Extraction & Quote Verifier Sandbox** | `POST /api/v1/extract/preview` | `S` | Accepts pasted PR markdown, ADR text, or prompt-injection attempts and runs **Injection Sandboxing → LLM Extraction → Character-for-Character Quote Verification** live in ~3 seconds without waiting for a repo clone. |
| **B6** | **Live Paste-a-Repo Ingestion + SSE Progress** | `POST /api/v1/repositories/ingest`<br>`GET /api/v1/repositories/ingest/{run_id}` | `M` | Zero-config repo ingestion (`github.com` only, size/rate-limited) with **1A Auto-Target Discovery**, blobless clone (`--filter=blob:none`), **⚡ Quick Start (~12–15 high-signal PRs)**, and **🔍 Deep Analysis (200 PRs)** streaming live progress. |
| **B7** | **Pre-Flight Impact Check / Diff Analyzer** | `POST /api/v1/repositories/{id}/preflight` | `S` | Takes a proposed change description or `git diff` and checks modified files/constants against `ACTIVE` and `SUPERSEDED` decisions, warning if the edit violates an active invariant or repeats a previously reverted PR. |
| **B8** | **Multi-Source Enterprise Connectors (Roadmap / B.2)** | `backend/app/services/ingest/` | `M–L` | Activates `Document` (in-repo `docs/adr/**/*.md`, Notion/Confluence), `Discussion` (GitHub Discussions), `Issue` (Jira/Linear ticket refs & APIs), and `Incident` (postmortem hotfixes `INC-\d+`) nodes in the knowledge graph. |

---

## 2. Frontend Features

| # | Feature | Where in UI | Effort | Why It Wins |
| :--- | :--- | :--- | :---: | :--- |
| **F1** | **Hallucination Duel Split-Screen** | *Investigate* tab | `S` | Side-by-side comparison: **Plain LLM** (with red *"Unverified Claim"* highlights) vs. **CodeWhy** (green *"Character-Verified Quote"*, PR link, confidence score, or honest refusal with coverage counts). |
| **F2** | **Click-a-Line "Why Blame" Code Viewer** | *Before You Change* tab | `M` | Renders file source code with subtle amber/green markers on decision-governed lines. Clicking line 42 opens the governing decision card, revert lineage, and verbatim quote inline. |
| **F3** | **Per-Answer Engineering Telemetry Chip** | *Investigate* answer header | `S` | Displays real execution proof on every response: `⚡ 1.1s · 740 tokens · 3 verbatim quotes verified` (or `⚡ 42ms · 0 LLM tokens · Refused at Gate G4`). |
| **F4** | **One-Click "Copy AI Guardrails (MCP Brief)"** | *Before You Change* & *Investigate* | `S` | Copies a clean Markdown constraint block containing `ACTIVE` decisions, reverted anti-patterns, verbatim quotes, and `@who_to_ask`, ready to paste into Cursor, Claude Code, or a PR description. |
| **F5** | **Time-Travel Slider on Knowledge Graph** | *Knowledge Graph* tab | `M` | Chronological date scrubber at the bottom of the `@xyflow/react` graph: drag from `2018 → 2026` to watch decisions appear, turn grey when `SUPERSEDED` (e.g., `#3456` → `#3466`), and reactivate on revert-of-revert. |
| **F6** | **Modification Risk Badge & Regression Hotspot Map** | *Before You Change* & *Overview* | `S` | Computes `HIGH RISK` / `CAUTION` / `LOW RISK` badges (with accessible text labels) from active constraint count, revert/supersession count, silent drift, and unanalyzed PR gaps, plus a visual treemap/grid of the riskiest files. |
| **F7** | **Visual Constant/Config Value Evolution Timeline** | *Before You Change* & *Decisions* | `S` | Surfaces AST `ConfigValueChange` transitions as a visual pill timeline (e.g., `MAX_RETRIES: 10 → 5 (PR #41) → 3 (PR #90)`). |
| **F8** | **Verification Gate Receipt & Trust Scoreboard Card** | *Repo Status* tab | `S` | Shows live anti-hallucination telemetry (`53 candidate decisions extracted → 19 unverified blocked → 34 character-verified`), 6-signal confidence explanations, and benchmark accuracy. |
| **F9** | **Dynamic Per-Entity Suggested Questions & Shareable Receipt Permalinks** | *Investigate* & *Decision Drawer* | `S` | Auto-generates context-aware questions when clicking any graph node or file, and lets users copy a shareable permalink to a verified citation receipt. |

---

## 3. Developer Workflow Integrations (MCP & CLI)

| # | Integration | Deliverable | Effort | Why It Wins |
| :--- | :--- | :--- | :---: | :--- |
| **W1** | **`codewhy-mcp` Server for AI Coding Agents** | `scripts/mcp_server.py` | `M` | Exposes `codewhy_before_you_change`, `codewhy_ask_why`, `codewhy_who_to_ask`, and `codewhy_search_entities` over local stdio (or API-key-protected HTTP). **Demo finale:** watch Cursor / Claude Code try to re-enable `ALPN_PROTOCOLS` in `ssl_.py`, call `codewhy_before_you_change`, see `#3466` revert warning, and stop itself. |
| **W2** | **`codewhy check` Pre-Commit / Diff Guard CLI** | `scripts/check_diff.py` | `S` | Reads `git diff --staged`, maps changed files and constants to `ACTIVE`/`SUPERSEDED` decisions, and warns locally before committing (*"You are touching a constraint reverted in #3466"*). Delivers PR-guardrail value without needing a full GitHub App. |

---

## 4. Demo & Pitch Polish Recommendations

1. **Rehearsed 3-Minute Demo Arc:**
   - **Hook (15s):** *Hallucination Duel (`F1`)* — Plain LLM invents a reason; CodeWhy proves it or refuses.
   - **Core Flow (45s):** Ask about `ssl_.py` → verified quote + `who_to_ask` + 6-signal confidence receipt.
   - **Temporal Lineage (30s):** Show `#3456` superseded by `#3466` (or *Time-Travel Slider* `F5`).
   - **Refusal Honesty (20s):** Off-topic / thin-score query → `0 LLM tokens` + exact repo coverage bounds.
   - **Line-Level + MCP Finale (60s):** Click line in *Before You Change* (`F2`) → watch AI coding agent call `codewhy-mcp` (`W1`) and avoid breaking the invariant.
2. **Offline / Resilience Safety Net:**
   - Pre-ingest 2–3 popular repos (`urllib3/urllib3`, `sqlalchemy/alembic`, `psf/requests`) so pasting them is an instant hit.
   - Automatic SQLite `InMemoryGraphStore` fallback when AuraDB is paused/unreachable (`verify_connectivity()`), plus a hidden demo-safe toggle for recorded fixtures if external APIs fail mid-pitch.
3. **Trust & Security Callout:**
   - Highlight **0 LLM tokens on refusal**, **100% verbatim substring verification**, **prompt-injection sandboxing (`<<<UNTRUSTED_REPOSITORY_DATA>>>`)**, and **email redaction** in both the README (with a 20-second GIF of `F1`/`F2`) and pitch deck.
