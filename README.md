# CodeWhy

> **Every line has a history. Find the reasoning, not just the code.**

CodeWhy answers *"why is this code like this?"* for a software repository by reconstructing engineering decisions from GitHub commits, pull requests, review discussions, issues, and design documents. It links decisions to code entities in a knowledge graph, tracks how decisions change over time (supersession, reversals, reaffirmations), and answers natural-language questions with traceable verbatim citations—or refuses honestly when the history does not say.

---

## Current Status: Phase 3 Complete (Graph & Ask)

The project has advanced through **Phase 0, Phase 1, Phase 2, and Phase 3**. All backend contracts, data ingestion, deterministic linking, AST constant history, noise filtering, decision extraction with verbatim quote checks, Neo4j graph stores, and the 4-gate grounded `/ask` pipeline are fully implemented and verified with **98 passing unit and integration tests**.

Target repository: [`hynek/structlog`](https://github.com/hynek/structlog) (with target definition at [`targets/hynek__structlog.json`](targets/hynek__structlog.json)).

### Build Phases at a Glance

| Phase | Title | Status | What It Delivers |
|:---:|---|:---:|---|
| **0** | **Contract & Fixtures** | ✅ Complete | Frozen Pydantic v2 schemas, OpenAPI specification, synthetic fixture data source, and strict response rule validators. |
| **1** | **Data In (Ingestion)** | ✅ Complete | Clone-first `git log --follow`, GitHub GraphQL batched client (20 PRs/query), SQLite cache (`data/ingest.sqlite3`) with stable IDs, rate-limit backoff, and email redaction. |
| **2** | **Linking & Decision Extraction** | ✅ Complete | Deterministic link extraction (`REVERTS`, `PART_OF`, `REFERENCES`, `SUPERSEDES`), AST constant & config history, 8 noise filters with revert protection, bounded token budget guard, prompt injection defense, Pydantic extraction schema, and 100% verbatim substring quote verification. |
| **3** | **Graph & Grounded Ask** | ✅ Complete | Neo4j schema & constraints, 384-dim vector index, parameterized Cypher queries, `scripts/rebuild_graph.py`, 384-dim embeddings, rule-based entity resolution, hybrid GraphRAG retrieval, 4-gate refusal pipeline (G1–G4), grounded answer service with citation post-validation, and `GraphDataSource`. |
| **4** | **History, Confidence & Who-to-Ask** | ⏳ Next | Supersession rules 1 to 3b, temporal state machine (`ACTIVE`, `SUPERSEDED`, `REJECTED`, `UNRESOLVED`), reversal-of-reversal chain preservation, contributor ranking (`who_to_ask`). |
| **5** | **Proof & Polish** | ⏳ Upcoming | 50-question benchmark (`benchmark/questions.jsonl`), evaluation script (`scripts/evaluate.py`), and React frontend integration. |

---

## Detailed Overview: What Has Been Built

### Phase 0: API Contract & Response Invariants
- **Frozen OpenAPI & JSON Schemas**: Every response model is validated via Pydantic v2.
- **Enforced Response Rules** ([`backend/app/services/response_rules.py`](backend/app/services/response_rules.py)):
  - Outcome `full` requires confidence label `HIGH` and at least one citation of kind `SOURCE`.
  - Outcome `partial` requires confidence label `MEDIUM` (or `LOW` when reason is `no_verified_quote`).
  - Refusal reason codes (`entity_not_found`, `ambiguous_entity`, `out_of_scope`, `no_decision_path`, `low_score`) only allow outcome `refusal`.
  - Ambiguous entity queries return at least 2 distinct candidate options and a `null` answer.
  - Reason `no_verified_quote` strictly forbids citations.
  - Contradiction flag (`signals.contradiction == 1.0`) caps confidence score at `0.70`.

### Phase 1: Safe, Bounded Ingestion
- **Repo-Agnostic Engine**: Target repositories are configured via `targets/<owner>__<repo>.json` files without touching code.
- **Target-First Strategy**: Historical analysis begins from seed targets (files and config keys) using `git log --follow` to preserve rename history before recency fill.
- **Resumable SQLite Cache** (`data/ingest.sqlite3`):
  - `raw_objects`: PRs, issues, commits, and documents under stable IDs (`pr:owner/repo#123`, `commit:sha`, `doc:path:hash`).
  - `commits` & `commit_files`: commit metadata, author display name only (email addresses automatically redacted), status, diffs, and truncation flags.
  - `skips` & `missing`: records items omitted by bounds or numbers that did not resolve.
- **GraphQL First**: Batches up to 20 pull requests with their reviews and comments per query, with exponential backoff on secondary rate limits.

### Phase 2: Linking & Decision Extraction
Phase 2 bridges raw repository records into structured engineering decisions and relationships:
1. **Deterministic Linking** ([`backend/app/services/linking.py`](backend/app/services/linking.py)):
   - `REVERTS`: parses `"This reverts commit <sha>"` and git `Reverts:` trailers.
   - `PART_OF`: parses `(#123)` in squash-commit subjects.
   - `REFERENCES`: parses closing keywords (`Fixes: #12`, `Closes: #12`, `Resolves: #12`) and trailer mentions.
   - `SUPERSEDES`: parses ADR document headers (`Status: Superseded by ADR-7`).
   - `FileHistoryTracker`: tracks file rename chains across commits.
2. **Configuration Keys & AST Value History** ([`backend/app/services/config_keys.py`](backend/app/services/config_keys.py)):
   - Uses Python's built-in `ast` to parse module and class `UPPER_CASE` constants (excluding private `_NAME` symbols).
   - Supports YAML, JSON, TOML, and `.env` formats.
   - Reconstructs constant value change histories across commit diffs (`ConfigValueChange`).
3. **Noise Filtering** ([`backend/app/services/noise.py`](backend/app/services/noise.py)):
   - 8 regex detectors: `bot_author`, `dependency_update`, `formatting_only`, `typo_fix`, `ci_config`, `version_bump`, `merge_commit`, `generated_file`.
   - **Critical Invariant**: Noise records are flagged but **never deleted**. Revert targets are strictly protected (`is_noise=False`) so historical reversions are never hidden.
4. **LLM Provider & Budget Guard** ([`backend/app/providers/llm_provider.py`](backend/app/providers/llm_provider.py)):
   - `TokenBudget`: tracks prompt and completion tokens against `MAX_LLM_TOKENS_PER_RUN` (500,000 default).
   - Raises `TokenBudgetExhaustedError` when the budget is reached, stopping the run cleanly as `PARTIAL`.
   - `MockLLMProvider` for tests and offline development; `OpenAICompatibleProvider` for production.
5. **Prompt Injection Defenses** ([`backend/app/prompts/extract_decision.py`](backend/app/prompts/extract_decision.py)):
   - Wraps all untrusted repository data in `<<<UNTRUSTED_REPOSITORY_DATA>>>` delimiters.
   - Neutralizes delimiter collision attempts and strips null bytes.
   - Detects prompt injection attempts (`detect_injection_attempt`).
6. **Decision Extraction Service** ([`backend/app/services/extraction.py`](backend/app/services/extraction.py)):
   - Enforces strict Pydantic models separating LLM output (summary, rationale, alternatives, quotes) from code-generated metadata.
   - Deterministic ID hashing: `decision_id = f"dec_{sha256(source_id:v1:index)}"`.
   - Computes `content_hash` to skip unchanged source files across re-runs.
7. **Verbatim Quote Verification** ([`backend/app/services/quote_check.py`](backend/app/services/quote_check.py)):
   - Requires quotes to be exact substrings of source text (with whitespace, case, and markdown normalization).
   - Unverified quotes are dropped.
   - **Invariant**: If no verified quote remains, the decision summary falls back to `"change recorded, rationale unknown"`, rationale is cleared, and `quote_verified = False`.
8. **Extraction CLI & Audit Report**:
   - [`scripts/extract.py`](scripts/extract.py) executes the extraction pipeline from SQLite cache.
   - [`review/decisions_sample.md`](review/decisions_sample.md) contains 20 hand-audited decisions verifying quote accuracy and rationale fallbacks.

### Phase 3: Neo4j Knowledge Graph & Grounded Ask Endpoint
Phase 3 builds the connected graph view and grounded retrieval pipeline:
1. **Neo4j Schema & Constraints** ([`backend/app/graph/schema.py`](backend/app/graph/schema.py)):
   - Unique ID constraints on all 11 node types (`Repository`, `CodeEntity`, `Decision`, `PullRequest`, `Commit`, `Issue`, `Discussion`, `Person`, `Evidence`, `Document`, `Incident`).
   - Property indexes on code entity paths, names, and decision states.
   - 384-dimensional cosine vector index (`decision_vector_index`) on `Decision.embedding`.
   - Full-text index on `Evidence.quote`.
2. **Parameterized Cypher Queries** ([`backend/app/graph/queries.py`](backend/app/graph/queries.py)):
   - Idempotent `MERGE` queries for all nodes and all 15 relationships with strictly controlled directions.
3. **Graph Stores** ([`backend/app/stores/graph_store.py`](backend/app/stores/graph_store.py)):
   - `Neo4jGraphStore`: connects to Neo4j AuraDB with the official `neo4j` Python driver.
   - `InMemoryGraphStore`: provides in-memory graph operations so unit tests run with **zero credentials**.
4. **Single-Command Graph Rebuilder** ([`scripts/rebuild_graph.py`](scripts/rebuild_graph.py)):
   - Reads SQLite cache and restores the entire Neo4j graph with nodes, relationships, and embeddings in one command.
5. **384-dim Embeddings Provider** ([`backend/app/providers/embeddings.py`](backend/app/providers/embeddings.py)):
   - Integrates SentenceTransformers `all-MiniLM-L6-v2` with a deterministic offline hash projection fallback.
6. **Entity Resolution** ([`backend/app/services/entity_resolution.py`](backend/app/services/entity_resolution.py)):
   - Rule-based candidate matching from questions (paths, `UPPER_CASE` constants, dotted keys, quoted names).
   - Exact match wins (1.0).
   - If multiple candidates score within `0.05` of each other, returns `Outcome: refusal, reason_code: ambiguous_entity` with candidate picker choices.
   - Non-code questions return `out_of_scope`. Unmatched terms return `entity_not_found`.
7. **Hybrid GraphRAG Retrieval** ([`backend/app/services/retrieval.py`](backend/app/services/retrieval.py)):
   - Traverses `GOVERNS`, `SUPERSEDES`, and `REVERTS` up to `MAX_CHAIN_LENGTH` (6 hops).
   - Bounded evidence bundle capped at `MAX_EVIDENCE_ITEMS` (12 items).
   - Semantic similarity scored only on candidate decisions in the entity's neighborhood.
   - Contradiction detection across opposing evidence and unresolved links.
8. **4-Gate Refusal Pipeline** ([`backend/app/services/gate.py`](backend/app/services/gate.py)):
   - **G1 Entity**: Validates single resolved entity (otherwise `entity_not_found`, `out_of_scope`, or `ambiguous_entity`).
   - **G2 Path**: Entity must have at least one decision via `GOVERNS` (otherwise `no_decision_path`).
   - **G3 Quote**: At least one linked evidence item must have a verified quote (otherwise partial `no_verified_quote`).
   - **G4 Relevance**: Similarity score must be $\ge$ `MIN_SCORE` (0.55 default, otherwise `low_score`).
   - **The LLM is invoked only when all 4 gates pass.**
9. **Grounded Answer Service** ([`backend/app/services/answer.py`](backend/app/services/answer.py)):
   - Generates answers grounded strictly in the evidence bundle.
   - **Citation Post-Validation**: every cited ID is checked against the bundle; quotes verified via substring check.
   - Evaluates the Section 7 evidence confidence formula:
     $$\text{score} = 0.30 \times \text{directness} + 0.20 \times \text{provenance} + 0.20 \times \text{agreement} + 0.15 \times \text{relevance} + 0.15 \times \text{temporal\_consistency} - 0.30 \times \text{contradiction}$$
10. **`GraphDataSource` Integration** ([`backend/app/services/data_source.py`](backend/app/services/data_source.py)):
    - Plugs directly into the FastAPI HTTP API, toggled via `DATA_SOURCE=graph`.

---

## Installation & Setup

### Requirements
- Python 3.12
- Git
- Neo4j AuraDB Free instance (for live graph persistence)
- Optional: GitHub Token (for live ingestion) and LLM API key (for live extraction)

### Install Dependencies

**PowerShell:**
```powershell
py -V:3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

**Bash:**
```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

---

## Running Automated Tests

The test suite runs with **zero credentials and no required `.env` file**.

### Run All Phase 2 & Phase 3 Tests (98 tests)
```powershell
.\.venv\Scripts\pytest.exe backend/tests/unit/test_phase3.py backend/tests/unit/test_extraction.py backend/tests/unit/test_linking.py backend/tests/unit/test_config_keys.py backend/tests/unit/test_noise.py -v
```

### Run Full Unit Test Suite
```powershell
.\.venv\Scripts\pytest.exe backend/tests/unit/
```

---

## How to Run & Verify the Pipeline

### 1. Ingestion (`scripts/ingest.py`)
Plan ingestion for `hynek/structlog` without network or database writes:
```powershell
.\.venv\Scripts\python.exe scripts\ingest.py --repo hynek/structlog --targets targets\hynek__structlog.json --dry-run
```
Run live ingestion (requires `GITHUB_TOKEN` in `.env`):
```powershell
.\.venv\Scripts\python.exe scripts\ingest.py --repo hynek/structlog --targets targets\hynek__structlog.json --max-prs 50 --max-issues 50
```

### 2. Decision Extraction (`scripts/extract.py`)
Run decision extraction on cached repository data:
```powershell
.\.venv\Scripts\python.exe scripts\extract.py --repo hynek/structlog --dry-run
```

### 3. Rebuild Knowledge Graph (`scripts/rebuild_graph.py`)
Rebuild all Neo4j nodes, relationships, and vector embeddings from the SQLite cache:
```powershell
.\.venv\Scripts\python.exe scripts\rebuild_graph.py --repo hynek/structlog
```

### 4. Start the FastAPI API Server
Start the backend server on port 8000:
```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```
- Interactive Swagger UI: <http://127.0.0.1:8000/docs>
- OpenAPI Schema: <http://127.0.0.1:8000/openapi.json>

### 5. Query the `/ask` Endpoint
Ask a question about a code entity:
```powershell
$body = @{ question = "Why is NAME_TO_LEVEL defined?" } | ConvertTo-Json
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/repositories/hynek-structlog/ask" -Method Post -Body $body -ContentType "application/json"
```

---

## Configuration (`.env`)

Copy `.env.example` to `.env` to configure settings. Defaults work out of the box for testing:

| Setting | Default | Description |
|---|---|---|
| `DATA_SOURCE` | `fixture` | Set to `graph` to use the live Neo4j / In-Memory graph engine. |
| `GITHUB_TOKEN` | `""` | GitHub personal access token for live ingestion. |
| `NEO4J_URI` | `""` | Neo4j AuraDB Bolt URI (`neo4j+s://...`). |
| `NEO4J_USERNAME` | `""` | Neo4j username. |
| `NEO4J_PASSWORD` | `""` | Neo4j password. |
| `LLM_PROVIDER` | `mock` | `openai`, `ollama`, or `mock`. |
| `LLM_MODEL` | `""` | Model identifier (e.g. `gpt-4o-mini`). |
| `LLM_API_KEY` | `""` | API key for LLM provider. |
| `MAX_LLM_TOKENS_PER_RUN` | `500000` | Token budget guard stopping execution when reached. |
| `EMBEDDING_PROVIDER` | `local` | `local` (all-MiniLM-L6-v2) or deterministic fallback. |
| `MIN_SCORE` | `0.55` | Relevance similarity threshold for gate G4. |
| `MAX_CHAIN_LENGTH` | `6` | Maximum traversal depth along `SUPERSEDES` and `REVERTS`. |
| `MAX_EVIDENCE_ITEMS` | `12` | Upper bound on evidence items included in answer bundle. |

---

## Project Structure

```
codewhy/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI application & CORS config
│   │   ├── config.py                  # Pydantic BaseSettings & validators
│   │   ├── api/                       # HTTP route handlers (/ask, /graph, /decisions, /health)
│   │   ├── schemas/                   # Pydantic v2 schemas for contract, graph, and decisions
│   │   ├── services/                  # Business logic
│   │   │   ├── linking.py             # Phase 2: Deterministic linking (REVERTS, PART_OF, REFERENCES)
│   │   │   ├── config_keys.py         # Phase 2: AST constants & config value history
│   │   │   ├── noise.py               # Phase 2: Noise filtering with revert protection
│   │   │   ├── extraction.py          # Phase 2: Pydantic decision extraction
│   │   │   ├── quote_check.py         # Phase 2: Verbatim quote substring verification
│   │   │   ├── entity_resolution.py   # Phase 3: Rule-based entity resolution & ambiguity margin
│   │   │   ├── retrieval.py           # Phase 3: Hybrid GraphRAG bounded traversal
│   │   │   ├── gate.py                # Phase 3: 4-gate refusal pipeline (G1–G4)
│   │   │   ├── answer.py              # Phase 3: Grounded answering & citation validation
│   │   │   ├── confidence.py          # Phase 3: Evidence confidence scoring formula
│   │   │   ├── response_rules.py      # Contract response validators
│   │   │   └── data_source.py         # DataSource protocol, FixtureDataSource & GraphDataSource
│   │   ├── stores/
│   │   │   ├── sqlite_cache.py        # SQLite cache for raw objects, links, decisions, evidence
│   │   │   └── graph_store.py         # Neo4jGraphStore & InMemoryGraphStore
│   │   ├── graph/
│   │   │   ├── schema.py              # Neo4j constraints, indexes & 384-dim vector index
│   │   │   └── queries.py             # Parameterized Cypher queries
│   │   ├── providers/
│   │   │   ├── llm_provider.py        # Configurable LLM provider & TokenBudget guard
│   │   │   └── embeddings.py          # 384-dim embeddings provider & cosine similarity
│   │   └── prompts/
│   │       ├── extract_decision.md    # Extraction prompt with security boundaries
│   │       ├── extract_decision.py    # Injection detection & untrusted data delimiters
│   │       └── answer.md              # Grounded answering prompt
│   └── tests/
│       ├── unit/                      # 98+ unit tests covering all components
│       └── conftest.py
├── scripts/
│   ├── ingest.py                      # Phase 1: Ingestion CLI runner
│   ├── extract.py                     # Phase 2: Decision extraction CLI runner
│   ├── rebuild_graph.py               # Phase 3: Rebuild Neo4j graph from SQLite cache
│   ├── inspect_cache.py               # Read-only cache inspection CLI
│   └── export_contract.py             # Regenerates contract JSON files
├── targets/
│   ├── hynek__structlog.json          # Target definitions for hynek/structlog
│   └── urllib3__urllib3.json          # Test bed targets for urllib3
├── review/
│   └── decisions_sample.md            # 20 hand-audited decisions for manual verification
├── contract/                          # Frozen API payloads and openapi.json
└── pyproject.toml                     # Python dependencies and pytest configuration
```

---

## Next Steps: Phase 4 & Phase 5

1. **Phase 4 (History, Confidence & Who-to-Ask)**:
   - Implement the supersession engine rules 1 to 3b in [`services/supersession.py`](backend/app/services/supersession.py).
   - Implement the temporal decision state machine (`ACTIVE`, `SUPERSEDED`, `REJECTED`, `UNRESOLVED`) preserving reversal chains in [`services/state.py`](backend/app/services/state.py).
   - Implement active contributor ranking in [`services/who_to_ask.py`](backend/app/services/who_to_ask.py).
2. **Phase 5 (Proof & Polish)**:
   - 50 hand-labeled benchmark questions in `benchmark/questions.jsonl` (38 tuning, 12 holdout).
   - Evaluation runner in `scripts/evaluate.py`.
   - React + Vite + TypeScript frontend interface.
