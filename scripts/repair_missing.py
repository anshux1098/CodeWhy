#!/usr/bin/env python3
"""Delete stale `missing` rows whose number is already a stored pull request.

An earlier ingest run recorded a pull request's number as a missing issue when a
pull request body named another pull request. The number is a pull request, not an
issue, so the row is wrong. This repairs the cache in place, deleting only those
rows and reporting the counts by reason before and after. No network call is made.

    python scripts/repair_missing.py --repo urllib3/urllib3
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.stores.sqlite_cache import SqliteCache  # noqa: E402

DEFAULT_DB = REPO_ROOT / "data" / "ingest.sqlite3"


def reason_counts(rows: Sequence[Any]) -> dict[str, int]:
    return dict(sorted(Counter(row["reason"] for row in rows).items()))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Repair stale missing pull-request numbers in an ingest cache."
    )
    parser.add_argument("--database", default=str(DEFAULT_DB))
    parser.add_argument("--repo", default=None, help="restrict to owner/name")
    args = parser.parse_args(argv)

    path = Path(args.database)
    if not path.exists():
        print(f"no cache at {path}", file=sys.stderr)
        return 2

    with SqliteCache(path) as cache:
        before = [dict(row) for row in cache.missing(args.repo)]
        removed = cache.purge_missing_pull_request_numbers(args.repo)
        after = [dict(row) for row in cache.missing(args.repo)]

    print(f"repo    : {args.repo or 'all repositories'}")
    print(f"before  : {len(before)} rows {reason_counts(before)}")
    print(f"deleted : {removed} rows")
    print(f"after   : {len(after)} rows {reason_counts(after)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
