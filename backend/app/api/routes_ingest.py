from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.services.ingest.auto_targets import auto_discover_targets
from app.services.ingest.git_probe import InvalidRepositoryError, normalize_repo_slug
from app.stores.ingest_jobs import IngestJobStore

logger = logging.getLogger("codewhy.ingest_api")

router = APIRouter(tags=["ingest"])

# Single shared store for the lifetime of the process
_JOB_STORE = IngestJobStore(Path("data/ingest_jobs.sqlite3"))

_REPO_RE = re.compile(r"^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$")


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class IngestRequest(BaseModel):
    repo: str
    mode: Literal["quick", "deep"] = "quick"
    max_prs: Optional[int] = None
    files: list[str] = Field(default_factory=list)
    dirs: list[str] = Field(default_factory=list)


class IngestJobResponse(BaseModel):
    job_id: str
    repo: str
    status: str
    phase: str | None = None
    progress_pct: int = 0
    started_at: str
    finished_at: str | None = None
    error: str | None = None
    result_repo_id: str | None = None


# ---------------------------------------------------------------------------
# File-ranking helper (inlined from auto_targets logic)
# ---------------------------------------------------------------------------


def _run_ingest_background(
    job_id: str,
    repo: str,
    max_prs: Optional[int],
    job_store: IngestJobStore,
    mode: Literal["quick", "deep"] = "quick",
    files: Optional[list[str]] = None,
    dirs: Optional[list[str]] = None,
) -> None:
    """Synchronous ingest pipeline — runs in FastAPI's thread-pool background."""
    finished_at_now = lambda: datetime.now(timezone.utc).isoformat()
    effective_max_prs = max_prs if max_prs is not None else (25 if mode == "quick" else 200)
    top_n = 8 if mode == "quick" else 20

    try:
        # ── Phase 1: clone ───────────────────────────────────────────────
        job_store.update_job(
            job_id,
            status="cloning",
            phase=f"Cloning {repo} ({'Quick Start' if mode == 'quick' else 'Deep Scan'})...",
            progress_pct=10,
        )

        # Resolve paths relative to the process CWD (the project root when
        # launched via `uvicorn --app-dir backend`)
        clone_root = Path("data/clones")
        targets_dir = Path("targets")
        targets_dir.mkdir(parents=True, exist_ok=True)

        # Import ingest helpers (available inside the backend package)
        from app.config import settings as _settings
        from app.services.ingest.git_probe import clone_repository, parse_slug
        from app.services.ingest.targets import IngestTargets
        from app.stores.sqlite_cache import SqliteCache
        from app.services.ingest.github_client import GitHubGraphQLClient
        from app.services.ingest.pipeline import run_ingest

        owner, name = parse_slug(repo)

        # Clone (or update) the repository
        clone_path = clone_repository(
            repo,
            clone_root,
            size_limit_mb=_settings.max_repo_size_mb,
            fast_clone=(mode == "quick"),
        )

        # ── Phase 2: zero-config auto-target discovery ──────────────────
        job_store.update_job(job_id, status="fetching", phase="Discovering hotspot files & constants...", progress_pct=25)
        targets_path = targets_dir / f"{owner}__{name}.json"

        explicit_files = [f.strip() for f in (files or []) if f and f.strip()]
        if explicit_files:
            targets = IngestTargets(
                repo=repo,
                files=explicit_files,
                dirs=[d.strip() for d in (dirs or []) if d and d.strip()],
                config_keys=[],
            )
            targets_path.write_text(targets.model_dump_json(indent=2), encoding="utf-8")
        else:
            targets = auto_discover_targets(
                repo,
                clone_path,
                top_n=top_n,
                commit_window=200,
                save_path=targets_path,
            )

        # ── Phase 3 & 4: fetch PRs & commits ────────────────────────────
        cache_path = Path("data/ingest.sqlite3")
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        def _on_progress(_stage: str, current: int, total: int, message: str) -> None:
            pct = max(25, min(65, int(25 + (current / max(total, 1)) * 40)))
            job_store.update_job(job_id, status="fetching", phase=message, progress_pct=pct)

        with SqliteCache(cache_path) as cache, GitHubGraphQLClient(_settings) as client:
            run_ingest(
                repo=repo,
                targets=targets,
                settings=_settings,
                cache=cache,
                clone_root=clone_root,
                client=client,
                max_prs=effective_max_prs,
                fast_clone=(mode == "quick"),
                on_progress=_on_progress,
            )

        # ── Phase 5: extract decisions & evidence quotes ────────────────
        job_store.update_job(job_id, status="extracting", phase="Extracting architectural decisions and verifying evidence quotes...", progress_pct=75)

        extract_cmd = [
            sys.executable,
            "scripts/extract.py",
            "--repo",
            repo,
            "--cache",
            str(cache_path),
            "--targets",
            str(targets_path),
            "--max-sources",
            "15",
        ]
        logger.info("Running decision extraction: %s", " ".join(extract_cmd))
        subprocess.run(extract_cmd, check=True)

        # ── Phase 6: rebuild Neo4j knowledge graph ─────────────────────
        job_store.update_job(job_id, status="indexing", phase="Populating Neo4j knowledge graph...", progress_pct=90)

        rebuild_cmd = [
            sys.executable,
            "scripts/rebuild_graph.py",
            "--repo",
            repo,
            "--cache",
            str(cache_path),
        ]
        logger.info("Rebuilding Neo4j graph: %s", " ".join(rebuild_cmd))
        subprocess.run(rebuild_cmd, check=True)

        # Also hydrate the running process's InMemoryGraphStore when Neo4j is in fallback mode
        try:
            from app.api.deps import get_source
            from app.stores.graph_store import InMemoryGraphStore
            from scripts.rebuild_graph import rebuild_graph as _rebuild_in_process

            live_source = get_source(_settings)
            live_store = getattr(live_source, "store", None)
            if isinstance(live_store, InMemoryGraphStore):
                _rebuild_in_process(repo, cache_path, live_store, cfg=_settings)
        except Exception as sync_exc:  # noqa: BLE001
            logger.warning("In-process graph sync skipped for %s: %s", repo, sync_exc)

        # ── Phase 7: done ───────────────────────────────────────────────
        result_repo_id = repo.replace("/", "-")
        job_store.update_job(
            job_id,
            status="done",
            phase="Ingestion complete. Knowledge graph ready.",
            progress_pct=100,
            finished_at=finished_at_now(),
            result_repo_id=result_repo_id,
        )
        logger.info("Ingest job %s fully completed for %s → %s", job_id, repo, result_repo_id)

    except Exception as exc:  # noqa: BLE001
        logger.exception("Ingest job %s failed: %s", job_id, exc)
        job_store.update_job(
            job_id,
            status="failed",
            phase="Ingestion failed.",
            finished_at=finished_at_now(),
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/repositories/ingest",
    status_code=202,
    summary="Kick off async ingestion of a GitHub repository",
)
def start_ingest(
    request: IngestRequest,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    try:
        normalized_repo = normalize_repo_slug(request.repo)
    except InvalidRepositoryError as exc:
        raise HTTPException(
            status_code=422,
            detail="repo must be a GitHub URL or owner/name (e.g. pallets/flask)",
        ) from exc
    if not _REPO_RE.match(normalized_repo):
        raise HTTPException(
            status_code=422,
            detail="repo must match ^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$ (e.g. owner/name)",
        )
    job_id = _JOB_STORE.create_job(normalized_repo)
    background_tasks.add_task(
        _run_ingest_background,
        job_id,
        normalized_repo,
        request.max_prs,
        _JOB_STORE,
        request.mode,
        request.files,
        request.dirs,
    )
    return JSONResponse(
        status_code=202,
        content={
            "job_id": job_id,
            "repo": normalized_repo,
            "mode": request.mode,
            "status": "queued",
        },
    )


@router.get(
    "/repositories/ingest",
    summary="List recent ingest jobs",
)
def list_ingest_jobs(repo: str | None = None) -> dict:
    jobs = _JOB_STORE.list_jobs(repo=repo)
    return {"jobs": jobs}


@router.get(
    "/repositories/ingest/{job_id}",
    response_model=IngestJobResponse,
    summary="Poll the status of an ingest job",
)
def get_ingest_job(job_id: str) -> IngestJobResponse:
    job = _JOB_STORE.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Ingest job {job_id!r} not found")
    return IngestJobResponse(**job)


@router.get(
    "/repositories/ingest/{job_id}/stream",
    summary="Stream live SSE progress updates for an ingest job",
)
async def stream_ingest_job(job_id: str) -> StreamingResponse:
    initial = _JOB_STORE.get_job(job_id)
    if initial is None:
        raise HTTPException(status_code=404, detail=f"Ingest job {job_id!r} not found")

    async def _event_generator():
        last_payload = ""
        while True:
            job = _JOB_STORE.get_job(job_id)
            if job is None:
                break
            payload = json.dumps(job)
            if payload != last_payload:
                last_payload = payload
                yield f"data: {payload}\n\n"
            if job.get("status") in ("done", "failed"):
                break
            await asyncio.sleep(1.0)

    return StreamingResponse(_event_generator(), media_type="text/event-stream")
