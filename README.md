# CodeWhy

> **Every line has a history. Find the reasoning, not just the code.**

CodeWhy answers *"why is this code like this?"* for a software repository by reconstructing engineering decisions from GitHub commits, pull requests, review discussions, issues, and design documents. It links decisions to code entities in a Neo4j knowledge graph and answers natural-language questions with traceable verbatim citations—or refuses honestly when repository history does not support an assertion.

---

## What CodeWhy Solves

Standard tools like `git blame` only tell you **who** touched a line and **when**. They do not tell you:
- **Why** the change was made (the trade-offs, discarded alternatives, and rationale).
- **Which discussions** led to the decision (PR comment threads, issue conversations, design documents).
- **What constraints** governed the implementation (bug workarounds, performance trade-offs, backward compatibility requirements).

CodeWhy builds a queryable, grounded knowledge graph that bridges code entities directly to historical engineering decisions with 100% verified verbatim source evidence.

---

## Key Features

- **Grounded Decision Extraction**: Extracts structured architectural decisions from PR reviews and issues using LLMs with prompt-injection boundaries and token budgets.
- **100% Verbatim Quote Verification**: Every quote cited in an answer is verified as an exact character-for-character substring of the original source text. Unverified quotes are dropped.
- **4-Gate Refusal Pipeline**:
  - **Gate 1 (Entity Resolution)**: Identifies the code entity or flags ambiguous/unrecognized symbols with disambiguation candidates.
  - **Gate 2 (Scope Check)**: Ensures questions pertain to the target repository's architectural history.
  - **Gate 3 (Path Traversal)**: Checks for connecting `GOVERNS` paths in the knowledge graph.
  - **Gate 4 (Evidence Verification)**: Validates that quotes and evidence meet required similarity thresholds before returning an answer.
- **Deterministic Linking Engine**: Automatically derives `REVERTS`, `PART_OF`, `REFERENCES`, `CONTAINS`, and `SUPERSEDES` relationships from commit trailers, squash subjects, and ADR document headers.
- **AST Constant & Config History**: Uses Python `ast` parsing to trace value changes of uppercase constants across commit diffs.
- **Noise Filtering with Revert Protection**: Flags bot updates, dependency bumps, and formatting commits while strictly protecting historical revert targets.
- **Interactive Knowledge Graph UI**: Visual interface for inspecting repository subgraphs, browsing decision timelines, and asking historical questions.

---

## Architecture & Technology Stack

| Component | Technology | Description |
|---|---|---|
| **Backend API** | Python 3.11+, FastAPI, Pydantic v2, Uvicorn | Strict schema-validated REST API (`/api/v1`). |
| **Knowledge Graph** | Neo4j 5.x Aura / Community | Graph database storing repositories, entities, PRs, commits, issues, and decisions with typed relationships. |
| **LLM Reasoning** | Gemini, OpenAI, or OpenRouter | Grounded decision extraction and retrieval answering with verbatim quote verification. |
| **Embeddings** | `sentence-transformers` (`all-MiniLM-L6-v2`) | 384-dimensional semantic embeddings for entity resolution and similarity search. |
| **Ingestion Cache** | SQLite (`data/ingest.sqlite3`) | Resumable SQLite cache storing raw GitHub GraphQL payloads, commit diffs, and redacted author metadata. |
| **Frontend UI** | React 19, TypeScript, Vite, Tailwind CSS v4 | Interactive workbench for graph visualization, decision browsing, and historical investigation. |

---

## Knowledge Graph Model

```
(Repository) ──[:CONTAINS]──> (CodeEntity) <──[:GOVERNS]── (Decision)
      │                              │                           │
      │                              │                     [:SUPPORTED_BY]
      │                              ▼                           ▼
      ├───────────[:CONTAINS]──> (Commit) <──[:DECIDED_IN]── (Evidence)
      │                              │
      │                         [:PART_OF]
      │                              │
      │                              ▼
      └───────────[:CONTAINS]──> (PullRequest) <──[:REFERENCES]── (Issue)
                                     │
                                 [:REVERTS]
                                     │
                                     ▼
                                (PullRequest)
```

### Node Types
- `Repository`: Ingested software repository root.
- `CodeEntity`: File, function, class, or configuration constant.
- `Decision`: Extracted architectural choice or policy.
- `Evidence`: Verbatim quotation extracted from a review or issue.
- `PullRequest` & `Commit`: Version control artifacts.
- `Issue` & `Discussion`: GitHub issue threads and design discussions.
- `Document`: Architectural Decision Records (ADRs) and design documentation.

### Core Relationships
- `GOVERNS`: Connects a `Decision` to the `CodeEntity` it affects.
- `SUPPORTED_BY`: Connects a `Decision` to its underlying `Evidence` items.
- `DECIDED_IN`: Links a `Decision` to the `PullRequest`, `Commit`, or `Document` where it originated.
- `PART_OF`: Connects a `Commit` to its parent `PullRequest`.
- `REFERENCES`: Links pull requests to referenced issues.
- `REVERTS`: Explicit revert relationships between commits or pull requests.
- `SUPERSEDES`: Replaces an earlier decision or ADR with a newer one.

---

## API Endpoints

All endpoints are versioned under `/api/v1`:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check returning engine status and active data source (`graph` or `fixture`). |
| `GET` | `/dependencies` | Configuration status of external dependencies (Neo4j, LLM, GitHub, embeddings). |
| `GET` | `/repositories` | List all ingested repositories with counts of decisions, entities, PRs, and commits. |
| `GET` | `/repositories/{id}` | Detailed repository metadata, scope, and ingestion telemetry. |
| `GET` | `/entities` | Search code entities within a repository by identifier, symbol, or file path. |
| `GET` | `/decisions` | List decisions for a repository or entity, with optional state filtering. |
| `GET` | `/decisions/{id}` | Full decision detail with supporting evidence quotes, source URLs, and governing entities. |
| `POST` | `/ask` | Ask a natural-language question about the repository. Returns a grounded answer with citations or an honest refusal. |
| `GET` | `/graph` | Subgraph payload for interactive visualization, filtered by entity or repository. |

---

## Local Setup & Development

### 1. Prerequisites
- Python 3.11+
- Node.js 18+ and `npm`
- Git
- Neo4j instance (Neo4j Aura or local Neo4j 5.x) — *optional if running with mock providers*

### 2. Environment Configuration
Copy the configuration template:
```bash
cp .env.example .env
```

Configure `.env`:
```env
# GitHub Credentials
GITHUB_TOKEN=your_github_token

# Neo4j Database Credentials
NEO4J_URI=neo4j+s://your-instance.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_password
NEO4J_DATABASE=neo4j

# LLM Configuration
LLM_PROVIDER=google
LLM_MODEL=gemini-2.5-flash
LLM_API_KEY=your_llm_api_key

# Operational Settings
DATA_SOURCE=graph            # 'graph' for real Neo4j, 'fixture' for mock testing
ALLOW_MOCK_PROVIDERS=false   # Set to true for offline testing without credentials
BACKEND_HOST=127.0.0.1
BACKEND_PORT=8000
```

### 3. Backend Setup
```bash
# Set up Python virtual environment
python -m venv .venv

# Activate virtual environment
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# Install backend dependencies in editable mode
pip install -e backend

# Verify configuration and external connections
python scripts/preflight.py --connect

# Start backend server
uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

### 4. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173` in your browser.

---

## Pipeline CLI Workflow

To ingest, extract, and build the knowledge graph for a repository:

```bash
# 1. Ingest GitHub repository history into SQLite cache
python scripts/ingest.py targets/urllib3__urllib3.json

# 2. Extract decisions, links, and constant histories
python scripts/extract.py --repo urllib3/urllib3

# 3. Rebuild the Neo4j knowledge graph from the cache
python scripts/rebuild_graph.py urllib3/urllib3

# 4. Verify live answering against the graph
python scripts/check_live_answers.py --repo urllib3/urllib3
```

---

## Testing & Quality Assurance

CodeWhy enforces strict contract tests, schema invariants, and regression tests:

```bash
# Run backend unit tests
pytest backend/tests/unit/

# Run API contract integration tests
pytest backend/tests/integration/

# Test live external service connectivity
python scripts/preflight.py --connect

# Build frontend to verify TypeScript types and bundle integrity
cd frontend
npm run build
```

---

## Project Structure

```
CodeWhy/
|-- backend/
|   |-- app/
|   |   |-- api/              # FastAPI route definitions (/health, /repositories, /decisions, /ask, /graph)
|   |   |-- fixtures/         # Synthetic fixture data source for offline/testing mode
|   |   |-- graph/            # Cypher queries, schema definitions, and index queries
|   |   |-- prompts/          # Decision extraction and grounded answering prompts
|   |   |-- providers/        # LLM (Gemini, OpenAI) and local embedding providers
|   |   |-- schemas/          # Strict Pydantic v2 contract models
|   |   |-- services/         # Ingestion, deterministic linking, AST extraction, 4-gate refusal pipeline
|   |   `-- stores/           # Neo4jGraphStore, InMemoryGraphStore, and SQLite cache store
|   `-- tests/
|       |-- unit/             # Unit tests for linking, extraction, gating, confidence scoring
|       `-- integration/      # API contract validation tests
|-- frontend/
|   |-- src/                  # React UI components, views, services, and styles
|   |-- public/               # Favicon, logo, and static assets
|   `-- package.json          # Frontend dependencies and scripts
|-- scripts/                  # CLI utilities (ingest, extract, rebuild_graph, preflight, evaluate)
|-- targets/                  # Target repository configuration specifications
|-- data/                     # Local SQLite caches (gitignored)
|-- contract/                 # Frozen OpenAPI specifications and contract payloads
|-- .env.example              # Environment variables template
`-- pyproject.toml            # Python packaging and dependency declarations
```

---

## Real vs. Mock Operation

Every response carries a `fixture` boolean flag. It is dynamically **derived** based on your environment:
- `fixture: false`: The response was retrieved from a real Neo4j database using a real LLM provider.
- `fixture: true`: The response was served by fixture data or an in-memory mock store.

If `DATA_SOURCE=graph` is configured but database credentials or LLM keys are missing, the server safely refuses to start to prevent serving ungrounded or fabricated history.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
