from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_objects (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    repo TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS raw_objects_kind_repo ON raw_objects (kind, repo);

CREATE TABLE IF NOT EXISTS commits (
    sha TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    authored_at TEXT,
    committed_at TEXT,
    author_name TEXT,
    subject TEXT,
    message TEXT,
    parent_shas TEXT,
    pull_requests TEXT
);

CREATE TABLE IF NOT EXISTS commit_files (
    sha TEXT NOT NULL,
    path TEXT NOT NULL,
    old_path TEXT,
    status TEXT,
    diff TEXT,
    diff_truncated INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (sha, path)
);
CREATE INDEX IF NOT EXISTS commit_files_path ON commit_files (path);

CREATE TABLE IF NOT EXISTS ingest_runs (
    id TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    graphql_cost INTEGER,
    summary TEXT
);

CREATE TABLE IF NOT EXISTS skips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    repo TEXT NOT NULL,
    kind TEXT NOT NULL,
    reason TEXT NOT NULL,
    count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def stable_id(kind: str, repo: str, key: str) -> str:
    if kind == "pr":
        return f"pr:{repo}#{key}"
    if kind == "issue":
        return f"issue:{repo}#{key}"
    if kind == "commit":
        return f"commit:{key}"
    if kind == "doc":
        return f"doc:{repo}:{key}"
    return f"{kind}:{repo}:{key}"


class SqliteCache:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(self.path))
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(SCHEMA)
        self._connection.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._connection
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "SqliteCache":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def put_raw(self, kind: str, repo: str, key: str, payload: Any) -> bool:
        object_id = stable_id(kind, repo, key)
        digest = content_hash(payload)
        row = self._connection.execute(
            "SELECT content_hash FROM raw_objects WHERE id = ?", (object_id,)
        ).fetchone()
        if row is not None and row["content_hash"] == digest:
            return False
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO raw_objects (id, kind, repo, fetched_at, content_hash, json) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET fetched_at = excluded.fetched_at, "
                "content_hash = excluded.content_hash, json = excluded.json",
                (object_id, kind, repo, utc_now(), digest, json.dumps(payload, ensure_ascii=False)),
            )
        return True

    def get_raw(self, kind: str, repo: str, key: str) -> Optional[Any]:
        object_id = stable_id(kind, repo, key)
        row = self._connection.execute(
            "SELECT json FROM raw_objects WHERE id = ?", (object_id,)
        ).fetchone()
        return json.loads(row["json"]) if row is not None else None

    def has_raw(self, kind: str, repo: str, key: str) -> bool:
        object_id = stable_id(kind, repo, key)
        return (
            self._connection.execute(
                "SELECT 1 FROM raw_objects WHERE id = ?", (object_id,)
            ).fetchone()
            is not None
        )

    def count(self, table: str, repo: Optional[str] = None) -> int:
        if repo is None:
            row = self._connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
        else:
            row = self._connection.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE repo = ?", (repo,)
            ).fetchone()
        return int(row["n"])

    def count_kind(self, kind: str, repo: Optional[str] = None) -> int:
        if repo is None:
            row = self._connection.execute(
                "SELECT COUNT(*) AS n FROM raw_objects WHERE kind = ?", (kind,)
            ).fetchone()
        else:
            row = self._connection.execute(
                "SELECT COUNT(*) AS n FROM raw_objects WHERE kind = ? AND repo = ?", (kind, repo)
            ).fetchone()
        return int(row["n"])

    def put_commit(self, repo: str, record: dict[str, Any]) -> bool:
        digest = content_hash(record)
        row = self._connection.execute(
            "SELECT sha FROM commits WHERE sha = ?", (record["sha"],)
        ).fetchone()
        if row is not None:
            return False
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO commits (sha, repo, authored_at, committed_at, author_name, subject, "
                "message, parent_shas, pull_requests) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["sha"],
                    repo,
                    record.get("authored_at"),
                    record.get("committed_at"),
                    record.get("author_name"),
                    record.get("subject"),
                    record.get("message"),
                    json.dumps(record.get("parent_shas") or []),
                    json.dumps(record.get("pull_requests") or []),
                ),
            )
        del digest
        return True

    def put_commit_file(self, sha: str, record: dict[str, Any]) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO commit_files (sha, path, old_path, status, diff, diff_truncated) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(sha, path) DO UPDATE SET old_path = excluded.old_path, "
                "status = excluded.status, diff = excluded.diff, "
                "diff_truncated = excluded.diff_truncated",
                (
                    sha,
                    record["path"],
                    record.get("old_path"),
                    record.get("status"),
                    record.get("diff"),
                    1 if record.get("diff_truncated") else 0,
                ),
            )

    def commit_files_for(self, path: str) -> list[sqlite3.Row]:
        return list(
            self._connection.execute(
                "SELECT sha, path, old_path, status, diff_truncated FROM commit_files "
                "WHERE path = ? ORDER BY sha",
                (path,),
            )
        )

    def start_run(self, run_id: str, repo: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO ingest_runs (id, repo, started_at, status) VALUES (?, ?, ?, ?)",
                (run_id, repo, utc_now(), "running"),
            )

    def finish_run(
        self,
        run_id: str,
        repo: str,
        status: str,
        graphql_cost: Optional[int],
        summary: Any,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE ingest_runs SET finished_at = ?, status = ?, graphql_cost = ?, summary = ? "
                "WHERE id = ?",
                (utc_now(), status, graphql_cost, json.dumps(summary, ensure_ascii=False), run_id),
            )

    def record_skip(self, run_id: str, repo: str, kind: str, reason: str, count: int) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO skips (run_id, repo, kind, reason, count, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, repo, kind, reason, count, utc_now()),
            )

    def skips(self, repo: Optional[str] = None) -> list[sqlite3.Row]:
        if repo is None:
            return list(self._connection.execute("SELECT * FROM skips ORDER BY id"))
        return list(
            self._connection.execute("SELECT * FROM skips WHERE repo = ? ORDER BY id", (repo,))
        )

    def runs(self, repo: Optional[str] = None) -> list[sqlite3.Row]:
            if repo is None:
                return list(
                    self._connection.execute("SELECT * FROM ingest_runs ORDER BY started_at")
                )
            return list(
                self._connection.execute(
                    "SELECT * FROM ingest_runs WHERE repo = ? ORDER BY started_at", (repo,)
                )
            )
