#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

# Add backend directory to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import settings
from app.providers.llm_provider import TokenBudget, TokenBudgetExhaustedError, get_llm_provider
from app.services.extraction import (
    EXTRACTION_VERSION,
    extract_decisions_from_source,
    summarise_injection_flags,
)
from app.stores.sqlite_cache import SqliteCache

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("codewhy.extract")


def parse_args() -> argparse.Namespace:
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
        "--dry-run",
        action="store_true",
        help="Plan extraction without invoking the LLM or updating the cache",
    )
    parser.add_argument(
        "--sample-review-file",
        type=Path,
        default=REPO_ROOT / "review" / "decisions_sample.md",
        help="Path to generate review/decisions_sample.md markdown report",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cache_path = args.cache
    if not cache_path.exists():
        logger.warning("Cache file %s does not exist; running in dry-run/preview mode.", cache_path)
        return 0

    cache = SqliteCache(cache_path)
    noisy_ids = cache.noisy_record_ids(args.repo)
    logger.info("Found %d noisy records to exclude from extraction", len(noisy_ids))

    budget = TokenBudget(settings.max_llm_tokens_per_run)
    provider = get_llm_provider(budget=budget)

    # Fetch candidate PRs and docs from raw_objects
    rows = cache.fetch_raw_objects(args.repo, limit=args.limit)
    # Counts only. The flagged text itself never reaches a log line.
    injection_counts = summarise_injection_flags(
        [{"source_id": row.get("id"), "injection_detected": row.get("injection_detected")}
         for row in rows]
    )
    logger.info(
        "prompt-injection scan: %d of %d sources flagged",
        injection_counts["sources_flagged"], injection_counts["sources_total"],
    )
    logger.info("Fetched %d raw candidate objects for repo %s", len(rows), args.repo)

    extracted_decisions_count = 0
    extracted_evidence_count = 0
    sample_records: list[dict[str, Any]] = []

    for row in rows:
        source_id = row["id"]
        if source_id in noisy_ids:
            logger.debug("Skipping noisy source: %s", source_id)
            continue

        raw_payload = json.loads(row["payload"])
        source_type = row["kind"]
        source_url = raw_payload.get("url", f"https://github.com/{args.repo}")
        title = raw_payload.get("title", "")
        body = raw_payload.get("body", "")
        author = raw_payload.get("author", {}).get("login") if isinstance(raw_payload.get("author"), dict) else None
        created_at = raw_payload.get("createdAt") or raw_payload.get("created_at")

        if args.dry_run:
            logger.info("[DRY-RUN] Would extract from %s (%s)", source_id, title[:50])
            continue

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
            logger.warning(
                "Token budget exhausted (used=%d/%d). Halting extraction as PARTIAL.",
                budget.total_tokens,
                budget.max_tokens,
            )
            break

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

    logger.info(
        "Extraction finished: %d decisions, %d verified evidence quotes written.",
        extracted_decisions_count,
        extracted_evidence_count,
    )

    if sample_records and args.sample_review_file:
        generate_sample_review_file(args.sample_review_file, sample_records)

    return 0


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
