from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.api import routes_ingest
from app.config import Settings
from app.main import create_app
from app.stores.ingest_jobs import IngestJobStore
from app.stores.sqlite_cache import SqliteCache


def test_sqlite_cache_wal_mode_and_batch_cross_repo_isolation():
    with TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "cache.sqlite3"
        with SqliteCache(db) as cache:
            mode = cache._connection.execute("PRAGMA journal_mode;").fetchone()[0]
            assert str(mode).lower() == "wal"

            cache.put_commits_and_files_batch(
                "org/repo-a",
                [{"sha": "aaa111", "subject": "init a", "message": "init a"}],
                [("aaa111", {"path": "src/a.py", "status": "M", "diff": "+x"})],
            )
            cache.put_commits_and_files_batch(
                "org/repo-b",
                [{"sha": "bbb222", "subject": "init b", "message": "init b"}],
                [
                    ("bbb222", {"path": "src/b1.py", "status": "M", "diff": "+y"}),
                    ("bbb222", {"path": "src/b2.py", "status": "M", "diff": "+z"}),
                ],
            )

            assert cache.count_commit_files("org/repo-a") == 1
            assert cache.count_commit_files("org/repo-b") == 2
            assert cache.count_commit_files() == 3


def test_ingest_sse_stream_emits_done_event():
    with TemporaryDirectory() as tmpdir:
        store = IngestJobStore(Path(tmpdir) / "jobs.sqlite3")
        job_id = store.create_job("pallets/flask")
        store.update_job(
            job_id,
            status="done",
            phase="Ingestion complete. Knowledge graph ready.",
            progress_pct=100,
            result_repo_id="pallets-flask",
        )
        orig_store = routes_ingest._JOB_STORE
        routes_ingest._JOB_STORE = store
        try:
            client = TestClient(create_app(config=Settings(data_source="fixture", offline=True)))
            resp = client.get(f"/api/v1/repositories/ingest/{job_id}/stream")
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
            assert '"status": "done"' in resp.text
            assert '"progress_pct": 100' in resp.text
        finally:
            routes_ingest._JOB_STORE = orig_store
