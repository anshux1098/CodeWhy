"""Read only view of an ingest cache. Makes no network call and writes nothing."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.stores.sqlite_cache import SqliteCache

DEFAULT_DB = ROOT / "data" / "ingest.sqlite3"


def inspect(cache: SqliteCache, repo: Optional[str]) -> dict[str, Any]:
    connection = cache._connection
    args: tuple[Any, ...] = (repo,) if repo else ()
    clause = " WHERE repo = ?" if repo else ""
    join = " AND " if repo else " WHERE "

    def scalar(sql: str, parameters: Sequence[Any] = ()) -> int:
        row = connection.execute(sql, parameters).fetchone()
        return int(row[0]) if row else 0

    def rows(sql: str, parameters: Sequence[Any] = ()) -> list[dict[str, Any]]:
        return [dict(row) for row in connection.execute(sql, parameters)]

    def list_columns(table: str, wanted: Sequence[str]) -> list[str]:
        """Only the columns this cache file actually has, so an older file still reports."""
        return [name for name in wanted if cache.has_column(table, name)]

    def scoped(predicate: str = "1 = 1") -> int:
        """Count commits matching a predicate, restricted to the repo when one was given."""
        if not have_commits:
            return 0
        return scalar(f"SELECT COUNT(*) FROM commits{clause}{join}{predicate}", args)

    have_commits = cache.has_table("commits")
    have_commit_files = cache.has_table("commit_files")
    have_raw = cache.has_table("raw_objects")

    def safe(has_table: bool, sql: str, parameters: Sequence[Any] = ()) -> int:
        return scalar(sql, parameters) if has_table else 0

    commits = safe(have_commits, f"SELECT COUNT(*) FROM commits{clause}", args)
    commit_files = safe(
        have_commit_files,
        f"SELECT COUNT(*) FROM commit_files WHERE sha IN (SELECT sha FROM commits{clause})",
        args,
    )
    empty_diffs = safe(
        have_commit_files,
        f"SELECT COUNT(*) FROM commit_files WHERE (diff IS NULL OR diff = '')"
        f" AND sha IN (SELECT sha FROM commits{clause})",
        args,
    )
    truncated = (
        scalar(
            f"SELECT COUNT(*) FROM commit_files WHERE diff_truncated = 1"
            f" AND sha IN (SELECT sha FROM commits{clause})",
            args,
        )
        if have_commit_files and cache.has_column("commit_files", "diff_truncated")
        else 0
    )
    def has_list(column: str) -> str:
        if not cache.has_column("commits", column):
            return "0"
        return f"({column} IS NOT NULL AND {column} != '[]')"

    with_closing = scoped(has_list("closing"))
    with_references = scoped(" OR ".join(
        [has_list(column) for column in ("closing", "mentions", "pull_requests")]
        + [
            "(trailers IS NOT NULL AND trailers != '{}')"
            if cache.has_column("commits", "trailers")
            else "0"
        ]
    ))

    def kinds(kind: str) -> int:
        if not have_raw:
            return 0
        if repo:
            return scalar("SELECT COUNT(*) FROM raw_objects WHERE kind = ? AND repo = ?", (kind, repo))
        return scalar("SELECT COUNT(*) FROM raw_objects WHERE kind = ?", (kind,))

    missing = (
        rows("SELECT repo, kind, number, reason FROM missing" + clause + " ORDER BY kind, number", args)
        if cache.has_table("missing")
        else []
    )
    skips = (
        [
            {**row, "bound": row.get("bound")}
            for row in rows(
                "SELECT repo, kind, reason, count"
                + (", bound" if cache.has_column("skips", "bound") else "")
                + " FROM skips" + clause + " ORDER BY kind, reason",
                args,
            )
        ]
        if cache.has_table("skips")
        else []
    )
    runs = [] if not cache.has_table("ingest_runs") else [dict(row) for row in connection.execute(
        "SELECT id, repo, started_at, finished_at, status, graphql_cost FROM ingest_runs" + clause
        + " ORDER BY started_at DESC LIMIT 10",
        args,
    )]
    files = (
        [
            dict(row)
            for row in connection.execute(
                "SELECT path, COUNT(*) AS commits FROM commit_files WHERE sha IN "
                "(SELECT sha FROM commits" + clause + ") GROUP BY path ORDER BY commits DESC, path LIMIT 25",
                args,
            )
        ]
        if have_commit_files
        else []
    )

    return {
        "database": str(cache.path),
        "repo_filter": repo,
        "counts": {
            "commits": commits,
            "commit_files": commit_files,
            "commit_files_with_empty_diff": empty_diffs,
            "commit_files_truncated": truncated,
            "commits_with_references": with_references,
            "commits_with_closing_references": with_closing,
            "pull_requests": kinds("pr"),
            "issues": kinds("issue"),
            "documents": kinds("doc"),
        },
        "last_runs": runs,
        "skips": skips,
        "missing_references": missing,
        "top_paths_by_commit_count": files,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect an ingest cache read only. No network call, no writes."
    )
    parser.add_argument("--database", default=str(DEFAULT_DB))
    parser.add_argument("--repo", default=None, help="restrict to owner/name")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args(argv)

    path = Path(args.database)
    if not path.exists():
        print(f"no cache at {path}", file=sys.stderr)
        return 2

    with SqliteCache(path, read_only=True) as cache:
        report = inspect(cache, args.repo)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    counts = report["counts"]
    print(f"database   : {report['database']}")
    print(f"repo       : {report['repo_filter'] or 'all repositories'}")
    print(f"commits    : {counts['commits']}")
    print(f"commit files: {counts['commit_files']}")
    print(f"  empty diffs: {counts['commit_files_with_empty_diff']}")
    print(f"  truncated  : {counts['commit_files_truncated']}")
    print(f"commits with references       : {counts['commits_with_references']}")
    print(f"commits with closing keywords : {counts['commits_with_closing_references']}")
    print(f"pull requests: {counts['pull_requests']}")
    print(f"issues      : {counts['issues']}")
    print(f"documents   : {counts['documents']}")
    if report["skips"]:
        print("skips")
        for skip in report["skips"]:
            bound = f" bound={skip['bound']}" if skip["bound"] is not None else ""
            print(f"  - {skip['kind']}: {skip['reason']} count={skip['count']}{bound}")
    if report["missing_references"]:
        print(f"missing references ({len(report['missing_references'])})")
        for row in report["missing_references"][:20]:
            print(f"  - #{row['number']} ({row['kind']}): {row['reason']}")
    if report["last_runs"]:
        print("last runs")
        for run in report["last_runs"]:
            print(f"  - {run['started_at']} {run['status']} cost={run['graphql_cost']}")
    print("top paths by commit count")
    for row in report["top_paths_by_commit_count"][:10]:
        print(f"  - {row['path']}: {row['commits']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())