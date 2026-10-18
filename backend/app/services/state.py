from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from app.schemas.common import DecisionState
from app.services.supersession import REVIEW_STATE_CONFIRMED, REVIEW_STATE_PROBABLE, SupersessionEdge, _get_timestamp, _is_merged

logger = logging.getLogger(__name__)


@dataclass
class DecisionStateResult:
    decision_id: str
    state: DecisionState
    supersedes: list[str] = field(default_factory=list)
    superseded_by: list[str] = field(default_factory=list)
    rule: Optional[str] = None
    probable_superseded_by: list[str] = field(default_factory=list)
    conflicts_with: list[str] = field(default_factory=list)
    reaffirms: list[str] = field(default_factory=list)


@dataclass
class RepositoryStateAnalysis:
    states: dict[str, DecisionStateResult]
    supersession_chains: list[list[str]] = field(default_factory=list)
    has_contradiction: bool = False
    chain_truncated: bool = False


def compute_decision_states(
    decisions: Sequence[dict[str, Any]],
    edges: Sequence[SupersessionEdge],
    source_metadata: Optional[dict[str, dict[str, Any]]] = None,
    max_chain_length: int = 6,
) -> RepositoryStateAnalysis:
    """Compute ACTIVE, SUPERSEDED, REJECTED, UNRESOLVED states across all decisions.

    Core Invariant:
    A decision A is SUPERSEDED only if a confirmed SUPERSEDES edge B -> A comes from
    a decision B that is NOT itself SUPERSEDED (e.g., Revert-of-Revert:
    B replaces A, C reverts B -> C is ACTIVE, B is SUPERSEDED, A reactivates to ACTIVE).
    """
    source_meta = source_metadata or {}
    states: dict[str, DecisionStateResult] = {}

    # Initialize all decision state entries
    for d in decisions:
        dec_id = d["id"]
        src = d.get("source_id", "")
        # Rule: Unmerged PR decisions are REJECTED
        if not _is_merged(source_meta.get(src)):
            states[dec_id] = DecisionStateResult(
                decision_id=dec_id,
                state=DecisionState.REJECTED,
                supersedes=[],
                superseded_by=[],
            )
        else:
            states[dec_id] = DecisionStateResult(
                decision_id=dec_id,
                state=DecisionState.ACTIVE,
                supersedes=[],
                superseded_by=[],
            )

    # Filter edges: unmerged changes never count
    valid_edges = [
        e for e in edges
        if e.source_decision_id in states
        and e.target_decision_id in states
        and states[e.source_decision_id].state != DecisionState.REJECTED
        and states[e.target_decision_id].state != DecisionState.REJECTED
    ]

    # Map edges: superseding -> superseded (source -> target)
    confirmed_supersedes_map: dict[str, list[SupersessionEdge]] = {}  # source -> targets
    confirmed_superseded_by_map: dict[str, list[SupersessionEdge]] = {}  # target -> sources
    probable_superseded_by_map: dict[str, list[SupersessionEdge]] = {}

    for e in valid_edges:
        if e.review_state == REVIEW_STATE_CONFIRMED:
            confirmed_supersedes_map.setdefault(e.source_decision_id, []).append(e)
            confirmed_superseded_by_map.setdefault(e.target_decision_id, []).append(e)
        elif e.review_state == REVIEW_STATE_PROBABLE:
            probable_superseded_by_map.setdefault(e.target_decision_id, []).append(e)

    # Sort non-rejected decisions in reverse chronological order (newest first)
    non_rejected = [d for d in decisions if states[d["id"]].state != DecisionState.REJECTED]
    sorted_decs = sorted(non_rejected, key=_get_timestamp, reverse=True)

    # Compute supersession state:
    # Evaluate newest to oldest. Since any superseding decision must be newer than the decision it replaces,
    # when evaluating decision A, all potential superseding decisions B have already had their states evaluated!
    for d in sorted_decs:
        dec_id = d["id"]
        incoming_edges = confirmed_superseded_by_map.get(dec_id, [])

        # Find if there is an active (not superseded) superseding decision
        active_superseders = [
            e for e in incoming_edges
            if states[e.source_decision_id].state == DecisionState.ACTIVE
        ]

        if active_superseders:
            states[dec_id].state = DecisionState.SUPERSEDED
            # Record confirmed superseding decisions
            for e in active_superseders:
                if e.source_decision_id not in states[dec_id].superseded_by:
                    states[dec_id].superseded_by.append(e.source_decision_id)
                if not states[dec_id].rule:
                    states[dec_id].rule = e.rule
                # Record in the source decision that it supersedes dec_id
                if dec_id not in states[e.source_decision_id].supersedes:
                    states[e.source_decision_id].supersedes.append(dec_id)
                if not states[e.source_decision_id].rule:
                    states[e.source_decision_id].rule = e.rule
        else:
            # If all incoming superseders are themselves superseded, A stays/reactivates to ACTIVE!
            states[dec_id].state = DecisionState.ACTIVE
            # Even if reactivated, record historical superseded_by for transparency if edge existed
            for e in incoming_edges:
                if e.source_decision_id not in states[dec_id].superseded_by:
                    states[dec_id].superseded_by.append(e.source_decision_id)
                if dec_id not in states[e.source_decision_id].supersedes:
                    states[e.source_decision_id].supersedes.append(dec_id)

        # Probable superseders
        for pe in probable_superseded_by_map.get(dec_id, []):
            if pe.source_decision_id not in states[dec_id].probable_superseded_by:
                states[dec_id].probable_superseded_by.append(pe.source_decision_id)

    # Check for contradictions / unresolved states:
    # Contradiction occurs if two decisions with opposite claims govern the same entity with active status
    has_contradiction = False
    for d_id, res in states.items():
        if res.state == DecisionState.UNRESOLVED or res.conflicts_with:
            has_contradiction = True

    # Build supersession chains up to max_chain_length
    supersession_chains: list[list[str]] = []
    chain_truncated = False

    for d in sorted_decs:
        dec_id = d["id"]
        # Only start chains from top-level / active superseding decisions
        if states[dec_id].supersedes:
            chain = [dec_id]
            curr = dec_id
            visited = {curr}
            depth = 1
            while states[curr].supersedes:
                if depth >= max_chain_length:
                    chain_truncated = True
                    break
                # Follow next superseded node
                next_id = states[curr].supersedes[0]
                if next_id in visited:
                    # Cycle detected
                    has_contradiction = True
                    states[curr].state = DecisionState.UNRESOLVED
                    states[next_id].state = DecisionState.UNRESOLVED
                    break
                visited.add(next_id)
                chain.append(next_id)
                curr = next_id
                depth += 1
            if len(chain) > 1 and chain not in supersession_chains:
                supersession_chains.append(chain)

    return RepositoryStateAnalysis(
        states=states,
        supersession_chains=supersession_chains,
        has_contradiction=has_contradiction,
        chain_truncated=chain_truncated,
    )


def check_code_differs_from_latest(
    decision_id: str,
    analysis: RepositoryStateAnalysis,
    decisions: Sequence[dict[str, Any]],
) -> bool:
    """Return True if the decision is superseded or its value differs from the latest active value."""
    state_res = analysis.states.get(decision_id)
    if not state_res:
        return False
    if state_res.state == DecisionState.SUPERSEDED:
        return True

    # If any decision in the same chain is active and different
    for chain in analysis.supersession_chains:
        if decision_id in chain:
            head = chain[0]
            if head != decision_id and analysis.states.get(head, {}).state == DecisionState.ACTIVE:
                return True

    return False
