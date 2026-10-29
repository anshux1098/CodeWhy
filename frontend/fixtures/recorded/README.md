# Recorded API Fixtures

- **Recorded Date**: 2026-10-29T19:42:02.063569+00:00
- **Git Commit**: `069e82f689e304482bdbe0dfde250b6d3b8705db`
- **Branch**: `ui-polish`
- **Backend URL**: `http://127.0.0.1:8000`
- **Data Source**: `graph` (Neo4j Aura live instance)

## How It Was Recorded
Recorded via repeatable script `record_fixtures.py` executed via `pnpm run record:fixtures`.
Every request was sent to a live running backend process with `DATA_SOURCE=graph`, `SQLITE_CACHE_PATH` unset, and `HF_HUB_OFFLINE=1`.
All keys in JSON fixtures are deterministically sorted.
The script asserts each endpoint matches its expected HTTP status code and fails immediately if any call drifts or returns an unexpected response code.

## Files
- `manifest.json`: Manifest index of all recorded endpoints, latencies, filenames, and descriptions.
- `snapshot_info.txt`: High-level recording metadata.
- `openapi.json`: OpenAPI 3.1.0 schema directly fetched from `/openapi.json`.
- `*.json`: Ground-truth endpoint responses (health, dependencies, repositories, decisions, graph, ask queries, refusals, 404s, and 422s).
