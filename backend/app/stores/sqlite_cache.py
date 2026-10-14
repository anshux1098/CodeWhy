from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from app.prompts.extract_decision import mark_injection_flag

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
    pull_requests TEXT,
    closing TEXT,
    mentions TEXT,
    trailers TEXT
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
    bound INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS missing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    repo TEXT NOT NULL,
    kind TEXT NOT NULL,
    number INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS missing_unique ON missing (repo, kind, number);

CREATE TABLE IF NOT EXISTS links (
    id TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    rel_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    is_direct INTEGER NOT NULL DEFAULT 1,
    derivation_method TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    metadata_json TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS links_repo_rel ON links (repo, rel_type);
CREATE INDEX IF NOT EXISTS links_source ON links (source_id);
CREATE INDEX IF NOT EXISTS links_target ON links (target_id);

CREATE TABLE IF NOT EXISTS config_keys (
    id TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    file_path TEXT NOT NULL,
    name TEXT NOT NULL,
    current_value TEXT,
    file_type TEXT NOT NULL,
    line_number INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS config_keys_repo ON config_keys (repo);
CREATE INDEX IF NOT EXISTS config_keys_file ON config_keys (repo, file_path);

CREATE TABLE IF NOT EXISTS config_value_changes (
    id TEXT PRIMARY KEY,
    config_id TEXT NOT NULL,
    repo TEXT NOT NULL,
    file_path TEXT NOT NULL,
    name TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT NOT NULL,
    authored_at TEXT,
    author_name TEXT,
    diff_snippet TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS config_changes_config_id ON config_value_changes (config_id);
CREATE INDEX IF NOT EXISTS config_changes_commit ON config_value_changes (commit_sha);

CREATE TABLE IF NOT EXISTS noise_labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL,
    record_type TEXT NOT NULL,
    repo TEXT NOT NULL,
    reason TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    detail TEXT,
    is_revert_target INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS noise_labels_record_reason ON noise_labels (record_id, reason);
CREATE INDEX IF NOT EXISTS noise_labels_repo ON noise_labels (repo);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    repo TEXT NOT NULL,
    summary TEXT NOT NULL,
    decision_type TEXT NOT NULL,
    rationale TEXT,
    state TEXT NOT NULL,
    alternatives_considered TEXT,
    constraints TEXT,
    affected_entities TEXT,
    source_references TEXT,
    decision_date TEXT,
    source_author TEXT,
    explicit_reversal_language INTEGER NOT NULL DEFAULT 0,
    unknown_fields TEXT,
    quote_verified INTEGER NOT NULL DEFAULT 0,
    extraction_version TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS decisions_repo ON decisions (repo);
CREATE INDEX IF NOT EXISTS decisions_source ON decisions (source_id);
CREATE INDEX IF NOT EXISTS decisions_hash ON decisions (source_id, extraction_version, content_hash);

CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_url TEXT NOT NULL,
    quote TEXT NOT NULL,
    author TEXT,
    timestamp TEXT,
    classification TEXT NOT NULL,
    claim TEXT NOT NULL,
    quote_verified INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS evidence_decision ON evidence (decision_id);
CREATE INDEX IF NOT EXISTS evidence_source ON evidence (source_id);
"""


EMAIL_WITH_NAME = re.compile(
    r"(?P<name>[A-Za-z][\w .'-]*?)\s*<\s*(?P<email>[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24})\s*>"
)
BARE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")


def redact_emails(text: Optional[str]) -> Optional[str]:
    """Remove contributor email addresses from stored prose, keeping the display name.

    Commit bodies carry `Co-authored-by: Name <address>` and `Signed-off-by` trailers, so
    storing a message verbatim would persist the addresses of people who only appear as
    co-authors. The name is evidence; the address is not something the cache should hold.
    """
    if not text:
        return text
    text = EMAIL_WITH_NAME.sub(lambda m: f"{m.group('name')} <redacted-email>", text)
    return BARE_EMAIL.sub("<redacted-email>", text)


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


def redact_trailers(trailers: dict[str, Any]) -> dict[str, list[str]]:
    return {token: [redact_emails(value) or "" for value in values] for token, values in trailers.items()}


class SqliteCache:
    def __init__(self, path: Path, *, read_only: bool = False) -> None:
        """Open the cache. A writable open creates or upgrades the schema.

        `read_only` opens the file through the sqlite read only URI and runs no DDL at
        all, so inspecting a cache cannot alter it. The file must already exist.
        """
        self.path = Path(path)
        self.read_only = read_only
        if read_only:
            uri = f"file:{self.path.resolve().as_posix()}?mode=ro"
            self._connection = sqlite3.connect(uri, uri=True)
            self._connection.row_factory = sqlite3.Row
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(self.path))
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(SCHEMA)
        self._migrate()
        self._connection.commit()

    def has_table(self, name: str) -> bool:
        """Whether a table exists. A read only open of an older cache may lack one."""
        row = self._connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
        return row is not None

    def has_column(self, table: str, column: str) -> bool:
        if not self.has_table(table):
            return False
        return any(
            entry["name"] == column
            for entry in self._connection.execute(f"PRAGMA table_info({table})")
        )

    ADDED_COLUMNS: dict[str, dict[str, str]] = {
        "commits": {
            "closing": "TEXT",
            "mentions": "TEXT",
            "trailers": "TEXT",
        },
        "skips": {"bound": "INTEGER"},
    }

    def _migrate(self) -> None:
        """Add columns introduced after a cache file was first created."""
        for table, columns in self.ADDED_COLUMNS.items():
            existing = {
                row["name"] for row in self._connection.execute(f"PRAGMA table_info({table})")
            }
            if not existing:
                continue
            for column, column_type in columns.items():
                if column not in existing:
                    self._connection.execute(
                        f"ALTER TABLE {table} ADD COLUMN {column} {column_type}"
                    )

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
        """Cache one raw object.

        Ingested repository text is scanned on the way in so a source that looks
        like a prompt injection is flagged at rest. Only the boolean is stored.
        """
        object_id = stable_id(kind, repo, key)
        if kind in ("pr", "issue", "doc", "commit") and isinstance(payload, dict):
            payload = mark_injection_flag(payload)
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

    def count_commit_files(self) -> int:
        """Count stored commit_files rows, which are per commit and path."""
        row = self._connection.execute("SELECT COUNT(*) AS n FROM commit_files").fetchone()
        return int(row["n"])

    def put_commit(self, repo: str, record: dict[str, Any]) -> bool:
        row = self._connection.execute(
            "SELECT sha FROM commits WHERE sha = ?", (record["sha"],)
        ).fetchone()
        if row is not None:
            return False
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO commits (sha, repo, authored_at, committed_at, author_name, subject, "
                "message, parent_shas, pull_requests, closing, mentions, trailers) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["sha"],
                    repo,
                    record.get("authored_at"),
                    record.get("committed_at"),
                    record.get("author_name"),
                    redact_emails(record.get("subject")),
                    redact_emails(record.get("message")),
                    json.dumps(record.get("parent_shas") or []),
                    json.dumps(record.get("pull_requests") or []),
                    json.dumps(record.get("closing") or []),
                    json.dumps(record.get("mentions") or []),
                    json.dumps(redact_trailers(record.get("trailers") or {})),
                ),
            )
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

    def record_skip(
        self,
        run_id: str,
        repo: str,
        kind: str,
        reason: str,
        count: int,
        bound: Optional[int] = None,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO skips (run_id, repo, kind, reason, count, bound, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, repo, kind, reason, count, bound, utc_now()),
            )

    def record_missing(self, run_id: str, repo: str, kind: str, number: int, reason: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO missing (run_id, repo, kind, number, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, repo, kind, number, reason, utc_now()),
            )

    def missing(self, repo: Optional[str] = None) -> list[sqlite3.Row]:
        if repo is None:
            return list(self._connection.execute("SELECT * FROM missing ORDER BY number"))
        return list(
            self._connection.execute(
                "SELECT * FROM missing WHERE repo = ? ORDER BY number", (repo,)
            )
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

    def put_link(self, link_row: dict[str, Any]) -> bool:
        """Store a link idempotently. Returns True if inserted or updated."""
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO links (id, repo, source_id, source_type, rel_type, target_id, "
                "target_type, is_direct, derivation_method, confidence, metadata_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "is_direct = excluded.is_direct, "
                "derivation_method = excluded.derivation_method, "
                "confidence = excluded.confidence, "
                "metadata_json = excluded.metadata_json",
                (
                    link_row["id"],
                    link_row["repo"],
                    link_row["source_id"],
                    link_row["source_type"],
                    link_row["rel_type"],
                    link_row["target_id"],
                    link_row["target_type"],
                    link_row.get("is_direct", 1),
                    link_row.get("derivation_method", "direct"),
                    link_row.get("confidence", 1.0),
                    json.dumps(link_row.get("metadata_json") or link_row.get("metadata") or {}),
                    link_row.get("created_at", utc_now()),
                ),
            )
        return True

    def put_links(self, link_rows: Sequence[dict[str, Any]]) -> int:
        count = 0
        with self.transaction() as connection:
            for row in link_rows:
                connection.execute(
                    "INSERT INTO links (id, repo, source_id, source_type, rel_type, target_id, "
                    "target_type, is_direct, derivation_method, confidence, metadata_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET "
                    "is_direct = excluded.is_direct, "
                    "derivation_method = excluded.derivation_method, "
                    "confidence = excluded.confidence, "
                    "metadata_json = excluded.metadata_json",
                    (
                        row["id"],
                        row["repo"],
                        row["source_id"],
                        row["source_type"],
                        row["rel_type"],
                        row["target_id"],
                        row["target_type"],
                        row.get("is_direct", 1),
                        row.get("derivation_method", "direct"),
                        row.get("confidence", 1.0),
                        json.dumps(row.get("metadata_json") or row.get("metadata") or {}),
                        row.get("created_at", utc_now()),
                    ),
                )
                count += 1
        return count

    def links_for(
        self,
        repo: Optional[str] = None,
        rel_type: Optional[str] = None,
    ) -> list[sqlite3.Row]:
        query = "SELECT * FROM links"
        params: list[Any] = []
        clauses: list[str] = []
        if repo is not None:
            clauses.append("repo = ?")
            params.append(repo)
        if rel_type is not None:
            clauses.append("rel_type = ?")
            params.append(rel_type)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id"
        return list(self._connection.execute(query, params))

    def links_from(self, source_id: str) -> list[sqlite3.Row]:
        return list(
            self._connection.execute(
                "SELECT * FROM links WHERE source_id = ? ORDER BY rel_type, target_id",
                (source_id,),
            )
        )

    def links_to(self, target_id: str) -> list[sqlite3.Row]:
        return list(
            self._connection.execute(
                "SELECT * FROM links WHERE target_id = ? ORDER BY rel_type, source_id",
                (target_id,),
            )
        )

    # ------------------------------------------------------------------
    # Config keys
    # ------------------------------------------------------------------

    def put_config_key(self, row: dict[str, Any]) -> bool:
        """Upsert a configuration key entity. Returns True."""
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO config_keys "
                "(id, repo, file_path, name, current_value, file_type, line_number, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "current_value = excluded.current_value, "
                "line_number = excluded.line_number",
                (
                    row["id"],
                    row["repo"],
                    row["file_path"],
                    row["name"],
                    row.get("current_value"),
                    row["file_type"],
                    row.get("line_number"),
                    row.get("created_at", utc_now()),
                ),
            )
        return True

    def put_config_keys(self, rows: Sequence[dict[str, Any]]) -> int:
        count = 0
        with self.transaction() as connection:
            for row in rows:
                connection.execute(
                    "INSERT INTO config_keys "
                    "(id, repo, file_path, name, current_value, file_type, line_number, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET "
                    "current_value = excluded.current_value, "
                    "line_number = excluded.line_number",
                    (
                        row["id"],
                        row["repo"],
                        row["file_path"],
                        row["name"],
                        row.get("current_value"),
                        row["file_type"],
                        row.get("line_number"),
                        row.get("created_at", utc_now()),
                    ),
                )
                count += 1
        return count

    def config_keys_for(self, repo: str, file_path: Optional[str] = None) -> list[sqlite3.Row]:
        if file_path is not None:
            return list(
                self._connection.execute(
                    "SELECT * FROM config_keys WHERE repo = ? AND file_path = ? ORDER BY name",
                    (repo, file_path),
                )
            )
        return list(
            self._connection.execute(
                "SELECT * FROM config_keys WHERE repo = ? ORDER BY file_path, name", (repo,)
            )
        )

    def put_config_value_change(self, row: dict[str, Any]) -> bool:
        """Upsert a config key value change event. Returns True."""
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO config_value_changes "
                "(id, config_id, repo, file_path, name, commit_sha, old_value, new_value, "
                "authored_at, author_name, diff_snippet, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "old_value = excluded.old_value, "
                "new_value = excluded.new_value, "
                "diff_snippet = excluded.diff_snippet",
                (
                    row["id"],
                    row["config_id"],
                    row["repo"],
                    row["file_path"],
                    row["name"],
                    row["commit_sha"],
                    row.get("old_value"),
                    row["new_value"],
                    row.get("authored_at"),
                    row.get("author_name"),
                    row.get("diff_snippet"),
                    row.get("created_at", utc_now()),
                ),
            )
        return True

    def value_history_for(self, config_id: str) -> list[sqlite3.Row]:
        """Return all value changes for a config key, oldest-first."""
        return list(
            self._connection.execute(
                "SELECT * FROM config_value_changes "
                "WHERE config_id = ? ORDER BY authored_at ASC NULLS LAST, id",
                (config_id,),
            )
        )

    # ------------------------------------------------------------------
    # Noise labels
    # ------------------------------------------------------------------

    def put_noise_labels(
        self,
        record_id: str,
        record_type: str,
        repo: str,
        labels: Sequence[dict[str, Any]],
        is_revert_target: bool = False,
    ) -> int:
        """Store noise labels for a record idempotently (upsert by record+reason).

        ``record_type`` is ``'pr'``, ``'commit'``, or ``'issue'``.
        Returns count of labels written.
        """
        count = 0
        with self.transaction() as connection:
            for label in labels:
                connection.execute(
                    "INSERT INTO noise_labels "
                    "(record_id, record_type, repo, reason, confidence, detail, "
                    "is_revert_target, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(record_id, reason) DO UPDATE SET "
                    "confidence = excluded.confidence, "
                    "detail = excluded.detail, "
                    "is_revert_target = excluded.is_revert_target",
                    (
                        record_id,
                        record_type,
                        repo,
                        label["reason"],
                        label.get("confidence", 1.0),
                        label.get("detail"),
                        1 if is_revert_target else 0,
                        utc_now(),
                    ),
                )
                count += 1
        return count

    def noise_labels_for(
        self,
        repo: Optional[str] = None,
        record_id: Optional[str] = None,
    ) -> list[sqlite3.Row]:
        """Query noise labels, optionally filtered by repo or record_id."""
        query = "SELECT * FROM noise_labels"
        params: list[Any] = []
        clauses: list[str] = []
        if repo is not None:
            clauses.append("repo = ?")
            params.append(repo)
        if record_id is not None:
            clauses.append("record_id = ?")
            params.append(record_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY record_id, reason"
        return list(self._connection.execute(query, params))

    def noisy_record_ids(self, repo: str, min_confidence: float = 0.8) -> set[str]:
        """Return the set of record IDs flagged as noise for a repo.

        Revert targets are never included even if they have noise labels.
        """
        rows = self._connection.execute(
            "SELECT DISTINCT record_id FROM noise_labels "
            "WHERE repo = ? AND confidence >= ? AND is_revert_target = 0",
            (repo, min_confidence),
        )
        return {row["record_id"] for row in rows}

    # ------------------------------------------------------------------
    # Decisions & Evidence
    # ------------------------------------------------------------------

    def put_decision(self, row: dict[str, Any]) -> bool:
        """Upsert an extracted decision record. Returns True."""
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO decisions "
                "(id, source_id, repo, summary, decision_type, rationale, state, "
                "alternatives_considered, constraints, affected_entities, "
                "source_references, decision_date, source_author, "
                "explicit_reversal_language, unknown_fields, quote_verified, "
                "extraction_version, content_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "summary = excluded.summary, "
                "decision_type = excluded.decision_type, "
                "rationale = excluded.rationale, "
                "state = excluded.state, "
                "alternatives_considered = excluded.alternatives_considered, "
                "constraints = excluded.constraints, "
                "affected_entities = excluded.affected_entities, "
                "source_references = excluded.source_references, "
                "explicit_reversal_language = excluded.explicit_reversal_language, "
                "unknown_fields = excluded.unknown_fields, "
                "quote_verified = excluded.quote_verified, "
                "content_hash = excluded.content_hash",
                (
                    row["id"],
                    row["source_id"],
                    row["repo"],
                    row["summary"],
                    row["decision_type"],
                    row.get("rationale"),
                    row["state"],
                    json.dumps(row.get("alternatives_considered") or []),
                    json.dumps(row.get("constraints") or []),
                    json.dumps(row.get("affected_entities") or []),
                    json.dumps(row.get("source_references") or []),
                    row.get("decision_date"),
                    row.get("source_author"),
                    1 if row.get("explicit_reversal_language") else 0,
                    json.dumps(row.get("unknown_fields") or []),
                    1 if row.get("quote_verified") else 0,
                    row["extraction_version"],
                    row["content_hash"],
                    row.get("created_at", utc_now()),
                ),
            )
        return True

    def put_decisions(self, rows: Sequence[dict[str, Any]]) -> int:
        """Batch upsert decision records."""
        count = 0
        for r in rows:
            if self.put_decision(r):
                count += 1
        return count

    def put_evidence(self, row: dict[str, Any]) -> bool:
        """Upsert a verified evidence quote. Returns True."""
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO evidence "
                "(id, decision_id, source_id, source_type, source_url, "
                "quote, author, timestamp, classification, claim, "
                "quote_verified, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "quote = excluded.quote, "
                "claim = excluded.claim, "
                "quote_verified = excluded.quote_verified",
                (
                    row["id"],
                    row["decision_id"],
                    row["source_id"],
                    row["source_type"],
                    row["source_url"],
                    row["quote"],
                    row.get("author"),
                    row.get("timestamp"),
                    row["classification"],
                    row["claim"],
                    1 if row.get("quote_verified", True) else 0,
                    row.get("created_at", utc_now()),
                ),
            )
        return True

    def put_evidence_batch(self, rows: Sequence[dict[str, Any]]) -> int:
        """Batch upsert evidence items."""
        count = 0
        for r in rows:
            if self.put_evidence(r):
                count += 1
        return count

    def decisions_for_repo(self, repo: str) -> list[sqlite3.Row]:
        """Return all decisions for a repo ordered by creation date."""
        return list(
            self._connection.execute(
                "SELECT * FROM decisions WHERE repo = ? ORDER BY decision_date ASC NULLS LAST, id",
                (repo,),
            )
        )

    def decision_by_id(self, decision_id: str) -> Optional[sqlite3.Row]:
        """Fetch a single decision by its ID."""
        return self._connection.execute(
            "SELECT * FROM decisions WHERE id = ?",
            (decision_id,),
        ).fetchone()

    def evidence_for_decision(self, decision_id: str) -> list[sqlite3.Row]:
        """Return all evidence items linked to a decision."""
        return list(
            self._connection.execute(
                "SELECT * FROM evidence WHERE decision_id = ? ORDER BY id",
                (decision_id,),
            )
        )

    def has_extracted_source(
        self, source_id: str, extraction_version: str, content_hash: str
    ) -> bool:
        """Checks if a source has already been extracted under this version and content hash."""
        row = self._connection.execute(
            "SELECT 1 FROM decisions "
            "WHERE source_id = ? AND extraction_version = ? AND content_hash = ? "
            "LIMIT 1",
            (source_id, extraction_version, content_hash),
        ).fetchone()
        return row is not None

