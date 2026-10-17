from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from app.prompts.extract_decision import mark_injection_flag

logger = logging.getLogger(__name__)

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
    reason_unstated INTEGER NOT NULL DEFAULT 0,
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

-- Candidate quotes the model proposed that failed verification. They are dropped
-- from the graph, but the candidate, the rung it failed at and the decision it
-- belonged to are kept so a rejection can be audited after the reply is gone.
CREATE TABLE IF NOT EXISTS rejected_quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    repo TEXT NOT NULL,
    source_id TEXT NOT NULL,
    decision_id TEXT,
    decision_summary TEXT,
    candidate TEXT NOT NULL,
    failed_rung TEXT NOT NULL,
    failure_reason TEXT,
    claim TEXT,
    source_url TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS rejected_quotes_source ON rejected_quotes (source_id);
CREATE INDEX IF NOT EXISTS rejected_quotes_repo ON rejected_quotes (repo);

-- One row per source whose extraction did not finish. A source that produced no
-- decisions is not a failure, so this table records only what actually broke,
-- which is what --retry-failed replays.
CREATE TABLE IF NOT EXISTS extraction_failures (
    source_id TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    extraction_version TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 1,
    final_status TEXT NOT NULL,
    error TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS extraction_failures_repo ON extraction_failures (repo);

-- One row per extraction invocation, so the tokens a run spent stay visible
-- after the process exits and the next run can report a cumulative figure.
CREATE TABLE IF NOT EXISTS extraction_runs (
    run_id TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    tokens INTEGER NOT NULL DEFAULT 0,
    decisions INTEGER NOT NULL DEFAULT 0,
    evidence INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS extraction_runs_repo ON extraction_runs (repo);

-- One row per (source, run). Recorded whatever the outcome: a source that answered
-- correctly with zero decisions is processed, and recording only failures or only
-- decisions loses that middle case, leaving a finished source indistinguishable
-- from one nobody attempted.
CREATE TABLE IF NOT EXISTS extraction_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    repo TEXT NOT NULL,
    source_id TEXT NOT NULL,
    extraction_version TEXT NOT NULL,
    status TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    response_format_mode TEXT NOT NULL DEFAULT '',
    finish_reason TEXT NOT NULL DEFAULT '',
    decisions INTEGER NOT NULL DEFAULT 0,
    tokens INTEGER NOT NULL DEFAULT 0,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
-- A source may be re-extracted, so this is deliberately not unique on source_id:
-- two runs of the same source are the comparison the columns exist to support.
CREATE INDEX IF NOT EXISTS extraction_sources_repo ON extraction_sources (repo, extraction_version);
CREATE INDEX IF NOT EXISTS extraction_sources_source ON extraction_sources (repo, source_id);
"""


EMAIL_WITH_NAME = re.compile(
    r"(?P<name>[A-Za-z][\w .'-]*?)\s*<\s*(?P<email>[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24})\s*>"
)
BARE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")

#: Provider keys that appear inside an error message when a request is rejected.
#: The prefix is what identifies them; the shape is deliberately loose because the
#: exact length differs per provider.
API_KEY_SHAPED = re.compile(
    r"\b(?:sk|pk|rk|ghp|gho|ghu|ghs|github_pat|xoxb|AKIA)[-_][A-Za-z0-9_-]{12,}\b"
)


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


def redact_secrets(text: Optional[str]) -> Optional[str]:
    """Remove anything shaped like an API key.

    A rejected request is answered with an error that frequently quotes the
    credential back. That text is stored so the failure can be diagnosed, so it
    has to be scrubbed on the way in rather than on the way out.
    """
    if not text:
        return text
    return API_KEY_SHAPED.sub("<redacted-key>", text)


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
        # Added after the first real run: a decision that records no reason must say so
        # at rest, not only at the moment it is created.
        "decisions": {"reason_unstated": "INTEGER NOT NULL DEFAULT 0"},
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

    def fetch_raw_objects(self, repo: str, limit: int = 50) -> list[dict[str, Any]]:
        """Rows of raw_objects for a repo, shaped for the extraction step."""
        query = "SELECT id, kind, json FROM raw_objects WHERE repo = ? ORDER BY id LIMIT ?"
        rows = self._connection.execute(query, (repo, limit)).fetchall()
        return [{"id": r[0], "kind": r[1], "payload": r[2]} for r in rows]

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
            "SELECT sha, message FROM commits WHERE sha = ?", (record["sha"],)
        ).fetchone()
        if row is not None:
            # A re-run that now carries a commit body should not leave the
            # previously stored empty one behind (body collection came after the
            # first ingest); repairing it keeps --refresh useful.
            new_message = redact_emails(record.get("message"))
            if (not row[1] or not str(row[1]).strip()) and new_message and new_message.strip():
                with self.transaction() as connection:
                    connection.execute(
                        "UPDATE commits SET message = ? WHERE sha = ?",
                        (new_message, record["sha"]),
                    )
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

    def purge_missing_pull_request_numbers(self, repo: Optional[str] = None) -> int:
        """Delete `missing` rows whose number is already stored as a pull request.

        A pull request body can name another pull request, and an earlier ingest
        recorded such a number as a missing issue. The row is wrong — the number is
        a pull request, not an issue — so it is removed. Rows for other repos and
        numbers that are genuinely missing are left untouched. Returns the number
        of rows deleted.
        """
        repo_clause = " AND missing.repo = ?" if repo is not None else ""
        params: tuple[Any, ...] = (repo,) if repo is not None else ()
        with self.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM missing WHERE EXISTS ("
                "SELECT 1 FROM raw_objects "
                "WHERE raw_objects.kind = 'pr' "
                "AND raw_objects.repo = missing.repo "
                "AND raw_objects.id = 'pr:' || missing.repo || '#' || missing.number)"
                + repo_clause,
                params,
            )
            return cursor.rowcount

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

    def iter_commits(self, repo: Optional[str] = None) -> list[dict[str, Any]]:
        """Every stored commit, newest first. Used by the deterministic link pass."""
        where = " WHERE repo = ?" if repo else ""
        params: tuple[Any, ...] = (repo,) if repo else ()
        return [dict(row) for row in self._connection.execute(
            f"SELECT sha, repo, subject, message, pull_requests, closing, mentions FROM commits {where}"
            " ORDER BY committed_at DESC",
            params,
        )]

    def iter_documents(self, repo: Optional[str] = None) -> list[dict[str, Any]]:
        """Every stored document, keyed by path."""
        where = " AND repo = ?" if repo else ""
        params: tuple[Any, ...] = (repo,) if repo else ()
        return [dict(row) for row in self._connection.execute(
            "SELECT json FROM raw_objects WHERE kind = 'doc'" + where, params,
        )]

    def iter_commit_files(self, repo: Optional[str] = None) -> list[dict[str, Any]]:
        """Every stored commit/path pair, used for containment links."""
        if repo:
            rows = self._connection.execute(
                "SELECT DISTINCT cf.path AS path FROM commit_files cf"
                " JOIN commits c ON c.sha = cf.sha WHERE c.repo = ?",
                (repo,),
            )
        else:
            rows = self._connection.execute("SELECT DISTINCT path FROM commit_files")
        return [dict(row) for row in rows]

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

    def clear_noise_labels(self, repo: str, record_type: Optional[str] = None) -> int:
        """Delete a repo's noise labels, optionally only one record type.

        A recompute replaces the stored labels, so a rule that no longer matches
        must be able to remove a stale label rather than leave it behind forever.
        Returns the number of rows deleted.
        """
        query = "DELETE FROM noise_labels WHERE repo = ?"
        params: list[Any] = [repo]
        if record_type is not None:
            query += " AND record_type = ?"
            params.append(record_type)
        with self.transaction() as connection:
            return connection.execute(query, tuple(params)).rowcount

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

    @staticmethod
    def _decision_would_degrade(existing: sqlite3.Row, incoming: dict[str, Any]) -> bool:
        """Whether writing `incoming` over `existing` would lose verified content.

        A stored decision that is quote-verified is authoritative. It may only be
        replaced by a record that is at least as good: still quote-verified and
        carrying a non-empty summary and rationale. A placeholder, a result whose
        quotes all failed verification, or a blank summary is therefore refused.
        """
        if not existing["quote_verified"]:
            return False
        if not incoming.get("quote_verified"):
            return True
        summary = (incoming.get("summary") or "").strip()
        rationale = (incoming.get("rationale") or "").strip()
        return not summary or not rationale

    def put_decision(self, row: dict[str, Any]) -> bool:
        """Upsert an extracted decision record.

        A re-run must never degrade a record that was good: see
        `_decision_would_degrade`. Returns True when the row was written and False
        when a weaker record was refused in favour of the stored one.
        """
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT summary, rationale, quote_verified FROM decisions WHERE id = ?",
                (row["id"],),
            ).fetchone()
            if existing is not None and self._decision_would_degrade(existing, row):
                logger.warning(
                    "Refused to overwrite verified decision %s with a weaker record",
                    row["id"],
                )
                return False
            connection.execute(
                "INSERT INTO decisions "
                "(id, source_id, repo, summary, decision_type, rationale, state, "
                "alternatives_considered, constraints, affected_entities, "
                "source_references, decision_date, source_author, "
                "explicit_reversal_language, unknown_fields, quote_verified, "
                "reason_unstated, extraction_version, content_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
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
                "reason_unstated = excluded.reason_unstated, "
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
                    1 if row.get("reason_unstated") else 0,
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

    def update_affected_entities(self, decision_id: str, entities: Sequence[str]) -> None:
        """Replace a decision's affected-entity list, leaving every other column alone.

        Used when the entity filter changes: re-deriving the list from a payload the
        cache already holds must not touch the summary, the quote or its verification.
        """
        with self.transaction() as connection:
            connection.execute(
                "UPDATE decisions SET affected_entities = ? WHERE id = ?",
                (json.dumps(list(entities)), decision_id),
            )

    def put_evidence(self, row: dict[str, Any]) -> bool:
        """Upsert a verified evidence quote.

        Evidence is only ever added or kept. Nothing here deletes a row, and a
        verified quote is never rewritten as unverified: a re-run that could not
        re-verify an old quote must not erase the fact that it once verified.
        Returns True when written and False when a verified row was protected.
        """
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT quote_verified FROM evidence WHERE id = ?", (row["id"],)
            ).fetchone()
            if (
                existing is not None
                and existing["quote_verified"]
                and not row.get("quote_verified", True)
            ):
                logger.warning(
                    "Kept verified evidence %s; refused an unverified rewrite", row["id"]
                )
                return False
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

    # -- rejected quotes -------------------------------------------------------

    def put_rejected_quotes(self, rows: Sequence[dict[str, Any]]) -> int:
        """Record candidate quotes that failed verification for later auditing.

        Appended, never upserted: two runs of the same source may propose different
        candidates, and the history is what makes a rejection diagnosable after the
        model reply is gone.
        """
        count = 0
        with self.transaction() as connection:
            for row in rows:
                connection.execute(
                    "INSERT INTO rejected_quotes "
                    "(run_id, repo, source_id, decision_id, decision_summary, candidate, "
                    "failed_rung, failure_reason, claim, source_url, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        row["run_id"],
                        row["repo"],
                        row["source_id"],
                        row.get("decision_id"),
                        row.get("decision_summary"),
                        row["candidate"],
                        row["failed_rung"],
                        row.get("failure_reason"),
                        row.get("claim"),
                        row.get("source_url"),
                        row.get("created_at") or utc_now(),
                    ),
                )
                count += 1
        return count

    def rejected_quotes(
        self, repo: Optional[str] = None, source_id: Optional[str] = None
    ) -> list[sqlite3.Row]:
        """Rejected quote candidates, oldest first, optionally filtered."""
        query = "SELECT * FROM rejected_quotes"
        clauses: list[str] = []
        params: list[Any] = []
        if repo is not None:
            clauses.append("repo = ?")
            params.append(repo)
        if source_id is not None:
            clauses.append("source_id = ?")
            params.append(source_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id ASC"
        return list(self._connection.execute(query, tuple(params)))

    # -- extraction bookkeeping ------------------------------------------------

    def record_extraction_failure(
        self,
        source_id: str,
        repo: str,
        extraction_version: str,
        final_status: str,
        error: str,
    ) -> None:
        """Remember that one source could not be extracted.

        `attempts` accumulates across runs so a source that keeps failing shows
        how much trouble it has already caused. The message is scrubbed first: a
        rejected request is the most likely error text to echo the key back.
        """
        now = utc_now()
        safe_error = redact_secrets(redact_emails(error)) or ""
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO extraction_failures "
                "(source_id, repo, extraction_version, attempts, final_status, error, "
                "created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?, ?, ?) "
                "ON CONFLICT(source_id) DO UPDATE SET attempts = attempts + 1, "
                "final_status = excluded.final_status, error = excluded.error, "
                "updated_at = excluded.updated_at",
                (source_id, repo, extraction_version, final_status, safe_error[:2000], now, now),
            )

    def clear_extraction_failure(self, source_id: str) -> None:
        """Drop a recorded failure once the source has been extracted."""
        with self.transaction() as connection:
            connection.execute(
                "DELETE FROM extraction_failures WHERE source_id = ?", (source_id,)
            )

    def extraction_failures(self, repo: Optional[str] = None) -> list[sqlite3.Row]:
        """Sources whose extraction failed, oldest first."""
        if repo is None:
            return list(
                self._connection.execute(
                    "SELECT * FROM extraction_failures ORDER BY created_at ASC, source_id"
                )
            )
        return list(
            self._connection.execute(
                "SELECT * FROM extraction_failures WHERE repo = ? ORDER BY created_at ASC, source_id",
                (repo,),
            )
        )

    def failed_source_ids(self, repo: str) -> set[str]:
        return {row["source_id"] for row in self.extraction_failures(repo)}

    #: Outcomes that mean the source was dealt with and needs no further work.
    COMPLETED_STATUSES: tuple[str, ...] = ("ok", "no_decision")

    def record_extraction_source(
        self,
        repo: str,
        source_id: str,
        extraction_version: str,
        status: str,
        run_id: str,
        model: str = "",
        response_format_mode: str = "",
        finish_reason: str = "",
        decisions: int = 0,
        tokens: int = 0,
        detail: str = "",
    ) -> None:
        """Record what one attempt at one source produced, whatever the outcome.

        Within a run a source is recorded once: a retry that succeeds replaces the
        earlier failure for that run, so the row describes where the source ended
        up rather than every attempt made along the way. Across runs the rows
        accumulate, which is what makes two models comparable on the same source.
        """
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT id FROM extraction_sources WHERE run_id = ? AND source_id = ?",
                (run_id, source_id),
            ).fetchone()
            values = (
                run_id, repo, source_id, extraction_version, status, model,
                response_format_mode, finish_reason, decisions, tokens,
                redact_secrets(redact_emails(detail)) or "", utc_now(),
            )
            if existing is None:
                connection.execute(
                    "INSERT INTO extraction_sources (run_id, repo, source_id, "
                    "extraction_version, status, model, response_format_mode, "
                    "finish_reason, decisions, tokens, detail, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    values,
                )
            else:
                connection.execute(
                    "UPDATE extraction_sources SET status = ?, model = ?, "
                    "response_format_mode = ?, finish_reason = ?, decisions = ?, "
                    "tokens = ?, detail = ?, created_at = ? WHERE id = ?",
                    (
                        status, model, response_format_mode, finish_reason, decisions,
                        tokens, values[10], values[11], existing["id"],
                    ),
                )

    def extraction_sources(self, repo: str) -> list[sqlite3.Row]:
        """Every recorded attempt for a repo, oldest first."""
        return list(
            self._connection.execute(
                "SELECT * FROM extraction_sources WHERE repo = ? ORDER BY id",
                (repo,),
            )
        )

    def processed_source_ids(self, repo: str, extraction_version: str) -> set[str]:
        """Sources that completed, with or without producing a decision.

        Keyed on the recorded status rather than on the presence of a decision row,
        so a source whose answer was "nothing to extract" is not reprocessed for
        ever, and is not lost either.
        """
        placeholders = ",".join("?" for _ in self.COMPLETED_STATUSES)
        return {
            row["source_id"]
            for row in self._connection.execute(
                f"SELECT DISTINCT source_id FROM extraction_sources "
                f"WHERE repo = ? AND extraction_version = ? AND status IN ({placeholders})",
                (repo, extraction_version, *self.COMPLETED_STATUSES),
            )
        }

    def extracted_source_ids(self, repo: str, extraction_version: str) -> set[str]:
        """Sources that already produced a decision for this extraction version.

        A rerun skips these, which is what makes the run resumable: only the work
        that never finished is repeated.
        """
        return {
            row["source_id"]
            for row in self._connection.execute(
                "SELECT DISTINCT source_id FROM decisions WHERE repo = ? AND extraction_version = ?",
                (repo, extraction_version),
            )
        }

    def record_extraction_run(
        self,
        repo: str,
        run_id: str,
        tokens: int,
        decisions: int,
        evidence: int,
        failures: int,
    ) -> None:
        """Store what one extraction run spent and produced."""
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO extraction_runs "
                "(run_id, repo, tokens, decisions, evidence, failures, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET tokens = excluded.tokens, "
                "decisions = excluded.decisions, evidence = excluded.evidence, "
                "failures = excluded.failures",
                (run_id, repo, tokens, decisions, evidence, failures, utc_now()),
            )

    def total_extraction_tokens(self, repo: Optional[str] = None) -> int:
        """Tokens spent by every recorded run for a repo."""
        if repo is None:
            row = self._connection.execute(
                "SELECT COALESCE(SUM(tokens), 0) FROM extraction_runs"
            ).fetchone()
        else:
            row = self._connection.execute(
                "SELECT COALESCE(SUM(tokens), 0) FROM extraction_runs WHERE repo = ?", (repo,)
            ).fetchone()
        return int(row[0]) if row else 0

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

