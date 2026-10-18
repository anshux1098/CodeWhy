# CodeWhy

> **Every line has a history. Find the reasoning, not just the code.**

CodeWhy answers *"why is this code like this?"* for a software repository by reconstructing engineering decisions from GitHub commits, pull requests, review discussions, issues, and design documents. It links decisions to code entities in a knowledge graph and answers natural-language questions with traceable verbatim citations—or refuses honestly when the history does not say.

---

## Current Status: Phases 0–3 Complete, Exercised on a Real Repository

The project has advanced through **Phase 0, Phase 1, Phase 2, and Phase 3**. All backend contracts, data ingestion, deterministic linking, AST constant history, noise filtering, decision extraction with verbatim quote checks, Neo4j graph stores, and the 4-gate grounded `/ask` pipeline are implemented. The suite collects **975 tests**: **963 pass with zero credentials and no `.env` file**, and **12 tests skip** (5 live tests marked `live`, run with `RUN_LIVE=1`, exercise the real Neo4j store, Cypher `EXPLAIN` plan, GitHub API, and the live answer path; 6 review honesty tests skip on probe files that cite no pull requests; and 1 review test skips when it cannot count tests).

The pipeline has been run end to end on the real repository `urllib3/urllib3`: ingest → extract → link → build the Neo4j graph → answer grounded `/ask` questions. The two HTTP/2 questions resolve to `src/urllib3/util/ssl_.py` and answer from the pull request #3456 and #3466 quotes; the questions that name no real entity refuse honestly. `scripts/check_live_answers.py` runs the six questions against a live server and prints every response, including each citation's quote and URL.

A repository is addressed by its **slug id** (`urllib3/urllib3` → `urllib3-urllib3`); the graph build maps the slug back to the GitHub `owner/name` when it writes nodes.

The running example is the fixture repository `acme-netclient`, which does not exist on GitHub.
Its people, pull request numbers and quotes are fictional, and every response carries
`"fixture": true`.

Real-repository targets are defined under [`targets/`](targets/):

| file | repository | status |
|---|---|---|
| `urllib3__urllib3.json` | `urllib3/urllib3` | test bed, ingested on this machine |
| `sqlalchemy__alembic.json` | `sqlalchemy/alembic` | draft, never ingested |

### Build Phases at a Glance

| Phase | Title | Status | What It Delivers |
|:---:|---|:---:|---|
| **0** | **Contract & Fixtures** | ✅ Complete | Frozen Pydantic v2 schemas, OpenAPI specification, synthetic fixture data source, and strict response rule validators. |
| **1** | **Data In (Ingestion)** | ✅ Complete | Clone-first `git log --follow`, GitHub GraphQL batched client (20 PRs/query), SQLite cache (`data/ingest.sqlite3`) with stable IDs, rate-limit backoff, and email redaction. |
| **2** | **Linking & Decision Extraction** | ✅ Complete | Deterministic link extraction (`REVERTS`, `PART_OF`, `REFERENCES`, `SUPERSEDES`), AST constant & config history, 8 noise filters with revert protection, bounded token budget guard, prompt injection defense, Pydantic extraction schema, and 100% verbatim substring quote verification. |
| **3** | **Graph & Grounded Ask** | ✅ Complete | Neo4j schema & constraints, 384-dim vector index (created; retrieval uses local cosine over a one-hop neighbourhood, not the index), parameterized Cypher queries, `scripts/rebuild_graph.py`, 384-dim embeddings, rule-based entity resolution, hybrid GraphRAG retrieval, 4-gate refusal pipeline (G1–G4), grounded answer service with citation post-validation, and `GraphDataSource`. |
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
8. **Extraction CLI & Decision Auditing**:
   - [`scripts/extract.py`](scripts/extract.py) executes the extraction pipeline from SQLite cache.
   - Supports `--sample-review-file` to generate an opt-in review sample of extracted decisions verifying quote accuracy and rationale fallbacks.

### Phase 3: Neo4j Knowledge Graph & Grounded Ask Endpoint
Phase 3 builds the connected graph view and grounded retrieval pipeline:
1. **Neo4j Schema & Constraints** ([`backend/app/graph/schema.py`](backend/app/graph/schema.py)):
   - Unique ID constraints on all 11 node types (`Repository`, `CodeEntity`, `Decision`, `PullRequest`, `Commit`, `Issue`, `Discussion`, `Person`, `Evidence`, `Document`, `Incident`).
   - Property indexes on code entity paths, names, and decision states.
   - 384-dimensional cosine vector index (`decision_vector_index`) on `Decision.embedding`. It is created by the schema but is **not queried yet**; retrieval scores candidates with local cosine over a one-hop neighbourhood (see Retrieval below).
   - Full-text index on `Evidence.quote`.
2. **Parameterized Cypher Queries** ([`backend/app/graph/queries.py`](backend/app/graph/queries.py)):
3. **Graph Stores** ([`backend/app/stores/graph_store.py`](backend/app/stores/graph_store.py)):
   - `Neo4jGraphStore`: connects to Neo4j AuraDB with the official `neo4j` Python driver.
   - `InMemoryGraphStore`: provides in-memory graph operations so unit tests run with **zero credentials**.
4. **Single-Command Graph Rebuilder** ([`scripts/rebuild_graph.py`](scripts/rebuild_graph.py)):
   - Reads SQLite cache and restores the entire Neo4j graph with nodes, relationships, and embeddings in one command.
5. **384-dim Embeddings Provider** ([`backend/app/providers/embeddings.py`](backend/app/providers/embeddings.py)):
   - Integrates SentenceTransformers `all-MiniLM-L6-v2` with a deterministic offline hash projection fallback.
6. **Entity Resolution** ([`backend/app/services/entity_resolution.py`](backend/app/services/entity_resolution.py)):
   - Rule-based candidate matching from questions (paths, `UPPER_CASE` constants, dotted keys, quoted names).
   - An exact full-path or basename match beats a bare partial token match.
   - Ambiguity (`ambiguous_entity`) is kept only when two genuinely different entities tie.
     Tokens that come from the repository name, and path components contained in a longer
     named path, are ignored, so a generic word cannot tie the whole repository.
   - A question that names no entity falls back to the decisions whose own text matches it
     and takes the entity those decisions govern; a path that is named but not in the graph
     is `entity_not_found`.
   - Non-code questions return `out_of_scope`. Unmatched terms return `entity_not_found`.
7. **Hybrid GraphRAG Retrieval** ([`backend/app/services/retrieval.py`](backend/app/services/retrieval.py)):
   - Performs a single `GOVERNS` hop from the resolved entity. It does **not** traverse
     `SUPERSEDES` or `REVERTS`; see "Not implemented yet" below.
   - Bounded evidence bundle capped at `MAX_EVIDENCE_ITEMS` (12 items).
   - Semantic similarity is scored with **local cosine over the one-hop neighbourhood**.
     The 384-dim vector index (`decision_vector_index`) exists in the schema but is not
     queried; similarity is computed in process against the candidate decisions.
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

### Coverage: what was checked

A refusal must say what the repository history was examined for, not imply that no
history exists. The rebuild ([`scripts/rebuild_graph.py`](scripts/rebuild_graph.py))
computes coverage from the cache and stores it in the graph, so the API never reads
SQLite. The terms are defined by [`backend/app/services/coverage.py`](backend/app/services/coverage.py):

- **touched**: PRs (non-noise and noise) whose changed files include the entity path.
- **analyzed**: sources with a completed extraction run (`ok` or `no_decision`),
  whether or not a verified decision came out of it.
- **noise-skipped**: sources removed by the noise filter.
- **not analyzed**: touched PRs that were neither analyzed nor noise-skipped.
- **verified decision**: `quote_verified=1`.

Each `CodeEntity` stores `prs_touching`, `prs_analyzed`, `prs_noise_skipped`,
`prs_not_analyzed` and `verified_decisions`. The `Repository` node stores the
`scope` text (branch, commit window, ingested file paths and ingest caps),
`prs_fetched`, `sources_analyzed`, `prs_noise_skipped` and `verified_decisions`.
Refusal and partial-answer `evidence_gaps` text is built only from these stored
facts; no response field or gate changes.

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
pip install -e ".[embeddings]"
```

**Bash:**
```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
pip install -e ".[embeddings]"
```

> **Note on embeddings:** Installing `.[embeddings]` provides `sentence-transformers` for semantic similarity. Without it, the deterministic fallback embedder is used and answers are weaker.
>
> **Offline after the first download:** the first run that selects the local embedder downloads `all-MiniLM-L6-v2` from Hugging Face. After that download succeeds, set `$env:HF_HUB_OFFLINE="1"` before later runs to keep them offline. This is a Hugging Face environment variable, not a CodeWhy setting.

---

## Running Automated Tests

The test suite runs with **zero credentials and no required `.env` file**.

### Run the Phase 2 and Phase 3 tests

The full suite collects **975 tests**. It needs no credentials and no `.env` file; 963 pass out of the box, while 12 tests skip (5 marked `live` requiring `RUN_LIVE=1`, 6 on review probe files without PR references, and 1 on a review file whose tests cannot be counted).
```powershell
.\.venv\Scripts\pytest.exe backend/tests/unit/test_phase3.py backend/tests/unit/test_extraction.py backend/tests/unit/test_linking.py backend/tests/unit/test_config_keys.py backend/tests/unit/test_noise.py -v
```

### Run the full suite
```powershell
.\.venv\Scripts\pytest.exe backend/tests/unit/
```

### Run the live tests

The live tests are skipped by default. They ask the real graph and the real model,
so they need:

- network access;
- a real `.env` with `NEO4J_*` and `LLM_*` credentials;
- the embeddings extra (`sentence-transformers`) installed.

`RUN_LIVE=1` is the only switch. The test reads `.env` itself and forces
`offline=False`, so the real embedder is selected without also setting `OFFLINE`.

```powershell
$env:RUN_LIVE="1"
.\.venv\Scripts\pytest.exe backend/tests/unit/test_live_answers.py -v
```

If the real embedder is not available the live test fails, rather than skipping,
with `live test needs the real embedder: install the embeddings extra and set OFFLINE=0`.
A green skip would hide the missing dependency.

---

## How to Run & Verify the Pipeline

### 1. Ingestion (`scripts/ingest.py`)
Plan ingestion for `urllib3/urllib3` without network or database writes:
```powershell
.\.venv\Scripts\python.exe scripts\ingest.py --repo urllib3/urllib3 --targets targets\urllib3__urllib3.json --dry-run
```
Run live ingestion (requires `GITHUB_TOKEN` in `.env`):
```powershell
.\.venv\Scripts\python.exe scripts\ingest.py --repo urllib3/urllib3 --targets targets\urllib3__urllib3.json --max-prs 50 --max-issues 50
```

### 2. Decision Extraction (`scripts/extract.py`)
Run decision extraction on cached repository data:
```powershell
.\.venv\Scripts\python.exe scripts\extract.py --repo urllib3/urllib3 --dry-run
```

### 3. Rebuild Knowledge Graph (`scripts/rebuild_graph.py`)
Rebuild all Neo4j nodes, relationships, and vector embeddings from the SQLite cache:
```powershell
.\.venv\Scripts\python.exe scripts\rebuild_graph.py --repo urllib3/urllib3
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
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/repositories/acme-netclient/ask" -Method Post -Body $body -ContentType "application/json"
```

---

## Guided Walkthrough

One command reads the real cache and the graph and walks through the whole pipeline
stage by stage, with the real numbers at each step. It is read only by default: it
never fetches from GitHub, never writes the cache or the graph, and never calls a
language model. It prints a plain-text report and exits non-zero if any self-check
fails, so it doubles as a check to run before a demo.

```powershell
.\walkthrough.cmd
```

The wrapper activates `.venv`, runs `scripts/walkthrough.py`, and saves the same
output to `walkthrough_report.txt`. To run it directly:

```powershell
.\.venv\Scripts\python.exe scripts\walkthrough.py
```

Useful flags: `--stage N` stops after stage N, `--pause` waits for Enter between
stages, `--with-llm` allows the answer path to call the model (otherwise the line
"LLM calls made" stays at 0), and `--out PATH` changes the report path.

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
| `LLM_PROVIDER` | `""` | Provider identifier: `openai`, `ollama`, `google`, `gemini`, `vllm`, `openrouter`, or `mock`. |
| `LLM_BASE_URL` | `""` | Custom OpenAI-compatible base URL. |
| `LLM_MAX_OUTPUT_TOKENS` | `4096` | Ceiling for a single LLM completion reply. |
| `ALLOW_MOCK_PROVIDERS` | `false` | When true, allows graph data source to run on in-memory mocks. |
| `OFFLINE` | `false` | When true, disables remote downloads and uses deterministic embeddings. |
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
|- backend/
|   |- app/
|   |   |- main.py                    # FastAPI application, CORS, error handlers
|   |   |- config.py                  # Pydantic BaseSettings and validators
|   |   |- api/                       # HTTP routes (/ask, /graph, /decisions, /health)
|   |   |- schemas/                   # Frozen contract models and validators
|   |   |- fixtures/                  # Synthetic dataset and the fixture data source
|   |   |- graph/
|   |   |   |- schema.py              # Neo4j constraints, indexes, 384-dim vector index
|   |   |   `- queries.py             # The Cypher the store actually executes
|   |   |- prompts/
|   |   |   |- extract_decision.md    # Extraction prompt with security boundaries
|   |   |   |- extract_decision.py    # Injection detection, untrusted-data delimiters
|   |   |   `- answer.md              # Grounded answering prompt
|   |   |- providers/
|   |   |   |- llm_provider.py        # LLM providers, mock provider, token budget
|   |   |   `- embeddings.py          # 384-dim embeddings and cosine similarity
|   |   |- services/
|   |   |   |- data_source.py         # DataSource protocol, get_data_source, GraphDataSource
|   |   |   |- errors.py              # DataSourceError shared across the data layer
|   |   |   |- ingest/                # Phase 1: git collection, GitHub GraphQL, pipeline
|   |   |   |- linking.py             # Deterministic links: REVERTS, PART_OF, REFERENCES,
|   |   |   |                          #   SUPERSEDES (document only), CONTAINS
|   |   |   |- config_keys.py         # AST constants and config value history
|   |   |   |- noise.py               # Noise filtering with revert protection
|   |   |   |- extraction.py          # Pydantic decision extraction
|   |   |   |- quote_check.py         # Verbatim quote verification
|   |   |   |- entity_resolution.py   # Rule-based resolution and the ambiguity margin
|   |   |   |- retrieval.py           # Single-hop GOVERNS retrieval, loads source text
|   |   |   |- gate.py                # The four-gate refusal pipeline
|   |   |   |- answer.py              # Grounded answering and citation validation
|   |   |   |- confidence.py          # Confidence formula, labels, contradiction cap
|   |   |   `- response_rules.py      # Contract response validators
|   |   `- stores/
|   |       |- sqlite_cache.py        # SQLite cache: raw objects, links, decisions, evidence
|   |       `- graph_store.py         # Neo4jGraphStore and InMemoryGraphStore
|   `- tests/
|       |- unit/                      # Unit tests, including the remediation regressions
|       |- integration/               # API contract tests over the fixture source
|       `- conftest.py
|- scripts/
|   |- ingest.py                      # Phase 1 ingestion CLI
|   |- extract.py                     # Phase 2 extraction and linking CLI
|   |- rebuild_graph.py               # Phase 3 graph build from the SQLite cache
|   |- inspect_cache.py               # Read-only cache inspection CLI
|   |- probe_targets.py               # Per-file and constant history probe
|   |- probe_history.py               # Full-history reverts and constant value changes
|   |- sample_repos.py                # Recent pull request sampling across candidates
|   |- export_contract.py             # Regenerates contract JSON files
|   |- check_live_answers.py          # Runs the six C13 questions against a live server
|   `- walkthrough.py                 # Read-only guided walkthrough of the whole pipeline
|- targets/
|   |- urllib3__urllib3.json          # Test bed targets for urllib3/urllib3
|   `- sqlalchemy__alembic.json       # Draft targets, never ingested
|- review/                            # Generated probe output, each naming its command
|   |- repo_sampling.md
|   |- history_probe.md
|   `- target_probe.md
|- contract/                          # Frozen API payloads and openapi.json
`- pyproject.toml                     # Dependencies and pytest configuration
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

## Attribution and quotes

An author is read from the ingested record, never from the model. `RawEvidenceItem` has no
`author` field, so a model response that invents one is ignored by the schema, and the value
stored is always the author parsed from the pull request or comment. An author that looks like
an email address is dropped rather than stored, in either the decision or the evidence row.

**Quotes are not redacted.** A quote must remain a verbatim, character-for-character substring
of its source or it is not a quote. Email-shaped text inside a quotation is therefore left
exactly as written, because altering it would break verification at answer time and make the
citation unverifiable. Author identity is the field that is held to the stricter rule.

## Not implemented yet

**Supersession is not implemented.** Rules 1, 2, 3 and 3b are not computed. Every decision is
written with `state = ACTIVE`, and nothing in the code derives a state from edges. There is no
revert-of-revert chain, so the case where B replaced A and C reverts B is not handled.

The linking layer *does* parse and store the evidence that supersession would later need:
`Commit -[REVERTS]-> Commit` edges from revert subjects and messages, `COMMIT -> PR`,
`REFERENCES` for closing issues, `SUPERSEDES` between documents from an ADR status line, and
`CONTAINS` for file containment. Those edges are written to the `links` table by
`scripts/extract.py` and replayed into the graph by `scripts/rebuild_graph.py`. Nothing reads
them to compute a state yet.

Retrieval does **not** traverse `SUPERSEDES` or `REVERTS`. It performs a single `GOVERNS` hop
from the resolved entity. `EvidenceBundle.supersession_chains` exists but is never populated.

The three decision fields `probable_superseded_by`, `conflicts_with` and `reaffirms` are declared
in the frozen contract and are **always empty**, because no code computes them. They are dead
schema surface until the supersession work lands.

Contradiction detection checks only whether a decision's stored state is `UNRESOLVED`. There is
no detection across opposing evidence.

## Known limitations

- **Confidence is a heuristic, not a calibrated probability.** `score` is the fixed weighted
  sum in [`services/confidence.py`](backend/app/services/confidence.py)
  (`0.30·directness + 0.20·provenance + 0.20·agreement + 0.15·relevance + 0.15·temporal_consistency − 0.30·contradiction`),
  not a benchmark-tuned value, and it is not calibrated against a labelled set. A correct answer
  grounded in a single verbatim quote can therefore reach `HIGH`.

## Real versus mock

Every response carries a `fixture` boolean. It is **derived**, never asserted: a response is
`fixture: false` only when the graph store is a real Neo4j instance **and** the language model
provider is a real one. Anything else is `fixture: true`, including refusals and error bodies.

A response is real (`fixture: false`) exactly when all of these hold:

| condition | how to check |
|---|---|
| `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` are set | `.env` |
| `LLM_PROVIDER` names a real provider and its credentials resolve | `.env` |

With `DATA_SOURCE=graph` and either one missing, the application refuses to start the graph
source and raises a `DataSourceError` naming what is absent. It will not serve invented answers.

To run deliberately against mocks, set `ALLOW_MOCK_PROVIDERS=true`. Every response then carries
`"fixture": true`, so a mock run cannot be mistaken for real history.

`MockLLMProvider` and `InMemoryGraphStore` both declare `is_real = False`. Any response built with
them is marked as a fixture regardless of how it is configured.

## License

MIT. See [LICENSE](LICENSE).
