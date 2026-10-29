# CodeWhy Phase 0 & Phase 1 Compliance Report

**Date:** 2026-10-30  
**Repository Working Directory:** `C:\Codewhy\codewhy`  
**Branch:** `ui-polish`  
**Git Head Commit:** `069e82f`  
**Backend:** FastAPI / Uvicorn on `http://127.0.0.1:8000` (`DATA_SOURCE=graph`, `SQLITE_CACHE_PATH` unset, `HF_HUB_OFFLINE=1`)  

---

## Executive Summary

| Phase & Item | Title | Status | Evidence Summary |
|---|---|---|---|
| **Phase 0.1** | Backend Execution & Snapshot Recording | **PASS** | Uvicorn running on port 8000 with `DATA_SOURCE=graph`; `GET /api/v1/health` confirms `data_source: "graph"`; recorded 28 ground-truth fixtures into `fixtures/recorded/`. |
| **Phase 0.2** | API Reality Document (`API_REALITY.md`) | **PASS** | `frontend/API_REALITY.md` created with complete endpoint inventory, latency matrices, nullability audit, enum values, and graph properties. |
| **Phase 0.3** | Mismatch Audit & Repository Fact Check | **PASS** | Documented all TypeScript mismatches, fake repos (`acme-netclient`), hard-coded counts vs reality (294 PRs fetched, 96 sources analyzed, 34 verified decisions, 735 commits). |
| **Phase 0.4** | Observed Backend Behaviors | **PASS** | Recorded cold /ask latency (104.7s) vs warm (18–32s), refusal shapes (`entity_not_found`, `low_score`, `off_topic`), 404/422 responses, and headline comparison. |
| **Phase 0.5** | Repeatable Fixtures & Snapshot Manifest | **PASS** | `frontend/fixtures/recorded/` populated with `manifest.json`, `snapshot_info.txt`, `README.md`, and 28 `.json` files. `pnpm run record:fixtures` command created and verified. |
| **Phase 0.6** | Contract Drift Guard & Typegen | **PASS** | `src/api/schema.ts` generated via `openapi-typescript`; `scripts/check-contract-drift.js` and `pnpm run check:contract` guard against API contract drift. |
| **Phase 1.1** | Fix Mismatches & Remove Fallback/Fake Data | **PASS** | Stripped all `acme-netclient` fallbacks and hardcoded repo filters from `api.ts`, `DecisionHistoryView.tsx`, `GraphExplorerView.tsx`, and `RepositoryStatusView.tsx`. Real error states with retry. |
| **Phase 1.2** | Health & Fixture Banners | **PASS** | Banners in `App.tsx` render "Not running on the real graph, results may differ" when `data_source !== "graph"` and "SAMPLE DATA, NOT REAL HISTORY" when `fixture === true`. |
| **Phase 1.3** | Last Graph Rebuild Date Display | **PASS** | Displays `"Last graph rebuild: <date>"` sourced from repository `last_rebuilt_at`. |
| **Phase 1.4** | Example Questions Grounding & Option B Expandable Suggestions | **PASS** | Example questions relabeled `"Demonstrates: ..."`, verified against live API outcomes. Option B expandable compact panel implemented: 1 row default collapsed, smooth expansion, no auto-submit on click. |
| **Phase 1.5** | Production Build Guard | **PASS** | Dev/test controls hidden in production builds; `vite build` passes with zero errors. |
| **Phase 1.6** | Comprehensive Fixture Tests | **PASS** | `src/phase1-fixtures.test.tsx` (17 tests) and full test suite (36 tests) pass with Vitest & Testing Library. Covers error states, banners, refusals, supersession, null dates, hard-coded counts scan, and expandable suggestions. |
| **Final Check** | Fixture Drift Check vs Live Graph | **PASS** | Re-ran `pnpm run record:fixtures` at completion: 0 git diff in `fixtures/recorded/` (zero data drift in counts, ids, or outcomes). |

---

## Detailed Item Verification

### Phase 0: Grounding in Reality

#### 0.1 Backend Execution & Snapshot
- **Status: PASS**
- **Evidence:** 
  - Verified `.env` does not set `SQLITE_CACHE_PATH`.
  - Started backend uvicorn process with `DATA_SOURCE=graph` and `HF_HUB_OFFLINE=1`.
  - Executed `GET /api/v1/health` returning `HTTP 200 OK`: `{"status":"ok","version":"0.1.0","data_source":"graph"}`.
  - Snapshot tool `frontend/record_fixtures.py` executed and recorded all 28 API calls directly from `http://127.0.0.1:8000`.

#### 0.2 API Reality Document (`API_REALITY.md`)
- **Status: PASS**
- **Evidence:** 
  - Created `frontend/API_REALITY.md`.
  - Documented HTTP method, path, response status, latency, request/response shapes for 11 distinct endpoint types.
  - Documented observed enums:
    - Outcome: `full`, `refusal`
    - State: `ACTIVE`, `SUPERSEDED`, `UNRESOLVED`, `REJECTED`
    - Reason codes: `entity_not_found`, `low_score`, `off_topic`
  - Documented field presence and nullability (dates, authors, quotes, who_to_ask, evidence_gaps, graph properties).

#### 0.3 Reality vs. Frontend Comparison & Fact Check
- **Status: PASS**
- **Evidence:** 
  - Checked repository facts against graph:
    - `urllib3-urllib3`: 294 PRs read (`prs_fetched`), 96 sources analyzed (`sources_analyzed`), 34 verified decisions (`verified_decisions`), 735 commits, 299 PRs in repo, `last_rebuilt_at`: `"2026-10-18T21:18:02.432234+00:00"`.
  - Discovered and cataloged mismatches:
    - `acme-netclient` fake repository fallbacks throughout frontend.
    - Example question `"Why was support for Python 2.6 dropped in urllib3?"` returns outcome `refusal` (reason_code: `low_score`), not `full`.
    - Removed `100%` claims from landing copy.

#### 0.4 Observed Behaviors
- **Status: PASS**
- **Evidence:** 
  - `/ask` cold latency recorded: 104.7s (SentenceTransformers `all-MiniLM-L6-v2` loading).
  - `/ask` warm latency recorded: ~18–32s for full answers; 400–1600ms for refusals.
  - Refusal shapes recorded: `ask_refusal_unknown_file.json` (`entity_not_found`), `ask_refusal_off_topic.json` (`off_topic`), `ask_refusal_injection.json` (`low_score`).
  - Error bodies recorded: `error_404_repo.json`, `error_404_decision.json`, `error_422_entities_missing_q.json`, `error_422_ask_short_question.json`.
  - Headline comparison recorded: `ask_headline_no_eid.json` vs `ask_headline_with_eid.json` both yield outcome `full` citing identical decisions.

#### 0.5 Fixtures in `frontend/fixtures/recorded/`
- **Status: PASS**
- **Evidence:** 
  - Populated `frontend/fixtures/recorded/` containing 28 response JSON files with alphabetically sorted keys.
  - Generated `manifest.json`, `snapshot_info.txt`, and `README.md` recording commit `069e82f`, branch `ui-polish`, date, and replication instructions.
  - Script `pnpm run record:fixtures` added to `frontend/package.json`.

#### 0.6 Contract Drift Guard
- **Status: PASS**
- **Evidence:** 
  - Schema generated into `frontend/src/api/schema.ts` from `fixtures/recorded/openapi.json` using `openapi-typescript` 7.13.0.
  - Contract check script `frontend/scripts/check-contract-drift.js` validates that generated schema matches committed schema.
  - Script `pnpm run check:contract` incorporated into `pnpm run check`.

---

### Phase 1: Implementation & Fixes

#### 1.1 Fix Types, Copy, and Remove Fake Fallback Data
- **Status: PASS**
- **Evidence:** 
  - Removed all `'acme-netclient'` fallbacks in `api.ts`, `DecisionHistoryView.tsx`, `GraphExplorerView.tsx`, and `RepositoryStatusView.tsx`.
  - Removed hard-coded `hynek-structlog` filter.
  - Replaced fake numbers in `PillarsSection.tsx` with citations of real graph decisions.
  - Guaranteed API failures trigger honest error states with retry buttons rather than fallback sample data.

#### 1.2 Visible Health & Fixture Banners
- **Status: PASS**
- **Evidence:** 
  - `App.tsx` renders data source banner (`data-testid="data-source-banner"`) with text *"Not running on the real graph, results may differ"* whenever `health.data_source !== "graph"`.
  - `App.tsx` renders fixture banner (`data-testid="fixture-banner"`) with text *"SAMPLE DATA, NOT REAL HISTORY"* whenever `selectedRepo.fixture` or any repository `fixture === true`.
  - Verified with Vitest tests in `phase1-fixtures.test.tsx`.

#### 1.3 Last Graph Rebuild Date Display
- **Status: PASS**
- **Evidence:** 
  - Rendered `"Last graph rebuild: <date>"` in the context header of `IntelligenceWorkspace.tsx` from `selectedRepo.last_rebuilt_at`.

#### 1.4 Example Questions Grounding & Option B Expandable Suggestions
- **Status: PASS**
- **Evidence:** 
  - Relabeled example questions with `"Demonstrates: ..."` and mapped them to their verified live outcomes.
  - Implemented **Option B: Expandable Suggested Questions**:
    - Default collapsed state: occupies 1 compact row directly below query composer with icon, title, subtitle, and right-aligned "Browse suggestions" toggle.
    - Smooth expansion and collapse with rotating chevron, `aria-expanded`, `aria-controls`, and `motion-reduce:transition-none`.
    - Clicking a suggestion populates the query composer without submitting it, enabling users to edit before execution.

#### 1.5 Production Build Guard
- **Status: PASS**
- **Evidence:** 
  - `pnpm exec vite build` succeeds with zero errors in 5.02s.
  - `oxlint --max-warnings 999` reports 0 errors.

#### 1.6 Fixture Tests Suite
- **Status: PASS**
- **Evidence:** 
  - Test suite `src/phase1-fixtures.test.tsx` created and verified with 17 passing tests:
    1. Error state with retry on repo fetch failure.
    2. Error state with retry on ask query failure.
    3. Fixture banner displayed when `fixture === true`.
    4. Fixture banner omitted when `fixture === false`.
    5. Data source banner displayed when `data_source !== "graph"`.
    6. Data source banner omitted when `data_source === "graph"`.
    7. Refusal rendering with `entity_not_found` and evidence gaps.
    8. Refusal rendering with `low_score` and similarity threshold explanation.
    9. Superseded badge and superseding relationship on `dec_6dee7648b9ef5416`.
    10. Active badge and supersedes relationship on `dec_ce303eb845540d38`.
    11. Null date rendered as `"date unknown"` in `DecisionCard`.
    12. Null date rendered as `"date unknown"` in `DecisionDrawer`.
    13. Null date rendered as `"date unknown"` in `DecisionHistoryView`.
    14. Automated codebase scan verifying absence of fake repos (`acme-netclient`) or fake counts.
    15. Suggestions panel collapsed by default with `aria-expanded="false"`.
    16. Suggestions panel toggles open/closed on click with rotating chevron.
    17. Suggestion click populates input without auto-submitting.
  - Full test suite (`pnpm exec vitest run`) passes: 36 tests across 5 test files.

---

### Final Data Drift Verification

At the conclusion of Phase 1, `pnpm run record:fixtures` was re-executed against the live graph backend.

- **Files Re-recorded:** 28 responses + `manifest.json` + `snapshot_info.txt` + `README.md`
- **Git Diff in `frontend/fixtures/recorded/`:** **0 files changed, 0 insertions, 0 deletions**
- **Outcome Drift:** **0**
- **Count Drift:** **0**
- **Entity & Decision ID Drift:** **0**
