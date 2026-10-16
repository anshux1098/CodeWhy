from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings, SettingsError
from app.services.ingest.github_client import GitHubGraphQLClient
from app.services.ingest.pipeline import build_plan, run_ingest
from app.services.ingest.targets import load_targets, require_matching_repo
from app.stores.sqlite_cache import SqliteCache

DEFAULT_DB = ROOT / "data" / "ingest.sqlite3"
SUMMARY_PATH = ROOT / "data" / "ingest_summary.json"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest a repository. The repository and its demo targets are inputs, never code."
    )
    parser.add_argument("--repo", required=True, help="owner/name on github.com")
    parser.add_argument("--targets", required=True, help="path to the targets JSON file")
    parser.add_argument("--max-prs", type=int, default=None, help="recency pull request bound")
    parser.add_argument("--max-issues", type=int, default=None, help="recency issue bound")
    parser.add_argument("--refresh", action="store_true", help="refetch objects already cached")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and make no network call")
    parser.add_argument("--database", default=str(DEFAULT_DB))
    parser.add_argument("--clone-root", default=str(ROOT / "data" / "clones"))
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(message)s")

    try:
        settings = Settings()
        settings.require_github()
        targets = load_targets(Path(args.targets))
        require_matching_repo(targets, args.repo)
    except (SettingsError, ValueError) as exc:
        print(f"cannot start ingestion: {exc}", file=sys.stderr)
        return 2

    if args.max_prs is not None:
        settings.max_ingestion_prs = args.max_prs
    if args.max_issues is not None:
        settings.max_ingestion_issues = args.max_issues

    clone_root = Path(args.clone_root)
    plan = build_plan(args.repo, targets, settings, clone_root, target_pull_requests=0, target_issues=0)
    if args.dry_run:
        print("Dry run. No network call, no clone, no database writes.")
        print()
        print(plan.render())
        return 0

    with GitHubGraphQLClient(settings) as client, SqliteCache(Path(args.database)) as cache:
        summary = run_ingest(
            args.repo,
            targets,
            settings,
            cache=cache,
            clone_root=clone_root,
            client=client,
            max_prs=settings.max_ingestion_prs,
            max_issues=settings.max_ingestion_issues,
            refresh=args.refresh,
        )

    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    counts = summary.as_dict()["counts"]
    print(f"repository        : {summary.repo}")
    print(f"status            : {summary.status}")
    print(f"commits           : {counts['commits']}")
    print(f"commit files      : {counts['commit_files']}")
    print(f"pull requests     : {counts['pull_requests']}")
    print(f"issues            : {counts['issues']}")
    print(f"documents         : {counts['documents']}")
    print(f"GraphQL cost      : {summary.graphql_cost}")
    if summary.skips:
        print("skipped")
        for skip in summary.skips:
            print(f"  - {skip['kind']}: {skip['reason']} ({skip['count']})")
    else:
        print("skipped           : nothing")
    for note in summary.notes:
        print(f"note              : {note}")
    print(f"summary written   : {SUMMARY_PATH}")
    print(f"database          : {args.database}")
    return 0 if summary.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())