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

    def scoped(predicate: str = "1 = 1") -> int:
        """Count commits matching a predicate, restricted to the repo when one was given."""
        return scalar(f"SELECT COUNT(*) FROM commits{clause}{join}{predicate}", args)

    commits = scalar(f"SELECT COUNT(*) FROM commits{clause}", args)
    commit_files = scalar(
        f"SELECT COUNT(*) FROM commit_files WHERE sha IN (SELECT sha FROM commits{clause})", args
    )
    empty_diffs = scalar(
        f"SELECT COUNT(*) FROM commit_files WHERE (diff IS NULL OR diff = '')"
        f" AND sha IN (SELECT sha FROM commits{clause})",
        args,
    )
    truncated = scalar(
        f"SELECT COUNT(*) FROM commit_files WHERE diff_truncated = 1"
        f" AND sha IN (SELECT sha FROM commits{clause})",
        args,
    )
    has_list = lambda column: f"({column} IS NOT NULL AND {column} != '[]')"  # noqa: E731
    with_closing = scoped(" OR ".join([has_list("closing")]))
    with_references = scoped(
        " OR ".join(
            [
                has_list("closing"),
                has_list("mentions"),
                has_list("pull_requests"),
                "(trailers IS NOT NULL AND trailers != '{}')",
            ]
        )
    )

    def kinds(kind: str) -> int:
        if repo:
            return scalar("SELECT COUNT(*) FROM raw_objects WHERE kind = ? AND repo = ?", (kind, repo))
        return scalar("SELECT COUNT(*) FROM raw_objects WHERE kind = ?", (kind,))

    missing = [dict(row) for row in connection.execute(
        "SELECT repo, kind, number, reason FROM missing" + clause + " ORDER BY kind, number", args
    )]
    skips = [dict(row) for row in connection.execute(
        "SELECT repo, kind, reason, count, bound FROM skips" + clause + " ORDER BY kind, reason", args
    )]
    runs = [dict(row) for row in connection.execute(
        "SELECT id, repo, started_at, finished_at, status, graphql_cost FROM ingest_runs" + clause
        + " ORDER BY started_at DESC LIMIT 10",
        args,
    )]
    files = [
        dict(row)
        for row in connection.execute(
            "SELECT path, COUNT(*) AS commits FROM commit_files WHERE sha IN "
            "(SELECT sha FROM commits" + clause + ") GROUP BY path ORDER BY commits DESC, path LIMIT 25",
            args,
        )
    ]

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

    with SqliteCache(path) as cache:
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