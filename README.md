# CodeWhy

Answers "why is this code like this?" for a repository, by reconstructing engineering
decisions from commit, pull request, issue and design-doc history.

**Phase 0 is fixtures only.** The API contract is frozen and served from synthetic data, so a
frontend can be built in parallel. No ingestion, extraction, graph, LLM, embeddings, entity
resolution, refusal gate or supersession logic exists yet, and every response says so with
`"fixture": true`.

The fixture repository `acme-netclient` does not exist. Its people (`priya`, `marco`, `lena`,
`tom`), pull request numbers and quotes are fictional.

## Requirements

Python 3.12.

## Install

PowerShell:

```powershell
cd codewhy
py -V:3.12-arm64 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

bash:

```bash
cd codewhy
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

The `-arm64` suffix selects the 64-bit ARM build of Python 3.12, which is the only 3.12
interpreter installed on the development machine. On a machine whose default 3.12 is the
regular x64 build, drop the suffix and use `py -V:3.12 -m venv .venv`.

If PowerShell refuses to run `Activate.ps1` because script execution is disabled, either run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or skip activation entirely and
call the virtual environment's interpreter by its full path as shown below.

## Run the tests

PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest
```

Without activating, in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

bash:

```bash
source .venv/bin/activate
python -m pytest
```

Without activating, in bash:

```bash
./.venv/bin/python -m pytest
```

Activation is a convenience, not a requirement. `python` on your PATH is only the virtual
environment's interpreter once `Activate.ps1` or `source .venv/bin/activate` has run; calling
the interpreter by its full path works whether or not you have activated anything.

The suite needs no credentials and no `.env` file.

## Start the app

PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

bash:

```bash
source .venv/bin/activate
uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

Without activating, in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

- API docs: <http://127.0.0.1:8000/docs>
- OpenAPI: <http://127.0.0.1:8000/openapi.json>
- CORS allows `http://localhost:5173`, which is the Vite dev server.
  A page opened at `http://127.0.0.1:5173` is a different origin and is blocked, so serve the frontend on `localhost`.

## Export the contract

`contract/` is generated, never edited by hand.

PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python scripts/export_contract.py
```

bash:

```bash
source .venv/bin/activate
python scripts/export_contract.py
```

The exporter writes ten response payloads and `openapi.json`. A clean tree after running it means
the committed contract still matches the code:

```powershell
git status --porcelain contract
```

## Try it

PowerShell:

```powershell
$base = "http://127.0.0.1:8000/api/v1"
Invoke-RestMethod "$base/health"
Invoke-RestMethod "$base/repositories/acme-netclient"
Invoke-RestMethod "$base/repositories/acme-netclient/entities?q=retry"
Invoke-RestMethod "$base/decisions/dec_77"
Invoke-RestMethod "$base/repositories/acme-netclient/graph"
Invoke-RestMethod "$base/repositories/acme-netclient/ask" -Method Post -Body (@{question = "Why is MAX_RETRIES 3?"} | ConvertTo-Json) -ContentType "application/json"
```

bash:

```bash
base=http://127.0.0.1:8000/api/v1
curl "$base/health"
curl "$base/repositories/acme-netclient"
curl "$base/repositories/acme-netclient/entities?q=retry"
curl "$base/decisions/dec_77"
curl "$base/repositories/acme-netclient/graph"
curl -X POST "$base/repositories/acme-netclient/ask" -H 'content-type: application/json' -d '{"question": "Why is MAX_RETRIES 3?"}'
```

## Fixture questions and what they return

| Question | Outcome | Reason code |
|---|---|---|
| `Why is MAX_RETRIES 3?` | `full` | null |
| `Is MAX_RETRIES still 6?` | `full` | null |
| `Why does config.py change so often?` | `full` | null |
| `Why is RETRY_BACKOFF_MS configurable?` | `partial` | null |
| `Why did the netclient package move that helper into its own module?` | `partial` | `no_verified_quote` |
| `Why is _PAD_BYTES 17?` | `refusal` | `no_decision_path` |
| `Why is retry set this way?` | `refusal` | `ambiguous_entity` |
| `Why is TIMEOUT_MS 500?` | `refusal` | `entity_not_found` |
| `Why was the team late for the demo?` | `refusal` | `out_of_scope` |

The fixture router splits identifiers on non-alphanumeric characters and matches whole words on both
sides, so a question written in canonical spelling resolves its own entity, while the bare word
`retry` matches both `retry.py` and `RETRY_BACKOFF_MS` and the answer is `ambiguous_entity`. That is the
same behaviour the real picker will have. The `no_verified_quote` example deliberately avoids the word
`retry`, because a question containing it ties between two entities and is refused as
`ambiguous_entity` instead.

## Confidence rules

These are enforced by validators, so an invalid response cannot be constructed:

- `confidence.label` is derived from `confidence.score`: 0.75 or more is HIGH, 0.50 up to but
  not including 0.75 is MEDIUM, below 0.50 is LOW. A supplied label that disagrees with the
  score is rejected, not silently corrected.
- `full` requires HIGH and at least one citation of kind `SOURCE`.
- `partial` requires MEDIUM, or MEDIUM or LOW when `reason_code` is `no_verified_quote`.
  HIGH is never allowed on a partial.
- `entity_not_found`, `ambiguous_entity` and `out_of_scope` happen before scoring, so
  `confidence` is null for them. `no_decision_path` and `low_score` carry a score.
- If `signals.contradiction` is 1 the score is capped at 0.70. `contradiction` is a binary
  `Literal[0.0, 1.0]`, so no intermediate value can bypass the cap. The best score the section 7
  formula can produce with contradiction 1 is 0.30 + 0.20 + 0.20 + 0.15 + 0.15 minus 0.30,
  which is 0.70, so a response with contradiction 1 can never be `full`.

The score is a weighted sum of evidence signals. It is a ranking aid, not a probability.

## Configuration

Copy `.env.example` to `.env` to change anything. Nothing is required in Phase 0: the app
imports and the tests run with an empty environment. Credentials are validated only when the
feature that needs them runs, through `Settings.require_github()`, `require_neo4j()`,
`require_llm()` and `require_embeddings()`.

`DATA_SOURCE` picks the data-source implementation. Phase 0 ships only `fixture`;
`GraphDataSource` arrives in Phase 3.

`MAX_GRAPH_NODES` can only **lower** the `/graph` node cap, never raise it. The hard cap is
`GRAPH_NODE_CAP` in `backend/app/schemas/common.py`, which every `GraphResponse` is validated
against; a value above it is rejected at startup rather than silently ignored.

## Layout

```
backend/app/api         HTTP layer, no logic beyond translating HTTP
backend/app/schemas     the frozen contract and its validators
backend/app/services    data-source protocol, confidence, response rules
backend/app/fixtures    synthetic dataset and the fixture data source
backend/tests           unit and integration tests
contract/               generated contract for the frontend
scripts/                contract exporter
```

## What is not built yet

Ingestion, extraction, Neo4j, LLM calls, embeddings, real entity resolution, the refusal gate,
supersession rules, evidence-based confidence scoring. `stores/`, `graph/`, `providers/` and
`prompts/` are placeholders. `low_score` has a validator rule but no fixture response, because
scoring arrives in a later phase. Supersession states in the fixtures are hand-written to match
the section 6 rules; no code computes them yet.

## License

MIT. See [LICENSE](LICENSE).

## Ingestion (Phase 1b)

Ingestion is **repo-agnostic**. The repository and its demo targets are inputs, never code.
Swapping to a different repository is a command-line change plus a new targets file; no code
is edited.

### Targets file

`targets/<owner>__<repo>.json`, validated with Pydantic. Unknown fields are rejected, and a
`config_keys` entry must point at a file that is also listed in `files`.

```json
{
  "repo": "owner/repo",
  "files": ["src/pkg/a.py", "src/pkg/b.py"],
  "dirs": ["docs/"],
  "config_keys": [{ "file": "src/pkg/a.py", "name": "SOME_CONSTANT" }]
}
```

- `repo` must match `--repo` exactly, or ingestion refuses to start.
- `files` are tracked with `git log --follow`, so renames are followed.
- `dirs` are extra document directories to scan alongside `docs/`, `adr/` and `rfcs/`.
- `config_keys` are the constants you expect to have value histories.

### Running it

```powershell
# Plan only. No network call, no clone, no database writes.
.\.venv\Scripts\python.exe scripts\ingest.py --repo owner/repo --targets targets\owner__repo.json --dry-run

# Ingest.
.\.venv\Scripts\python.exe scripts\ingest.py --repo owner/repo --targets targets\owner__repo.json

# Bound the recency fill. Target pull requests and issues never count against these bounds.
.\.venv\Scripts\python.exe scripts\ingest.py --repo owner/repo --targets targets\owner__repo.json --max-prs 40 --max-issues 40

# Refetch objects already in the cache.
.\.venv\Scripts\python.exe scripts\ingest.py --repo owner/repo --targets targets\owner__repo.json --refresh
```

Requires `GITHUB_TOKEN` in `.env`. Output goes to stdout, `data/ingest_summary.json` and the
SQLite cache at `data/ingest.sqlite3`. Everything under `data/` is git-ignored, and no
ingested data is ever committed.

### Cache

Plain `sqlite3`, no ORM, at `data/ingest.sqlite3`:

| table | contents |
|---|---|
| `raw_objects` | cached PRs, issues, commits and documents under stable ids such as `pr:owner/repo#123` |
| `commits` | commit metadata, author **name** only, never the email, plus `closing`, `mentions`, `pull_requests` and `trailers` |
| `commit_files` | per commit path, old path for renames, status, diff and `diff_truncated` |
| `ingest_runs` | one row per run with status and GraphQL cost |
| `skips` | what a bound stopped, with the reason, the count and the `bound` actually used |
| `missing` | numbers that resolved to neither a pull request nor an issue |

Rerunning creates no duplicates and refetches nothing already cached unless `--refresh`. A
rerun of the urllib3 test bed dropped the GraphQL cost from 170 to 9 with identical row counts.

A cache file created by an older build gains new columns on open; nothing needs to be deleted.

### Inspecting a cache

Read only. No network call, no writes, no credentials.

```powershell
.\.venv\Scripts\python.exe scripts\inspect_cache.py
.\.venv\Scripts\python.exe scripts\inspect_cache.py --repo owner/repo
.\.venv\Scripts\python.exe scripts\inspect_cache.py --repo owner/repo --json
```

It prints commit and commit-file counts, how many commit files have an empty or truncated diff,
how many commits carry reference trailers, the objects per kind, the skips with their bounds,
the numbers that could not be resolved, the last runs and the busiest paths. It is the fastest
way to confirm a run collected what it claims.

### Commit trailers and `(#123)`

Two different signals, deliberately kept apart:

- **`(#123)` in a subject** means the commit came from that pull request. It is a link, not a
  statement of intent, and it is exempt from the recency bounds so target history is never
  truncated.
- **A trailer block** at the end of the message is a statement someone made deliberately:
  `Fixes:`, `Closes:` and `Resolves:` are closing references; `References:` and `Related:` are
  mentions; `Pull-request: <url>` is a link, used only when the URL names the same repository.

Only the final paragraph of a message is read as trailers, so a line like `Fixes: #99` in the
middle of a discussion is not mistaken for one. `Fixes #5` written in prose is deliberately not
a closing reference, because it carries no intent signal. A trailer may also carry values with
no number at all, such as `Change-Id:` or `Pull-request-sha:`; those are stored verbatim.

### Test bed

`targets/urllib3__urllib3.json` is a **test bed, not a decision**. It exercises the pipeline
against `urllib3/urllib3` because that clone already exists on this machine. The real
repository has not been chosen; replace this file and pass a different `--repo` when you decide.

### Draft target: `sqlalchemy/alembic`

`targets/sqlalchemy__alembic.json` is a **draft chosen from measurements, not a decision**.
Every number behind it is in `review/`, measured from a full clone with plain `git`, and the
probes never import or execute target code.

| file | commits | PR-linked | reverted | long messages |
|---|---|---|---|---|
| `alembic/autogenerate/api.py` | 55 | 0 | 1 | 27 |
| `alembic/autogenerate/render.py` | 116 | 0 | 1 | 58 |
| `alembic/ddl/base.py` | 49 | 0 | 1 | 21 |
| `alembic/ddl/impl.py` | 110 | 0 | 1 | 47 |
| `alembic/operations/ops.py` | 165 | 5 | 0 | 62 |

- `docs/` and `docs/build/` are the document directories. Alembic has no `changelog/` directory:
  the changelog lives in `docs/build/changelog.rst`, and the top-level `CHANGES` is a redirect
  file that only points at it.
- The only config key is `MAX_PYTHON_ARGS` in `alembic/autogenerate/render.py` (currently 255,
  2 commits touching the defining line). It is the sole module constant in the repository with
  at least 2 line-touching commits **that also lives in a target file**.
- `USE_TWOPHASE` in `alembic/templates/multidb/env.py` also has 2 commits and is excluded only
  because that file is not a target; a config key must point at a listed file.
- No class-level constant in the repository has 2 or more commits, so none is listed.

Caveats worth stating plainly. Four of the five files have **zero** PR-linked commits and each
has exactly one revert, which is the same `pep484 updates` revert in three of them, so the
revert counts are not independent signals. The whole history is 2095 commits with 5 reverts
total, so this is a repository with unusually little revert history, which limits how much
supersession evidence it can offer at all. A recent-PR sample over a 2018-11-30 to 2026-06-30
window returned only 49 merged pull requests, of which 16 were reviewed and 2 read as incident
work: thin ground for a reasoning corpus whatever the targets.

### What ingestion does and does not do

- Commits come from `git` only. Pull requests and issues come from GraphQL, batched at most 20
  aliases per request, reusing `GitHubGraphQLClient`. No REST client exists.
- `(#123)` in a commit subject is treated as a pull request number, and `Fixes #5` is not.
  Numbers that do not resolve to a pull request are recorded as unresolved rather than failing
  the run, because in older histories those references are usually issues.
- Repository text is stored as untrusted data. Nothing is imported or executed, no author
  email is ever stored, and INFO-level logging records counts and ids only.
- Every connection records a `truncated` flag when more pages existed than were fetched.
