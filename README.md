# CodeWhy

Answers "why is this code like this?" for a repository, by reconstructing engineering
decisions from commit, pull request, issue and design-doc history.

**Phase 0 is fixtures only.** The API contract is frozen and served from synthetic data, so a
frontend can be built in parallel. No ingestion, extraction, graph, LLM, embeddings, entity
resolution, refusal gate or supersession logic exists yet, and every response says so with
`"fixture": true`.

The fixture repository `acme/netclient` does not exist. Its people (`priya`, `marco`, `lena`,
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
Invoke-RestMethod "$base/repositories/acme/netclient"
Invoke-RestMethod "$base/repositories/acme/netclient/entities?q=retry"
Invoke-RestMethod "$base/decisions/dec_77"
Invoke-RestMethod "$base/repositories/acme/netclient/graph"
Invoke-RestMethod "$base/repositories/acme/netclient/ask" -Method Post -Body (@{question = "Why is MAX_RETRIES 3?"} | ConvertTo-Json) -ContentType "application/json"
```

bash:

```bash
base=http://127.0.0.1:8000/api/v1
curl "$base/health"
curl "$base/repositories/acme/netclient"
curl "$base/repositories/acme/netclient/entities?q=retry"
curl "$base/decisions/dec_77"
curl "$base/repositories/acme/netclient/graph"
curl -X POST "$base/repositories/acme/netclient/ask" -H 'content-type: application/json' -d '{"question": "Why is MAX_RETRIES 3?"}'
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
