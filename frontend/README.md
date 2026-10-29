# CodeWhy Frontend

## Demo Mode

The demo runs with `DATA_SOURCE=graph` and `SQLITE_CACHE_PATH` unset. The SQLite data source does not carry dates, authors, coverage counts, or full supersession lineage, so `DATA_SOURCE=graph` is the recommended mode for accurate data.

## Prerequisites

- Node.js >= 22.12.0 (current: v22.11.0 works with warnings)
- pnpm 10.33.4+

## Install (fresh clone)

```bash
git clone <repo-url>
cd CodeWhy/frontend
pnpm install
```

## Run

```bash
pnpm dev          # Vite on 5173, proxied to 127.0.0.1:8000/api
pnpm build        # typecheck + production build
pnpm test         # Vitest unit tests
pnpm lint         # oxlint
pnpm check        # typecheck + lint + tests + build
pnpm preview      # preview production build
```

## Backend

Start the backend with:
```bash
DATA_SOURCE=graph python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Notes

- `pnpm-lock.yaml` is committed; `package-lock.json` is not used.
- The `@rolldown/binding-win32-x64-msvc` and `@oxlint/binding-win32-x64-msvc` packages are optional dependencies that may need manual installation on some systems.