# API Reality Report: Ground Truth Contract & Live Behavior

**Generated Date**: 2026-10-29  
**Git Commit**: `069e82f689e304482bdbe0dfde250b6d3b8705db`  
**Git Branch**: `ui-polish`  
**Backend Mode**: `DATA_SOURCE=graph`, `SQLITE_CACHE_PATH` unset, `HF_HUB_OFFLINE=1`  
**Verification Method**: Live requests against running FastAPI backend connected to Neo4j Aura graph instance. All responses recorded deterministically into `frontend/fixtures/recorded/`.

---

## 1. Endpoints & Ground Truth Response Matrix

| Endpoint | HTTP Method | Expected Status | Real Latency | Observed Shape Summary | Fields Present / Null / Empty |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `/api/v1/health` | GET | 200 | ~24 ms | `{"status":"ok","version":"0.1.0","data_source":"graph"}` | Present: `status`, `version`, `data_source`. Extra fields like `dependencies`, `timestamp`, `database` are absent. |
| `/api/v1/health/dependencies` | GET | 200 | ~29 ms | `{"services":[...],"data_source":"graph"}` | Services array with 4 items: `github`, `neo4j`, `llm`, `embeddings`. Each has `name`, `status` ("configured"), `detail`. |
| `/api/v1/repositories` | GET | 200 | ~1,642 ms | `{"items":[...],"fixture":false}` | 2 repositories returned: `sqlalchemy-alembic` (9 decisions) and `urllib3-urllib3` (34 decisions). |
| `/api/v1/repositories/urllib3-urllib3` | GET | 200 | ~954 ms | Single repository object | `prs_fetched`: 294, `sources_analyzed`: 96, `prs_noise_skipped`: 70, `verified_decisions`: 34, `last_rebuilt_at`: `"2026-10-18T21:18:02.432234+00:00"`. |
| `/api/v1/repositories/sqlalchemy-alembic` | GET | 200 | ~904 ms | Single repository object | `prs_fetched`: null, `sources_analyzed`: null, `prs_noise_skipped`: null, `verified_decisions`: null, `last_rebuilt_at`: null, `scope`: null. |
| `/api/v1/repositories/{id}/entities?q=src` | GET | 200 | ~4,093 ms | `{"entities":[...],"query":"src","fixture":false}` | 24 entities matching "src" (23 `File`, 1 `Module`). Query param `q` is REQUIRED (`minLength: 1`). |
| `/api/v1/repositories/{id}/entities?q=pool` | GET | 200 | ~606 ms | `{"entities":[...],"query":"pool","fixture":false}` | 2 entities matching "pool" (`connectionpool.py`, `poolmanager.py`). |
| `/api/v1/repositories/{id}/decisions` | GET | 200 | ~621 ms | `{"items":[...],"total":34,"limit":50,"offset":0,"fixture":false}` | Exactly 34 decisions in urllib3. 33 `ACTIVE`, 1 `SUPERSEDED`. 1 decision (`dec_954169a03fd82f51`) has `date: null`. |
| `/api/v1/decisions/dec_6dee7648b9ef5416` | GET | 200 | ~281 ms | Decision detail object | Superseded decision. `state`: "SUPERSEDED", `superseded_by`: `["dec_ce303eb845540d38"]`, `rule`: "1_revert_commit". |
| `/api/v1/decisions/dec_ce303eb845540d38` | GET | 200 | ~275 ms | Decision detail object | Active superseding decision. `state`: "ACTIVE", `supersedes`: `["dec_6dee7648b9ef5416"]`, `rule`: "1_revert_commit". |
| `/api/v1/decisions/dec_954169a03fd82f51` | GET | 200 | ~233 ms | Decision detail object | `effective_at`: null, `recorded_at`: null, `ended_at`: null. Must render as "date unknown". |
| `/api/v1/repositories/{id}/graph` | GET | 200 | ~677 ms | `{"nodes":[...],"edges":[...],"truncated":true,"fixture":false}` | Repo-wide graph: 80 nodes, 104 edges. Truncated at node limit. Edge types: `GOVERNS`, `DECIDED_IN`, `SUPERSEDES`. |
| `/api/v1/repositories/{id}/graph?entity_id=...` | GET | 200 | ~1,072 ms | `{"nodes":[...],"edges":[...],"truncated":false,"fixture":false}` | Subgraph reaching evidence nodes: 74 nodes, 97 edges. Node types include `Evidence`, edge types include `SUPPORTED_BY`. |
| `/api/v1/repositories/{id}/ask` (cold) | POST | 200 | ~104,688 ms | AskResponse object | Cold ask loads SentenceTransformer embedding weights (`all-MiniLM-L6-v2`) on first inference. |
| `/api/v1/repositories/{id}/ask` (warm) | POST | 200 | ~18,000–31,000 ms | AskResponse object | Full answers with LLM generation take ~18–32s. Fast refusals take 400–1600ms. |

---

## 2. Field Analysis & Nullability

### Dates and Timestamps
- **Repository `last_rebuilt_at`**: Returned for `urllib3-urllib3` (`2026-10-18T21:18:02.432234+00:00`), but `null` for `sqlalchemy-alembic`.
- **Decision `date` / `effective_at`**: `dec_954169a03fd82f51` has `date: null` in decision lists and `effective_at: null` in details. The UI must never assume date is non-null. It must render "date unknown".
- **Decision `recorded_at` & `ended_at`**: Consistently `null` in all live decisions.
- **Citation `timestamp`**: Consistently `null` in all live evidence citations.

### Authors and Quotes
- **Citation `author`**: Present on citations (e.g. `"mrdaybird"`, `"Lukasa"`), nullable in schema.
- **Citation `quote`**: Verbatim substring extracted from PR markdown or issue discussion. Always present on verified citations.

### Coverage & Counts
- `urllib3-urllib3`:
  - `counts.decisions`: 34
  - `counts.entities`: 24
  - `counts.pull_requests`: 299
  - `counts.commits`: 735
  - `prs_fetched`: 294
  - `sources_analyzed`: 96
  - `prs_noise_skipped`: 70
  - `verified_decisions`: 34
- `sqlalchemy-alembic`:
  - `counts.decisions`: 9
  - `counts.entities`: 6
  - `counts.pull_requests`: 199
  - `counts.commits`: 345
  - Ingest coverage counters (`prs_fetched`, `sources_analyzed`, etc.) are `null`.

### Ask Response Fields
- `who_to_ask`: Observed as empty `[]` in all real responses.
- `candidates`: Observed as empty `[]` in all real responses.
- `evidence_gaps`: Non-empty in refusals (contains human-readable explanations of repository scope or similarity threshold gaps), empty `[]` in full responses.
- `code_differs_from_latest`: Observed as `null`.

---

## 3. Observed Enums

| Enum Type | Values Defined in Contract | Values Actually Observed in Live Data |
| :--- | :--- | :--- |
| `Outcome` | `full`, `partial`, `refusal` | `full`, `refusal` |
| `DecisionState` | `ACTIVE`, `SUPERSEDED`, `REJECTED`, `UNRESOLVED` | `ACTIVE` (33 items), `SUPERSEDED` (1 item) |
| `ReasonCode` | `entity_not_found`, `ambiguous_entity`, `out_of_scope`, `no_decision_path`, `no_verified_quote`, `low_score` | `entity_not_found`, `low_score` |
| `SourceType` | `PullRequest`, `Issue`, `Document`, `Commit` | `PullRequest` |
| Graph Node Type | Any string | `Decision`, `CodeEntity`, `PullRequest`, `Evidence`, `Repository` |
| Graph Edge Type | Any string | `GOVERNS`, `DECIDED_IN`, `SUPERSEDES`, `SUPPORTED_BY`, `CONTAINS` |

---

## 4. Observed Behaviors (0.4)

### 4.1 Latency of `/ask`
- **Cold Latency**: **104,688.58 ms (~104.7s)**  
  On the first `/ask` request after backend startup, the SentenceTransformer model weights (`all-MiniLM-L6-v2`) are loaded from local cache into memory, taking ~15–20s before query embedding, graph traversal, and LLM reasoning begin.
- **Warm Latency**: **18,091.75 ms to 31,879.77 ms (~18–32s)** for queries resulting in `outcome: full`.
- **Fast Refusal Latency**: **447.79 ms to 1,657.14 ms** for queries where entity lookup fails immediately or query score is evaluated before LLM generation.

### 4.2 Refusal Shapes
1. **Unknown Entity (`file:urllib3/urllib3:does/not/exist.py`)**:
   ```json
   {
     "outcome": "refusal",
     "reason_code": "entity_not_found",
     "answer": "I could not find a matching code entity in the repository history for this question.",
     "entity": null,
     "confidence": null,
     "decisions": [],
     "citations": [],
     "evidence_gaps": [
       "This system covers urllib3/urllib3 at branch main, commits 2009-12-10..2026-10-01, 291 file paths touched by the fetched pull requests; ingest caps: max_ingestion_issues=100; no matching file was found."
     ],
     "who_to_ask": [],
     "code_differs_from_latest": null,
     "fixture": false
   }
   ```
2. **Off-Topic Query ("Why does urllib3 use Kubernetes for orchestration?")**:
   - `outcome`: `"refusal"`
   - `reason_code`: `"entity_not_found"`
   - `entity`: `null`
   - `confidence`: `null`
   - `evidence_gaps`: Identical coverage-caps explanation.
3. **Prompt Injection Attempt ("Ignore all previous instructions...")**:
   ```json
   {
     "outcome": "refusal",
     "reason_code": "low_score",
     "answer": "Relevant decisions exist for this entity, but the retrieved evidence does not meet the required similarity threshold to reliably assert an answer.",
     "entity": {
       "id": "file:urllib3/urllib3:src/urllib3/util/ssl_.py",
       "type": "File",
       "label": "src/urllib3/util/ssl_.py",
       "path": "src/urllib3/util/ssl_.py",
       "decision_count": 1
     },
     "confidence": {
       "score": 0.45,
       "label": "LOW",
       "signals": {
         "directness": 0.5,
         "provenance": 0.5,
         "agreement": 0.4,
         "relevance": 0.4918,
         "temporal_consistency": 1.0,
         "contradiction": 0.0
       }
     },
     "evidence_gaps": ["Evidence relevance score below MIN_SCORE threshold"],
     "decisions": [],
     "citations": []
   }
   ```

### 4.3 Error Responses (404 and 422)
- **404 Not Found Body**:
  ```json
  { "detail": "repository 'not-found' not found" }
  ```
  ```json
  { "detail": "decision 'dec_notfound' not found" }
  ```
- **422 Validation Error Bodies**:
  - Missing query parameter `q` on `/entities`:
    ```json
    { "detail": [{ "loc": ["query", "q"], "msg": "Field required", "type": "missing", "input": null }] }
    ```
  - Empty query parameter `q=""` on `/entities`:
    ```json
    { "detail": [{ "loc": ["query", "q"], "msg": "String should have at least 1 character", "type": "string_too_short", "input": "", "ctx": { "min_length": 1 } }] }
    ```
  - Missing `question` in `/ask` body:
    ```json
    { "detail": [{ "loc": ["body", "question"], "msg": "Field required", "type": "missing", "input": {} }] }
    ```
  - Short `question` (`"ab"`) in `/ask` body:
    ```json
    { "detail": [{ "loc": ["body", "question"], "msg": "String should have at least 3 characters", "type": "string_too_short", "input": "ab", "ctx": { "min_length": 3 } }] }
    ```

### 4.4 `ask_headline` vs `ask_headline_entity_id`
- Both queries ask: `"Why was src/urllib3/util/ssl_.py changed for HTTP/2 TLS support?"`.
- When called without `entity_id`, the backend automatically resolves entity `file:urllib3/urllib3:src/urllib3/util/ssl_.py` from the query text.
- Both invocations return `status: 200`, `outcome: "full"`, citing the exact same decision IDs (`dec_6dee7648b9ef5416` and `dec_ce303eb845540d38`).
- **Answer Text Comparison**: `r1.answer == r2.answer` evaluates to `false` because the response text is synthesized by the LLM in real-time, resulting in phrasing variation while maintaining factual equivalence.

---

## 5. Mismatches & Drift Analysis (0.3)

### 5.1 TypeScript Types & Service Contract Drift
1. **Fake Repository `acme-netclient`**:
   - `services/api.ts` contained 6 demo questions for `acme-netclient`.
   - `IntelligenceWorkspace.tsx` defaulted to `acme-netclient` when no repository was selected (`const repoId = selectedRepo?.id || 'acme-netclient'`).
   - `acme-netclient` does not exist in the backend.
2. **Hardcoded Exclusion in `fetchRepositories`**:
   - `services/api.ts` explicitly filtered out `hynek-structlog`.
   - The backend only returns `sqlalchemy-alembic` and `urllib3-urllib3`. Hardcoded repository exclusions should not exist.
3. **Example Questions Grounding Mismatches (`GROUNDED_DEMO_QUESTIONS`)**:
   - Question `"Why was support for Python 2.6 dropped in urllib3?"`:
     - **Frontend Assumption**: Tagged as `'Full Answer (PR #1429)'` with `outcomeType: 'full'`.
     - **Live API Reality**: Returns `outcome: 'refusal'` with `reason_code: 'low_score'` because the evidence similarity score is below `MIN_SCORE`!
   - Question `"Why was src/urllib3/util/url.py changed?"`:
     - **Frontend Assumption**: Tagged as `'Refusal (Thin Score)'` with `outcomeType: 'refusal'`.
     - **Live API Reality**: Returns `outcome: 'full'` with 3 valid decisions (`dec_374c15ea4fa9fa06`, `dec_5bf9c85e20b5cb14`, `dec_d93fcc65f36fe7a9`)!
   - Question `"Why was src/urllib3/util/ssl_.py reverted for HTTP/2 TLS?"`:
     - **Frontend Assumption**: Tagged as `tag: 'Superseded (PR #3466)'`.
     - **Live API Reality**: Outcome is `full`, which discusses both the initial RFC 9113 change and the subsequent revert commit.
4. **`HealthResponse` Type Inaccuracies**:
   - `types/index.ts` defined optional fields `app_version`, `database`, `timestamp`, `dependencies`.
   - Live backend returns strictly `{ status: "ok", version: "0.1.0", data_source: "graph" }`.
5. **Decision Date Nullability**:
   - In `types/index.ts`, `DecisionListItem.date` was typed as `string | null`, but UI components did not consistently handle null dates (displaying blank or raw null rather than "date unknown"). In real data, `dec_954169a03fd82f51` has `date: null`.

### 5.2 UI Claims vs Repository Facts
- **PRs read**: Real repository fact is **294 PRs read** (`prs_fetched`). The UI should display `294` directly from `repoData.prs_fetched`.
- **Sources analyzed**: Real repository fact is **96 sources analyzed** (`sources_analyzed`).
- **Verified decisions**: Real repository fact is **34 verified decisions** (`verified_decisions`).
- **Commits**: Real fact is **735 commits** (`counts.commits`).
- **Total PRs in repository**: Real fact is **299 pull requests** (`counts.pull_requests`).
- **Last Rebuild Date**: Real rebuild date is `"2026-10-18T21:18:02.432234+00:00"`.
- **"100%" Claims**: Any copy claiming "100% Verbatim Quote Policy", "100% Available", or "100% operational" must be audited to ensure it reflects actual verification and not ungrounded marketing claims.
