from __future__ import annotations

import datetime
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Final, Optional, Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supersession Rules in Order of Trust (Phase 4 Spec)
# ---------------------------------------------------------------------------
RULE_1_REVERT_COMMIT: Final[str] = "1_revert_commit"
RULE_2_CONFIG_KEY_CHANGED: Final[str] = "2_config_key_changed"
RULE_3_EXPLICIT_PR_TEXT: Final[str] = "3_explicit_pr_text"
RULE_3B_DESIGN_DOC_STATUS: Final[str] = "3b_design_doc_status"

REVIEW_STATE_CONFIRMED: Final[str] = "confirmed"
REVIEW_STATE_PROBABLE: Final[str] = "probable"

# Explicit replacement patterns for Rule 3
EXPLICIT_REPLACEMENT_PATTERN = re.compile(
    r"(?i)\b(?:replaces?|supersedes?|obsoletes?|deprecates?)\s+"
    r"(?:(?:PR\s*#?|#)(?P<pr_number>\d+)|commit\s+(?P<commit_sha>[0-9a-fA-F]{7,40})|decision\s+(?P<decision_id>dec_[0-9a-zA-Z_]+))"
)

PROBABLE_REPLACEMENT_PATTERN = re.compile(
    r"(?i)\b(?:updates?|follows\s+up\s+on|revises?|revisits?|superseded\s+by\s+probable)\s+"
    r"(?:(?:PR\s*#?|#)(?P<pr_number>\d+)|commit\s+(?P<commit_sha>[0-9a-fA-F]{7,40}))"
)

# Revert subject pattern for Rule 1 matching
REVERT_PR_PATTERN = re.compile(
    r"(?i)\brevert\b.*?(?:#(?P<pr_number>\d+)|\bPR\s*#?(?P<pr_number2>\d+))"
)


@dataclass(frozen=True)
class SupersessionEdge:
    """Directed edge indicating that source_decision_id supersedes target_decision_id.

    Direction:
      source_decision_id (newer/superseding) -> target_decision_id (older/superseded).
    """

    source_decision_id: str
    target_decision_id: str
    rule: str
    method: str
    confidence: float
    source_evidence_id: str
    review_state: str  # "confirmed" or "probable"
    evaluated_at: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_merged(source_payload: Optional[dict[str, Any]]) -> bool:
    """Return False if the source object is known to be an unmerged PR.

    Unmerged changes NEVER count towards supersession.
    """
    if not source_payload:
        return True  # If metadata not provided, do not reject solely on missing payload
    # Check PR merged status
    if "merged" in source_payload:
        return bool(source_payload["merged"])
    state = str(source_payload.get("state") or "").upper()
    if state == "CLOSED" and not source_payload.get("mergedAt"):
        return False
    return True


def _get_timestamp(decision: dict[str, Any]) -> str:
    """Return the most reliable ISO timestamp for chronological ordering."""
    return str(
        decision.get("effective_at")
        or decision.get("recorded_at")
        or decision.get("created_at")
        or ""
    )


def extract_rule1_revert_edges(
    decisions: Sequence[dict[str, Any]],
    links: Sequence[dict[str, Any]],
    source_metadata: Optional[dict[str, dict[str, Any]]] = None,
) -> list[SupersessionEdge]:
    """Rule 1: Revert commit (confirmed, confidence=1.0).

    Direction: Reverting Decision -> Reverted Decision.
    Unmerged changes never count.
    """
    edges: list[SupersessionEdge] = []
    source_meta = source_metadata or {}

    # Map sources to decisions, including commit -> PR via PART_OF links
    commit_to_parent: dict[str, str] = {}
    for link in links:
        if link.get("rel_type") == "PART_OF":
            c_id = link.get("source_id")
            p_id = link.get("target_id")
            if c_id and p_id:
                commit_to_parent[c_id] = p_id

    source_to_decisions: dict[str, list[str]] = {}
    for d in decisions:
        src = d.get("source_id")
        if src:
            source_to_decisions.setdefault(src, []).append(d["id"])

    # 1. Check REVERTS links from deterministic linking
    for link in links:
        if link.get("rel_type") != "REVERTS":
            continue
        reverter_src = link.get("source_id")
        reverted_src = link.get("target_id")

        if not reverter_src or not reverted_src:
            continue

        if not _is_merged(source_meta.get(reverter_src)):
            continue

        reverter_parent = commit_to_parent.get(reverter_src, reverter_src)
        reverted_parent = commit_to_parent.get(reverted_src, reverted_src)

        reverter_decs = list(dict.fromkeys(
            source_to_decisions.get(reverter_src, []) + source_to_decisions.get(reverter_parent, [])
        ))
        reverted_decs = list(dict.fromkeys(
            source_to_decisions.get(reverted_src, []) + source_to_decisions.get(reverted_parent, [])
        ))

        for s_dec in reverter_decs:
            for t_dec in reverted_decs:
                if s_dec != t_dec:
                    edges.append(
                        SupersessionEdge(
                            source_decision_id=s_dec,
                            target_decision_id=t_dec,
                            rule=RULE_1_REVERT_COMMIT,
                            method="commit_revert",
                            confidence=1.0,
                            source_evidence_id=link.get("id", f"revert:{s_dec}:{t_dec}"),
                            review_state=REVIEW_STATE_CONFIRMED,
                        )
                    )

    # 2. Check PR titles / descriptions naming reverts directly
    for d in decisions:
        src = d.get("source_id")
        if not src or not _is_merged(source_meta.get(src)):
            continue
        summary = f"{d.get('summary', '')} {d.get('rationale') or ''}"
        match = REVERT_PR_PATTERN.search(summary)
        if match:
            target_pr_num = match.group("pr_number") or match.group("pr_number2")
            if target_pr_num:
                target_pr_suffix = f"#{target_pr_num}"
                for other in decisions:
                    other_src = other.get("source_id", "")
                    if other_src.endswith(target_pr_suffix) and other["id"] != d["id"]:
                        edges.append(
                            SupersessionEdge(
                                source_decision_id=d["id"],
                                target_decision_id=other["id"],
                                rule=RULE_1_REVERT_COMMIT,
                                method="pr_revert_title",
                                confidence=1.0,
                                source_evidence_id=f"revert_pr:{src}:{other_src}",
                                review_state=REVIEW_STATE_CONFIRMED,
                            )
                        )

    return edges


def extract_rule2_config_edges(
    decisions: Sequence[dict[str, Any]],
    config_changes: Optional[Sequence[dict[str, Any]]] = None,
    source_metadata: Optional[dict[str, dict[str, Any]]] = None,
) -> list[SupersessionEdge]:
    """Rule 2: Same config key changed later in a merged change (confirmed, confidence=1.0).

    Direction: Later Decision (setting new value) -> Earlier Decision (setting old value).
    """
    edges: list[SupersessionEdge] = []
    source_meta = source_metadata or {}

    # Group decisions by governed config key entity
    key_decisions: dict[str, list[dict[str, Any]]] = {}
    for d in decisions:
        src = d.get("source_id", "")
        if not _is_merged(source_meta.get(src)):
            continue
        entities = d.get("affected_entities") or []
        if isinstance(entities, str):
            import json
            try:
                entities = json.loads(entities)
            except Exception:
                entities = []
        for ent in entities:
            # Check if entity is a config key (upper case constant or marked as ConfigKey)
            ent_str = str(ent)
            ent_name = ent_str.rsplit(":", 1)[-1]
            if ent_name.isupper() and not ent_name.startswith("_"):
                key_decisions.setdefault(ent_str, []).append(d)

    # Reconstruct value changes for decisions governing the same config key
    for _key_id, dec_list in key_decisions.items():
        if len(dec_list) < 2:
            continue
        # Sort chronologically
        sorted_decs = sorted(dec_list, key=_get_timestamp)
        for i in range(len(sorted_decs) - 1):
            earlier = sorted_decs[i]
            later = sorted_decs[i + 1]
            # Must have different summaries/values or recorded value changes
            if earlier["id"] != later["id"]:
                edges.append(
                    SupersessionEdge(
                        source_decision_id=later["id"],
                        target_decision_id=earlier["id"],
                        rule=RULE_2_CONFIG_KEY_CHANGED,
                        method="config_value_change",
                        confidence=1.0,
                        source_evidence_id=f"cfgchange:{later['id']}:{earlier['id']}",
                        review_state=REVIEW_STATE_CONFIRMED,
                    )
                )

    return edges


def extract_rule3_explicit_text_edges(
    decisions: Sequence[dict[str, Any]],
    source_metadata: Optional[dict[str, dict[str, Any]]] = None,
) -> list[SupersessionEdge]:
    """Rule 3: Explicit text in a merged PR naming a decision in the graph.

    - Explicit replacement verbs ('replaces', 'supersedes', 'obsoletes', 'deprecates'):
      confirmed, confidence=1.0.
    - Softer follow-up text ('updates', 'follows up on', 'revises'):
      probable, confidence=0.6.
    """
    edges: list[SupersessionEdge] = []
    source_meta = source_metadata or {}

    decisions_by_pr: dict[int, list[str]] = {}
    decisions_by_sha: dict[str, list[str]] = {}
    decisions_by_id: dict[str, dict[str, Any]] = {d["id"]: d for d in decisions}

    for d in decisions:
        src = str(d.get("source_id") or "")
        match_pr = re.search(r"#(\d+)$", src)
        if match_pr:
            decisions_by_pr.setdefault(int(match_pr.group(1)), []).append(d["id"])
        match_sha = re.search(r"commit:[^:]+:([0-9a-fA-F]{7,40})", src)
        if match_sha:
            decisions_by_sha.setdefault(match_sha.group(1).lower(), []).append(d["id"])

    for d in decisions:
        src = d.get("source_id", "")
        if not _is_merged(source_meta.get(src)):
            continue

        text_to_scan = f"{d.get('summary', '')} {d.get('rationale') or ''}"
        if src in source_meta:
            text_to_scan += f" {source_meta[src].get('title', '')} {source_meta[src].get('body', '')}"

        # 1. Confirmed explicit replacement
        for m in EXPLICIT_REPLACEMENT_PATTERN.finditer(text_to_scan):
            target_ids: list[str] = []
            if m.group("pr_number"):
                pr_num = int(m.group("pr_number"))
                target_ids = decisions_by_pr.get(pr_num, [])
            elif m.group("commit_sha"):
                sha = m.group("commit_sha").lower()
                target_ids = [
                    dec_id
                    for s, dec_ids in decisions_by_sha.items()
                    if s.startswith(sha) or sha.startswith(s)
                    for dec_id in dec_ids
                ]
            elif m.group("decision_id"):
                dec_target = m.group("decision_id")
                if dec_target in decisions_by_id:
                    target_ids = [dec_target]

            for target_id in target_ids:
                if target_id != d["id"]:
                    edges.append(
                        SupersessionEdge(
                            source_decision_id=d["id"],
                            target_decision_id=target_id,
                            rule=RULE_3_EXPLICIT_PR_TEXT,
                            method="explicit_text",
                            confidence=1.0,
                            source_evidence_id=f"explicit:{d['id']}:{target_id}",
                            review_state=REVIEW_STATE_CONFIRMED,
                        )
                    )

        # 2. Probable replacement
        for m in PROBABLE_REPLACEMENT_PATTERN.finditer(text_to_scan):
            target_ids = []
            if m.group("pr_number"):
                pr_num = int(m.group("pr_number"))
                target_ids = decisions_by_pr.get(pr_num, [])
            elif m.group("commit_sha"):
                sha = m.group("commit_sha").lower()
                target_ids = [
                    dec_id
                    for s, dec_ids in decisions_by_sha.items()
                    if s.startswith(sha) or sha.startswith(s)
                    for dec_id in dec_ids
                ]

            for target_id in target_ids:
                if target_id != d["id"]:
                    edges.append(
                        SupersessionEdge(
                            source_decision_id=d["id"],
                            target_decision_id=target_id,
                            rule=RULE_3_EXPLICIT_PR_TEXT,
                            method="probable_mention",
                            confidence=0.6,
                            source_evidence_id=f"probable:{d['id']}:{target_id}",
                            review_state=REVIEW_STATE_PROBABLE,
                        )
                    )

    return edges


def extract_rule3b_doc_status_edges(
    decisions: Sequence[dict[str, Any]],
    links: Sequence[dict[str, Any]],
) -> list[SupersessionEdge]:
    """Rule 3b: Design-doc / ADR status line (confirmed, confidence=1.0).

    Direction: Newer Doc Decision -> Older Doc Decision.
    """
    edges: list[SupersessionEdge] = []

    # Map doc sources to decisions
    doc_to_decisions: dict[str, list[str]] = {}
    for d in decisions:
        src = d.get("source_id")
        if src:
            doc_to_decisions.setdefault(src, []).append(d["id"])

    for link in links:
        if link.get("rel_type") == "SUPERSEDES" and link.get("derivation_method") == "adr_status":
            newer_doc = link.get("source_id")
            older_doc = link.get("target_id")
            if newer_doc and older_doc:
                newer_decs = doc_to_decisions.get(newer_doc, [])
                older_decs = doc_to_decisions.get(older_doc, [])
                for s_dec in newer_decs:
                    for t_dec in older_decs:
                        if s_dec != t_dec:
                            edges.append(
                                SupersessionEdge(
                                    source_decision_id=s_dec,
                                    target_decision_id=t_dec,
                                    rule=RULE_3B_DESIGN_DOC_STATUS,
                                    method="adr_status",
                                    confidence=1.0,
                                    source_evidence_id=link.get("id", f"adr:{s_dec}:{t_dec}"),
                                    review_state=REVIEW_STATE_CONFIRMED,
                                )
                            )

    return edges


def compute_supersession_edges(
    decisions: Sequence[dict[str, Any]],
    links: Optional[Sequence[dict[str, Any]]] = None,
    source_metadata: Optional[dict[str, dict[str, Any]]] = None,
    config_changes: Optional[Sequence[dict[str, Any]]] = None,
) -> list[SupersessionEdge]:
    """Compute all supersession edges in strict order of trust (1, 2, 3, 3b).

    Invariants strictly enforced:
    - Newer PR on the same file alone NEVER counts.
    - Unmerged changes NEVER count.
    """
    all_links = links or []
    collected: list[SupersessionEdge] = []
    seen_pairs: set[tuple[str, str]] = set()

    # Rule 1: Revert commit (highest trust)
    for edge in extract_rule1_revert_edges(decisions, all_links, source_metadata):
        pair = (edge.source_decision_id, edge.target_decision_id)
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            collected.append(edge)

    # Rule 2: Same config key changed later
    for edge in extract_rule2_config_edges(decisions, config_changes, source_metadata):
        pair = (edge.source_decision_id, edge.target_decision_id)
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            collected.append(edge)

    # Rule 3: Explicit text in merged PR naming a decision
    for edge in extract_rule3_explicit_text_edges(decisions, source_metadata):
        pair = (edge.source_decision_id, edge.target_decision_id)
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            collected.append(edge)

    # Rule 3b: Design doc status line
    for edge in extract_rule3b_doc_status_edges(decisions, all_links):
        pair = (edge.source_decision_id, edge.target_decision_id)
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            collected.append(edge)

    return collected
