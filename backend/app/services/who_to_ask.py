from __future__ import annotations

import datetime
import logging
import re
from typing import Any, Optional, Sequence

from app.schemas.common import WhoToAskReason
from app.schemas.decisions import WhoToAsk

logger = logging.getLogger(__name__)

# Known bot logins and suffixes
BOT_SUFFIXES = ("[bot]", "-bot", "_bot")
KNOWN_BOT_LOGINS = frozenset({
    "dependabot",
    "dependabot[bot]",
    "renovate",
    "renovate[bot]",
    "github-actions",
    "github-actions[bot]",
    "codecov",
    "codecov[bot]",
    "web-flow",
    "bors",
    "stale",
    "stale[bot]",
})

BOT_REGEX = re.compile(r"(?i)(?:^|[-_])bot(?:\[bot\])?$")
MAX_WHO_TO_ASK = 3
ACTIVE_WINDOW_DAYS = 365


def is_bot_login(login: str) -> bool:
    """Return True if login belongs to a bot account."""
    if not login or not login.strip():
        return True
    clean = login.strip().lower()
    if clean in KNOWN_BOT_LOGINS:
        return True
    if any(clean.endswith(suffix) for suffix in BOT_SUFFIXES):
        return True
    if BOT_REGEX.search(clean):
        return True
    return False


def _parse_iso_date(dt_str: Optional[str]) -> Optional[datetime.datetime]:
    if not dt_str:
        return None
    try:
        # Handles Z and ISO offsets
        clean = dt_str.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(clean)
    except Exception:
        return None


def is_active_contributor(
    last_activity_date: Optional[str],
    reference_date: Optional[datetime.datetime] = None,
) -> bool:
    """Return True if the person committed or was active in the last 12 months (365 days)."""
    if not last_activity_date:
        return False
    parsed = _parse_iso_date(last_activity_date)
    if not parsed:
        return False
    # Ensure timezone aware
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)

    ref = reference_date or datetime.datetime.now(datetime.timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=datetime.timezone.utc)

    delta = ref - parsed
    return 0 <= delta.days <= ACTIVE_WINDOW_DAYS


def determine_who_to_ask(
    decisions: Sequence[dict[str, Any]],
    sources: Optional[Sequence[dict[str, Any]]] = None,
    commits: Optional[Sequence[dict[str, Any]]] = None,
    people: Optional[Sequence[dict[str, Any]]] = None,
    evidence_items: Optional[Sequence[Any]] = None,
    store: Optional[Any] = None,
    reference_date: Optional[datetime.datetime] = None,
) -> list[WhoToAsk]:
    """Rank at most 3 persons to ask for a code entity/decision.

    Prioritizes:
      1. Author of the relevant PR/commit
      2. Reviewer or commenter on the change
      3. Top recent contributor to the entity/repo

    Invariants:
      - At most 3 people.
      - Bots are always skipped.
      - Active flag indicates whether they committed in the last 12 months.
    """
    results: list[WhoToAsk] = []
    seen_logins: set[str] = set()

    sources_map: dict[str, dict[str, Any]] = {}
    if sources:
        for s in sources:
            sid = s.get("id")
            if sid:
                sources_map[sid] = s

    # 1. Authors of decisions, evidence items, and their sources
    for d in decisions:
        author = d.get("source_author") or d.get("author")
        src_id = d.get("source_id")
        timestamp = d.get("effective_at") or d.get("recorded_at") or d.get("created_at")

        if not author and d.get("evidence"):
            for ev in d["evidence"]:
                ev_author = ev.get("author") if isinstance(ev, dict) else getattr(ev, "author", None)
                if ev_author:
                    author = ev_author
                    timestamp = timestamp or (ev.get("timestamp") if isinstance(ev, dict) else getattr(ev, "timestamp", None))
                    break

        if not author and src_id and src_id in sources_map:
            src = sources_map[src_id]
            author = src.get("author") or src.get("author_login")
            timestamp = timestamp or src.get("created_at") or src.get("createdAt")

        if not author and src_id:
            if store and hasattr(store, "get_node"):
                node = store.get_node(src_id)
                if node:
                    author = node.get("author") or node.get("author_login")
            if not author:
                try:
                    from pathlib import Path
                    import sqlite3, json
                    default_db = Path("data/ingest.sqlite3")
                    if default_db.exists():
                        conn = sqlite3.connect(str(default_db))
                        cur = conn.cursor()
                        cur.execute("SELECT json FROM raw_objects WHERE id = ?", (src_id,))
                        row = cur.fetchone()
                        if row and row[0]:
                            payload = json.loads(row[0])
                            author = payload.get("author") or payload.get("author_login")
                            timestamp = timestamp or payload.get("createdAt") or payload.get("created_at")
                        conn.close()
                except Exception:
                    pass

        if author and not is_bot_login(author):
            clean_login = author.strip()
            if clean_login.lower() not in seen_logins:
                seen_logins.add(clean_login.lower())
                active = is_active_contributor(timestamp, reference_date)
                results.append(
                    WhoToAsk(
                        login=clean_login,
                        reason=WhoToAskReason.AUTHOR,
                        active=active,
                    )
                )
                if len(results) >= MAX_WHO_TO_ASK:
                    return results

    if evidence_items:
        for ev in evidence_items:
            ev_author = getattr(ev, "author", None) if hasattr(ev, "author") else (ev.get("author") if isinstance(ev, dict) else None)
            ts = getattr(ev, "timestamp", None) if hasattr(ev, "timestamp") else (ev.get("timestamp") if isinstance(ev, dict) else None)
            if ev_author and not is_bot_login(ev_author):
                clean_login = ev_author.strip()
                if clean_login.lower() not in seen_logins:
                    seen_logins.add(clean_login.lower())
                    active = is_active_contributor(ts, reference_date)
                    results.append(
                        WhoToAsk(
                            login=clean_login,
                            reason=WhoToAskReason.AUTHOR,
                            active=active,
                        )
                    )
                    if len(results) >= MAX_WHO_TO_ASK:
                        return results

    # 2. Reviewers and commenters from sources
    if sources:
        for s in sources:
            reviewers = s.get("reviewers") or []
            if isinstance(reviewers, list):
                for rev in reviewers:
                    login = rev.get("login") if isinstance(rev, dict) else str(rev)
                    ts = rev.get("submittedAt") if isinstance(rev, dict) else s.get("created_at")
                    if login and not is_bot_login(login):
                        clean_login = login.strip()
                        if clean_login.lower() not in seen_logins:
                            seen_logins.add(clean_login.lower())
                            active = is_active_contributor(ts, reference_date)
                            results.append(
                                WhoToAsk(
                                    login=clean_login,
                                    reason=WhoToAskReason.REVIEWER,
                                    active=active,
                                )
                            )
                            if len(results) >= MAX_WHO_TO_ASK:
                                return results

    # 3. Top recent contributors from commits / people
    candidate_commits = commits or []
    for c in candidate_commits:
        author = c.get("author_name") or c.get("author") or c.get("committer")
        ts = c.get("authored_at") or c.get("committed_at") or c.get("created_at")
        if author and not is_bot_login(author):
            clean_login = author.strip()
            if clean_login.lower() not in seen_logins:
                seen_logins.add(clean_login.lower())
                active = is_active_contributor(ts, reference_date)
                results.append(
                    WhoToAsk(
                        login=clean_login,
                        reason=WhoToAskReason.RECENT_CONTRIBUTOR,
                        active=active,
                    )
                )
                if len(results) >= MAX_WHO_TO_ASK:
                    return results

    # 4. From people list if provided
    if people:
        for p in people:
            login = p.get("login") or p.get("name")
            ts = p.get("last_committed_at") or p.get("created_at")
            if login and not is_bot_login(login):
                clean_login = login.strip()
                if clean_login.lower() not in seen_logins:
                    seen_logins.add(clean_login.lower())
                    active = p.get("active")
                    if active is None:
                        active = is_active_contributor(ts, reference_date)
                    reason_val = p.get("reason")
                    try:
                        reason = WhoToAskReason(reason_val)
                    except Exception:
                        reason = WhoToAskReason.RECENT_CONTRIBUTOR
                    results.append(
                        WhoToAsk(
                            login=clean_login,
                            reason=reason,
                            active=bool(active),
                        )
                    )
                    if len(results) >= MAX_WHO_TO_ASK:
                        return results

    return results
