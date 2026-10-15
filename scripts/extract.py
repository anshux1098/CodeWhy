#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

# Add backend directory to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import settings
from app.providers.llm_provider import TokenBudget, TokenBudgetExhaustedError, get_llm_provider
from app.services.extraction import (
    EXTRACTION_VERSION,
    ExtractionSchemaRejected,
    extract_decisions_from_source,
    summarise_injection_flags,
)
from app.stores.sqlite_cache import SqliteCache

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("codewhy.extract")

#: The pull request that added HTTP/2 TLS settings and the one that reverted it.
#: They are the clearest statement of intent in this history, so they are read first.
PINNED_PULL_REQUESTS: tuple[int, ...] = (3456, 3466)

#: Files whose changes explain the retry, connection and TLS behaviour.
TARGET_FILES: tuple[str, ...] = (
    "src/urllib3/connectionpool.py",
    "src/urllib3/connection.py",
    "src/urllib3/util/ssl_.py",
)


def _pull_request_number(source_id: str) -> Optional[int]:
    """The number in `pr:owner/name#123`, or None for any other kind of source."""
    if not source_id.startswith("pr:") or "#" not in source_id:
        return None
    tail = source_id.rsplit("#", 1)[1]
    return int(tail) if tail.isdigit() else None


def _touches_target_files(payload: dict[str, Any]) -> bool:
    """Whether an ingested payload lists one of the target files.

    Matched on the suffix because the stored paths carry different roots: `git`
    recorded `src/urllib3/...` while GitHub reported `urllib3/...` for older files.
    """
    files = payload.get("files") or []
    if not isinstance(files, list):
        return False
    wanted = {name.rsplit("/", 1)[-1] for name in TARGET_FILES}
    return any(
        isinstance(name, str) and name.rsplit("/", 1)[-1] in wanted for name in files
    )


def _sort_key(row: dict[str, Any]) -> tuple[int, int, str]:
    """Rank a candidate: pinned pull requests, then target files, then everything else.

    Documentation sorts last because a changelog restates a decision rather than
    making one, so it should never crowd out the record of the decision itself.
    """
    source_id = row["id"]
    number = _pull_request_number(source_id)

    if number is not None and number in PINNED_PULL_REQUESTS:
        rank = PINNED_PULL_REQUESTS.index(number)
        return (rank, 0, source_id)

    if row.get("kind") == "doc":
        return (len(PINNED_PULL_REQUESTS) + 2, 0, source_id)

    try:
        payload = json.loads(row["payload"])
    except (TypeError, ValueError):
        payload = {}
    if isinstance(payload, dict) and _touches_target_files(payload):
        return (len(PINNED_PULL_REQUESTS), 0, source_id)

    return (len(PINNED_PULL_REQUESTS) + 1, 0, source_id)


def select_sources(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """The first `limit` candidates in priority order."""
    return sorted(rows, key=_sort_key)[:limit]


def source_url_for(source_id: str, repo: str, payload: dict[str, Any]) -> str:
    """The canonical web address of a source.

    A stored `url` is trusted when present. Otherwise the address is derived from
    the identifier, because a citation that points at the repository homepage
    instead of the pull request is not a citation anyone can check.
    """
    stored = payload.get("url")
    if isinstance(stored, str) and stored:
        return stored

    number = _pull_request_number(source_id)
    if number is not None:
        return f"https://github.com/{repo}/pull/{number}"
    if source_id.startswith("issue:") and "#" in source_id:
        issue = source_id.rsplit("#", 1)[1]
        if issue.isdigit():
            return f"https://github.com/{repo}/issues/{issue}"
    if source_id.startswith("commit:"):
        return f"https://github.com/{repo}/commit/{source_id.split(':', 1)[1]}"
    if source_id.startswith("doc:"):
        path = source_id.split(":", 2)[2] if source_id.count(":") >= 2 else ""
        return f"https://github.com/{repo}/blob/main/{path}"
    return f"https://github.com/{repo}"


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract engineering decisions and verified citations from SQLite cache."
    )
    parser.add_argument(
        "--repo",
        type=str,
        default="urllib3/urllib3",
        help="Repository identifier (owner/name)",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=REPO_ROOT / "data" / "ingest.sqlite3",
        help="Path to the SQLite cache",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum candidate records to extract",
    )
    parser.add_argument(
        "--token-budget",
        dest="token_budget",
        type=int,
        default=None,
        help="Stop extraction once this many tokens have been used.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan extraction without invoking the LLM or updating the cache",
    )
    parser.add_argument(
        "--retry-failed",
        dest="retry_failed",
        action="store_true",
        help="Only retry the sources a previous run recorded as failed",
    )
    parser.add_argument(
        "--run-id",
        dest="run_id",
        type=str,
        default=uuid.uuid4().hex,
        help="Identifier recorded against this run's token usage",
    )
    parser.add_argument(
        "--sample-review-file",
        type=Path,
        default=REPO_ROOT / "review" / "decisions_sample.md",
        help="Path to generate review/decisions_sample.md markdown report",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    cache_path = args.cache
    if not cache_path.exists():
        logger.warning("Cache file %s does not exist; running in dry-run/preview mode.", cache_path)
        return 0

    # The cache is closed on every path out, including an exception, so the file is
    # never left locked for the next run.
    with SqliteCache(cache_path) as cache:
        return run_extraction(args, cache)


def run_extraction(args: argparse.Namespace, cache: SqliteCache) -> int:
    noisy_ids = cache.noisy_record_ids(args.repo)
    logger.info("Found %d noisy records to exclude from extraction", len(noisy_ids))

    budget = TokenBudget(
        args.token_budget if args.token_budget is not None else settings.max_llm_tokens_per_run
    )
    provider = get_llm_provider(budget=budget)

    # Every candidate is ranked first and only then cut to the limit, so --limit
    # selects the highest priority sources instead of whichever ids sort first.
    candidates = cache.fetch_raw_objects(args.repo, limit=10_000)
    failed_ids = cache.failed_source_ids(args.repo)
    already_done = cache.extracted_source_ids(args.repo, EXTRACTION_VERSION)

    rows = select_sources(candidates, args.limit)

    if args.retry_failed:
        rows = [row for row in rows if row["id"] in failed_ids]
        logger.info("--retry-failed: %d sources to retry", len(rows))

    pending = [
        row for row in rows
        if row["id"] not in already_done and row["id"] not in noisy_ids
    ]
    skipped_done = len([row for row in rows if row["id"] in already_done])
    if skipped_done:
        logger.info(
            "Skipping %d sources that already have a stored extraction result", skipped_done
        )

    # Counts only. The flagged text itself never reaches a log line.
    injection_counts = summarise_injection_flags(
        [{"source_id": row.get("id"), "injection_detected": row.get("injection_detected")}
         for row in pending]
    )
    logger.info(
        "prompt-injection scan: %d of %d sources flagged",
        injection_counts["sources_flagged"], injection_counts["sources_total"],
    )
    logger.info(
        "Selected %d of %d candidates in priority order for %s",
        len(pending), len(candidates), args.repo,
    )

    extracted_decisions_count = 0
    extracted_evidence_count = 0
    #: A source answered correctly with an empty decisions list. The only legitimate
    #: reading of "nothing to extract".
    no_decision_count = 0
    #: Answered, but not in the agreed shape. Recorded, never silently dropped.
    schema_rejected_count = 0
    #: A decision was extracted but no supporting quote survived verification.
    unverified_quote_count = 0
    failed_count = 0
    stopped_for_budget = False
    sample_records: list[dict[str, Any]] = []

    for position, row in enumerate(pending, start=1):
        source_id = row["id"]
        raw_payload = json.loads(row["payload"])
        source_type = row["kind"]
        source_url = source_url_for(source_id, args.repo, raw_payload)
        title = raw_payload.get("title", "")
        body = raw_payload.get("body", "")
        author = raw_payload.get("author", {}).get("login") if isinstance(raw_payload.get("author"), dict) else None
        created_at = raw_payload.get("createdAt") or raw_payload.get("created_at")

        if args.dry_run:
            logger.info("[DRY-RUN] %d/%d %s (%s) %s", position, len(pending), source_id, title[:50], source_url)
            continue

        logger.info("%d/%d extracting %s", position, len(pending), source_id)

        try:
            records = extract_decisions_from_source(
                provider=provider,
                source_id=source_id,
                source_type=source_type,
                source_url=source_url,
                repo=args.repo,
                title=title,
                body=body,
                author=author,
                created_at=created_at,
                extraction_version=EXTRACTION_VERSION,
            )
        except TokenBudgetExhaustedError:
            # The budget is a deliberate stop, not a failure of this source.
            logger.warning(
                "Token budget exhausted (used=%d/%d). Halting extraction as PARTIAL.",
                budget.total_tokens,
                budget.max_tokens,
            )
            stopped_for_budget = True
            break
        except ExtractionSchemaRejected as rejected:
            # A reply that is valid JSON but not the agreed shape. Recorded rather
            # than dropped: silently returning nothing here is what made a good
            # extraction disappear from the real run.
            schema_rejected_count += 1
            logger.warning(
                "Source %s schema_rejected: %s; keys received: %s",
                source_id, rejected.reason, ", ".join(rejected.received_keys) or "(none)",
            )
            cache.record_extraction_failure(
                source_id=source_id,
                repo=args.repo,
                extraction_version=EXTRACTION_VERSION,
                final_status="schema_rejected",
                error=str(rejected),
            )
            continue
        except Exception as exc:  # noqa: BLE001 - one bad source must not end the run
            # Recorded so a rerun can retry exactly this source. The exception text
            # may quote the credential, so it is scrubbed before it is stored.
            failed_count += 1
            logger.warning("Source %s failed: %s", source_id, type(exc).__name__)
            cache.record_extraction_failure(
                source_id=source_id,
                repo=args.repo,
                extraction_version=EXTRACTION_VERSION,
                final_status=str(getattr(exc, "status_code", type(exc).__name__)),
                error=str(exc),
            )
            continue

        # The source completed, so it is no longer outstanding work.
        cache.clear_extraction_failure(source_id)

        if not records:
            no_decision_count += 1

        for dec in records:
            if not dec.quote_verified:
                unverified_quote_count += 1

        for dec in records:
            dec_row = {
                "id": dec.id,
                "source_id": dec.source_id,
                "repo": dec.repo,
                "summary": dec.summary,
                "decision_type": dec.decision_type,
                "rationale": dec.rationale,
                "state": dec.state.value if hasattr(dec.state, "value") else str(dec.state),
                "alternatives_considered": dec.alternatives_considered,
                "constraints": dec.constraints,
                "affected_entities": dec.affected_entities,
                "source_references": dec.source_references,
                "decision_date": dec.decision_date,
                "source_author": dec.source_author,
                "explicit_reversal_language": dec.explicit_reversal_language,
                "unknown_fields": dec.unknown_fields,
                "quote_verified": dec.quote_verified,
                "extraction_version": dec.extraction_version,
                "content_hash": dec.content_hash,
                "created_at": dec.created_at,
            }
            cache.put_decision(dec_row)
            extracted_decisions_count += 1

            for ev in dec.evidence:
                ev_row = {
                    "id": ev.id,
                    "decision_id": ev.decision_id,
                    "source_id": ev.source_id,
                    "source_type": ev.source_type,
                    "source_url": ev.source_url,
                    "quote": ev.quote,
                    "author": ev.author,
                    "timestamp": ev.timestamp,
                    "classification": ev.classification,
                    "claim": ev.claim,
                    "quote_verified": ev.quote_verified,
                }
                cache.put_evidence(ev_row)
                extracted_evidence_count += 1

                if len(sample_records) < 20:
                    sample_records.append({
                        "summary": dec.summary,
                        "quote": ev.quote,
                        "source_url": ev.source_url,
                        "verified": "yes" if ev.quote_verified else "no",
                    })

    # ------------------------------------------------------------------
    # Linking pass. Without this the links table stayed empty, so the graph
    # build had nothing to replay and every REVERTS/PART_OF/REFERENCES edge was
    # silently lost.
    # ------------------------------------------------------------------
    links_written = build_links(cache, args.repo, rows)
    logger.info("Linking finished: %d links written.", links_written)

    if args.dry_run:
        return 0

    # Tokens spent by earlier runs are part of the true total, so they are read
    # back rather than implied by this run alone.
    tokens_this_run = budget.total_tokens
    tokens_before = cache.total_extraction_tokens()
    cache.record_extraction_run(
        repo=args.repo,
        run_id=args.run_id,
        tokens=tokens_this_run,
        decisions=extracted_decisions_count,
        evidence=extracted_evidence_count,
        failures=failed_count,
    )
    logger.info(
        "Extraction finished: %d decisions, %d verified evidence quotes written.",
        extracted_decisions_count,
        extracted_evidence_count,
    )
    logger.info("Tokens used this run: %d", tokens_this_run)
    logger.info("Tokens used in total, including earlier runs: %d", tokens_before + tokens_this_run)
    logger.info(
        "Failures this run: %d of %d attempted sources", failed_count, len(pending)
    )
    # One line per outcome so a run cannot look productive by accident. Each source
    # lands in exactly one of these buckets.
    logger.info(
        "Run summary: decisions=%d no_decision=%d schema_rejected=%d "
        "unverified_quote=%d failed=%d (of %d attempted)",
        extracted_decisions_count,
        no_decision_count,
        schema_rejected_count,
        unverified_quote_count,
        failed_count,
        len(pending),
    )
    if schema_rejected_count or failed_count:
        for row in cache.extraction_failures(args.repo):
            logger.info(
                "  rejected or failed source %s: status=%s attempts=%s",
                row["source_id"], row["final_status"], row["attempts"],
            )

    if sample_records and args.sample_review_file:
        generate_sample_review_file(args.sample_review_file, sample_records)

    # Nothing usable came back, so the exit code has to say so. A partial run still
    # exits 0 because its work is stored and a rerun continues from it.
    attempted = len(pending)
    unusable = failed_count + schema_rejected_count
    if attempted and unusable == attempted:
        logger.error(
            "No source produced a usable result: %d rejected, %d failed.",
            schema_rejected_count, failed_count,
        )
        return 1
    return 0


def build_links(cache: SqliteCache, repo: str, source_rows: list[Any]) -> int:
    """Run every deterministic link extractor over the cached history.

    All of these are pure functions over already-ingested text, so they need no
    model call and are safe to re-run: put_links upserts on a stable id.
    """
    from app.services import linking

    collected: list[Any] = []

    for commit in cache.iter_commits(repo):
        message = commit.get("message") or ""
        collected.extend(linking.extract_revert_links(commit["sha"], message, repo))
        collected.extend(
            linking.extract_commit_pr_links(
                commit["sha"],
                commit.get("subject") or "",
                message,
                repo,
                explicit_prs=json.loads(commit.get("pull_requests") or "[]"),
            )
        )
        for number in json.loads(commit.get("closing") or "[]"):
            collected.extend(
                linking.extract_issue_links(
                    source_id=f"pr:{repo}#{number}", source_type="pull_request",
                    text=f"#{number}", repo=repo,
                )
            )

    for doc in cache.iter_documents(repo):
        path = doc.get("path") or ""
        collected.extend(linking.extract_document_supersession(path, doc.get("content") or "", repo))

    file_paths = sorted({commit.get("path") for commit in cache.iter_commit_files(repo)
                         if commit.get("path")})
    collected.extend(linking.extract_containment_links(repo, file_paths))

    rows = [record.as_row() for record in collected]
    return cache.put_links(rows) if rows else 0


def generate_sample_review_file(output_path: Path, samples: list[dict[str, Any]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Extracted Decisions Sample (Manual Verification)",
        "",
        "This file contains extracted decisions and citations for manual audit.",
        "",
        "| # | Decision Summary | Verbatim Quote | Source URL | Verified? |",
        "|---|---|---|---|---|",
    ]
    for idx, s in enumerate(samples, start=1):
        clean_quote = s["quote"].replace("\n", " ").replace("|", "\\|")[:80]
        clean_sum = s["summary"].replace("\n", " ").replace("|", "\\|")[:60]
        lines.append(f"| {idx} | {clean_sum} | `{clean_quote}` | {s['source_url']} | {s['verified']} |")
    lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %d sample review decisions to %s", len(samples), output_path)


if __name__ == "__main__":
    sys.exit(main())
