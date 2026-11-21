# CodeWhy — Hackathon Checkpoint Submission

**Every line has a history. Find the reasoning, not just the code.**

---

## 1. Where We Are Today

### What Works in Our Prototype Today
* **End-to-End Decision Archaeology Pipeline (Real Repo Tested on `urllib3/urllib3`):**
  * **Ingestion & Cache (`scripts/ingest.py`, `data/ingest.sqlite3`):** Clones repositories locally with `git log --follow` rename tracking and batches GitHub GraphQL fetches (`20 PRs/query`), redacting emails and caching **294 PRs** and **735 commits** in SQLite.
  * **Deterministic Linking & Noise Filtering:** Extracts `PART_OF` (`120`), `REVERTS` (`7`), and `CONTAINS` (`4`) links without LLM calls; flags **70 noisy PRs** (bots, formatting, dependency bumps) while protecting revert targets.
  * **Prompt-Sandboxed Extraction & Verbatim Quote Gate (`scripts/extract.py`, `quote_check.py`):** Isolates untrusted repository text (`<<<UNTRUSTED_REPOSITORY_DATA>>>`), extracts **53 candidate decisions** across **96 sources**, and enforces **100% character-for-character substring verification**—dropping 19 unverified candidates to yield **34 verified decisions** (`33 ACTIVE`, `1 SUPERSEDED`).
* **Knowledge Graph & Supersession (`Neo4j AuraDB` + `InMemoryGraphStore`):**
  * Live Neo4j AuraDB graph (~**2,056 nodes, 524 relationships** across 8 node labels and 7 relationship types) with 384-dim `all-MiniLM-L6-v2` embeddings.
  * **Rule 1 Supersession Live:** Automatically resolves revert lineage (e.g., `PR #3456` marked `SUPERSEDED` by revert `PR #3466` on `src/urllib3/util/ssl_.py`).
* **4-Gate Refusal Backend (`FastAPI /api/v1`) & 6-View Frontend (`React 19 + Vite 8 + @xyflow/react`):**
  * Enforces **G1 (Entity Resolution) → G2 (Governing Decision) → G3 (Verified Quote) → G4 (Similarity ≥ 0.55)** before invoking the LLM—returning zero-token refusals with exact coverage telemetry when evidence is missing.
  * Frozen OpenAPI contract (`contract/openapi.v1.json`) with compatibility tests, 1,076 backend tests, and a 6-view UI (*Overview*, *Investigate*, *Decisions*, *Before You Change*, *Knowledge Graph*, *Repo Status*) displaying verified citations, confidence breakdowns, and honest fixture/data-source banners.

### What Is Mocked, Hardcoded, or Missing Today
* **Mocked / Offline Fallbacks:** `DATA_SOURCE` defaults to `"fixture"` when unconfigured, and `VERCEL` mode defaults to `ALLOW_MOCK_PROVIDERS=true` + `OFFLINE=true` (`MockLLMProvider` + SHA-256 hash embeddings), whereas the live demo runs with `DATA_SOURCE=graph` against real Neo4j AuraDB + Gemini.
* **Hardcoded:** Confidence signals `provenance` (`0.8` / `0.6`) and `temporal_consistency` (`1.0`) in `answer.py`; `LIBRARY_SOURCE_PREFIX = "src/urllib3/"` in `extraction.py`; `ALLOWED_REPOS` in `RepositorySelectorModal.tsx`; `src/urllib3/connection.py` exclusion in `DecisionHistoryView.tsx`; static demo questions in `api.ts`.
* **Missing / Broken Today:**
  * `Person` nodes and `AUTHORED`/`REVIEWED` edges are not yet built in `rebuild_graph.py`, leaving `who_to_ask` empty (`[]`) in live `/ask` responses; `source_author` and `decision_date` are also `NULL` in SQLite `decisions` rows.
  * `config_keys` and `config_value_changes` tables in SQLite have `0` rows, and Supersession Rules 2, 3, and 3b do not fire on live data yet.
  * `data/ingest.sqlite3` contains only `urllib3/urllib3`; there is no live UI paste-repo ingestion flow yet.
  * 50/59 frontend Vitest tests currently fail (`ReferenceError: React is not defined` in `vitest.config.ts`); `/ask` re-embeds decisions in a loop (~18–32s warm), `/entities` (~4.1s) and `/repositories` (~1.6s) suffer N+1 Neo4j queries, graph rebuild takes ~5 minutes, `/health/dependencies` only checks non-empty env strings, and there is no automatic SQLite fallback if AuraDB Free pauses after 72h idle.

---

## 2. Where We Will Be by 12 PM on 22 November

By **12 PM on 22 November**, CodeWhy will be a **fast, multi-repo, zero-mock, agent-integrated Decision Archaeology platform** with the following exact features, flows, and integrations working end-to-end:

### A. Hardened Core Engine, Resilience & Speed Optimizations
* **Multi-Repo & Multi-Source Pipeline (`urllib3/urllib3` + `sqlalchemy/alembic` + Pasted Repos):** Target-configurable entity scoping (`targets/*.json`), scoped SQLite counts, and both core repos pre-ingested in `data/ingest.sqlite3` and Neo4j AuraDB—with all hardcoded UI filters removed. Activates `Document` (ADRs), `Discussion`, `Issue`, and `Incident` nodes alongside PRs and Commits.
* **Live Contributor Graph & `who_to_ask` (`Person`, `AUTHORED`, `REVIEWED`):** Fixed `source_author` and `decision_date` extraction + SQLite backfill; `Person` nodes and `AUTHORED`/`REVIEWED` edges built in Neo4j; `who_to_ask` returning up to 3 ranked active authors and reviewers on full answers, partials, and scored refusals.
* **Dynamic Confidence & All 4 Supersession Rules:** Dynamic `provenance` (`0.80–1.00`) and `temporal_consistency` (`0.50–1.00`) signals; `config_keys` / `config_value_changes` wired into SQLite and `source_metadata` passed into `rebuild_graph.py` so **Rules 2, 3, and 3b** fire alongside Rule 1.
* **Sub-Second API & <10s Graph Rebuild:** Batched Cypher `UNWIND` writes (`rebuild_graph.py` cut from **~5 min → <10s**), pre-stored node counts killing N+1 queries (`/repositories` **<50 ms**, `/entities` **<80 ms**), single-query embedding against stored `d["embedding"]` (`>90%` faster retrieval), and a per-repo LRU `/ask` cache (**<15 ms** on repeat queries).
* **Resilient Production Deployment & Green Test Suite:** FastAPI hosted on a persistent container service with pre-warmed `all-MiniLM-L6-v2` embeddings + Vercel frontend; explicit `driver.verify_connectivity()` check at startup with automatic SQLite `InMemoryGraphStore` fallback if AuraDB Free pauses; **all 59/59 frontend Vitest tests and 1,076+ backend tests passing**.

### B. End-to-End Backend & Frontend User Flows
1. **Hallucination Duel Flow (`POST /api/v1/repositories/{id}/duel` + Split-Screen UI):** Side-by-side comparison of an **ungrounded plain LLM** (unverifiable claims flagged) vs. **CodeWhy** (character-verified PR quotes, confidence receipt, or zero-token refusal).
2. **Line-Level "Why Does This Line Exist?" Flow (`GET /api/v1/repositories/{id}/blame` + Click-a-Line UI):** Click any line in *Before You Change* to trace `git blame` → `PART_OF` PR → governing `Decision` → `ACTIVE`/`SUPERSEDED` lineage and verbatim quote.
3. **Pre-Flight Impact Check, Risk Badges & Constant Evolution Timeline:** Diff analyzer (`POST /preflight`) checking proposed changes against `ACTIVE` and `SUPERSEDED` decisions; `HIGH RISK` / `CAUTION` / `LOW RISK` badges + Regression Hotspot Map; visual AST `ConfigValueChange` timeline (`MAX_RETRIES: 10 → 5 → 3`).
4. **Time-Travel Graph Slider & Dynamic Per-Entity Exploration:** Date scrubber (`2018 → 2026`) on the `@xyflow/react` Knowledge Graph showing decisions appearing, turning grey when `SUPERSEDED`, and reactivating on revert-of-revert, plus dynamic per-entity questions and shareable citation receipt permalinks.
5. **Live Paste-a-Repo Ingestion & Extraction Sandbox:** Zero-config hotspot discovery + blobless clone + **⚡ Quick Start** / **🔍 Deep Analysis** modes (`POST /repositories/ingest`), plus `POST /api/v1/extract/preview` to test extraction, injection sandboxing, and quote verification live in ~3s.
6. **Auto-ADR Exporter & Trust Scoreboard:** One-click export of verified decisions to `docs/adr/0001-*.md`, per-answer telemetry chip (`⚡ 1.1s · 740 tokens · 3 verbatim quotes verified`), and a *Repo Status* Trust Scoreboard (`GET /api/v1/eval/scoreboard`) reporting **100% Citation Precision**, **Refusal Accuracy**, **Hallucinations Blocked**, and **p50/p95 Latency**.

### C. Live Developer Workflow Integrations
* **`codewhy-mcp` Server (`scripts/mcp_server.py`):** Exposes `codewhy_before_you_change`, `codewhy_ask_why`, `codewhy_who_to_ask`, and `codewhy_search_entities` to **Cursor, Claude Code, and Antigravity**—demonstrating an AI coding agent querying CodeWhy before editing `ssl_.py` and stopping itself from re-introducing reverted `PR #3466`, paired with a one-click **"Copy AI Guardrails (MCP Brief)"** button.
* **`codewhy check` Pre-Commit CLI (`scripts/check_diff.py`):** Reads `git diff --staged` and warns developers locally before committing if they touch an `ACTIVE` constraint or repeat a reverted pattern.

---

## 3. Our User Segments

* **Segment 1 (Primary) — Senior / Staff Software Engineers & New Developer Hires *(including AI-Assisted Developers)*:**
  * *Need:* Understand *why* constraints and workarounds exist before refactoring unfamiliar modules or letting AI agents edit code.
  * *Solution:* Grounded `/ask` with verbatim PR quotes, line-level "Why Blame", *Before You Change* briefs, `who_to_ask` maintainer attribution, and `codewhy-mcp` agent guardrails.
* **Segment 2 (Additional) — Code Reviewers, Tech Leads & QA Release Engineers:**
  * *Need:* Catch architectural regressions during PR review and release sign-off before re-introducing previously reverted bugs.
  * *Solution:* Pre-Flight Impact Check (`POST /preflight`), `codewhy check` CLI, `HIGH RISK` Hotspot Maps, and Knowledge Graph Time-Travel showing `ACTIVE` vs. `SUPERSEDED` revert chains.
* **Segment 3 (Additional) — Engineering Managers, Compliance Auditors & Onboarding Leads:**
  * *Need:* Retain institutional memory, maintain up-to-date Architecture Decision Records, and prove verifiable audit provenance for security/compliance controls.
  * *Solution:* Auto-Generated ADR Exporter (`docs/adr/*.md`), shareable verbatim citation receipts, Trust Scoreboard metrics, and `Person` ownership graphs to spot bus-factor risk.

---

## 4. Partner Tech Choice: **Neo4j (Neo4j AuraDB GraphRAG)**

### How We Deepen Neo4j in CodeWhy
CodeWhy runs on **Neo4j AuraDB** (~2,056 nodes, 524 relationships) with uniqueness constraints, property indexes, a full-text quote index, and a 384-dim cosine vector index (`decision_vector_index`). By **12 PM on 22 November**, we deepen Neo4j across four areas:
1. **Full 11-Label Contributor & Multi-Source Graph:** Materialize `Person` nodes with `AUTHORED` and `REVIEWED` edges for entity-scoped `who_to_ask` ranking, alongside `Document` (ADRs), `Discussion`, and `Incident` nodes.
2. **Batched Cypher `UNWIND` Ingestion (`~5 min → <10s`):** Upgrade `Neo4jGraphStore` to batched `UNWIND` transactions (`merge_nodes_batch`, `merge_relationships_batch`), making live graph rebuilds fast enough for real-time repository onboarding.
3. **Eliminating N+1 Cypher Queries & Reusing Graph Embeddings (`~4.1s → <80ms`):** Pre-store `decision_count` and repository counts on `CodeEntity`/`Repository` nodes and score against pre-stored 384-dim `Decision.embedding` vectors inside the 1-hop `GOVERNS` neighborhood.
4. **Production Resilience (`verify_connectivity()` + SQLite Fallback):** Add an explicit 5-second `driver.verify_connectivity()` check at startup so if AuraDB Free pauses after 72h idle, CodeWhy automatically falls back to `InMemoryGraphStore` hydrated from `data/ingest.sqlite3` with zero downtime.

### The Product Need Neo4j Solves
* **Why Plain Vector RAG Fails for Engineering History:** A vector store retrieves semantically similar text, but it cannot determine whether a decision was **reverted three months later**, which **PR** a `git blame` commit belongs to, or **who authored and reviewed** a constraint.
* **Graph-Enforced Grounding & Temporal Truth:** Neo4j enables deterministic multi-hop traversal (`CodeEntity ←[GOVERNS]— Decision —[SUPERSEDES]→ Decision`, `Commit —[PART_OF]→ PullRequest`, `Decision —[SUPPORTED_BY]→ Evidence`, `Person —[AUTHORED|REVIEWED]→ PullRequest`) so CodeWhy enforces its **4-Gate Refusal Pipeline** and **100% verbatim provenance** *in the graph* before the LLM generates a single word.
