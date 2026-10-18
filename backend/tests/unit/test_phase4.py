from __future__ import annotations

import datetime
from typing import Any

import pytest

from app.schemas.common import ConfidenceLabel, DecisionState, WhoToAskReason
from app.services.confidence import calculate_confidence
from app.services.state import (
    check_code_differs_from_latest,
    compute_decision_states,
)
from app.services.supersession import (
    REVIEW_STATE_CONFIRMED,
    REVIEW_STATE_PROBABLE,
    RULE_1_REVERT_COMMIT,
    RULE_2_CONFIG_KEY_CHANGED,
    RULE_3_EXPLICIT_PR_TEXT,
    RULE_3B_DESIGN_DOC_STATUS,
    SupersessionEdge,
    compute_supersession_edges,
)
from app.services.who_to_ask import (
    determine_who_to_ask,
    is_active_contributor,
    is_bot_login,
)


# ===========================================================================
# 1. Tests for Rule 1: Revert commit (confirmed)
# ===========================================================================

def test_rule1_revert_commit_creates_confirmed_supersession() -> None:
    decisions = [
        {"id": "dec_A", "source_id": "commit:repo:1111111", "summary": "Add TLS 1.3 support", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "dec_B", "source_id": "commit:repo:2222222", "summary": "Revert TLS 1.3 support", "created_at": "2024-01-02T00:00:00Z"},
    ]
    links = [
        {
            "id": "link_1",
            "rel_type": "REVERTS",
            "source_id": "commit:repo:2222222",
            "target_id": "commit:repo:1111111",
        }
    ]

    edges = compute_supersession_edges(decisions, links=links)
    assert len(edges) == 1
    edge = edges[0]
    assert edge.source_decision_id == "dec_B"
    assert edge.target_decision_id == "dec_A"
    assert edge.rule == RULE_1_REVERT_COMMIT
    assert edge.review_state == REVIEW_STATE_CONFIRMED
    assert edge.confidence == 1.0


def test_rule1_revert_pr_title_matching() -> None:
    decisions = [
        {"id": "dec_A", "source_id": "pr:repo#3456", "summary": "Add TLS settings for HTTP/2", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "dec_B", "source_id": "pr:repo#3466", "summary": "Revert the addition of TLS settings for HTTP/2 (#3456)", "created_at": "2024-01-02T00:00:00Z"},
    ]
    edges = compute_supersession_edges(decisions, links=[])
    assert len(edges) == 1
    edge = edges[0]
    assert edge.source_decision_id == "dec_B"
    assert edge.target_decision_id == "dec_A"
    assert edge.rule == RULE_1_REVERT_COMMIT
    assert edge.review_state == REVIEW_STATE_CONFIRMED


# ===========================================================================
# 2. Tests for Rule 2: Same config key changed later (confirmed for the value)
# ===========================================================================

def test_rule2_same_config_key_changed_later() -> None:
    decisions = [
        {
            "id": "dec_A",
            "source_id": "pr:repo#41",
            "summary": "Cap MAX_RETRIES at 3",
            "affected_entities": ["netclient/config.py:MAX_RETRIES"],
            "created_at": "2024-02-01T00:00:00Z",
        },
        {
            "id": "dec_B",
            "source_id": "pr:repo#77",
            "summary": "Raise MAX_RETRIES to 6",
            "affected_entities": ["netclient/config.py:MAX_RETRIES"],
            "created_at": "2024-06-01T00:00:00Z",
        },
    ]

    edges = compute_supersession_edges(decisions, links=[])
    assert len(edges) == 1
    edge = edges[0]
    assert edge.source_decision_id == "dec_B"
    assert edge.target_decision_id == "dec_A"
    assert edge.rule == RULE_2_CONFIG_KEY_CHANGED
    assert edge.review_state == REVIEW_STATE_CONFIRMED
    assert edge.confidence == 1.0


# ===========================================================================
# 3. Tests for Rule 3: Explicit text in a merged PR (confirmed vs probable)
# ===========================================================================

def test_rule3_explicit_replacement_verb_is_confirmed() -> None:
    decisions = [
        {"id": "dec_1", "source_id": "pr:repo#10", "summary": "Initial socket pool", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "dec_2", "source_id": "pr:repo#25", "summary": "Rewrite connection pool. Supersedes #10 with async architecture", "created_at": "2024-03-01T00:00:00Z"},
    ]

    edges = compute_supersession_edges(decisions, links=[])
    assert len(edges) >= 1
    edge = next(e for e in edges if e.source_decision_id == "dec_2" and e.target_decision_id == "dec_1")
    assert edge.rule == RULE_3_EXPLICIT_PR_TEXT
    assert edge.review_state == REVIEW_STATE_CONFIRMED
    assert edge.confidence == 1.0


def test_rule3_soft_follow_up_is_probable() -> None:
    decisions = [
        {"id": "dec_1", "source_id": "pr:repo#10", "summary": "Initial socket pool", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "dec_2", "source_id": "pr:repo#25", "summary": "Revises #10 to add extra diagnostics", "created_at": "2024-03-01T00:00:00Z"},
    ]

    edges = compute_supersession_edges(decisions, links=[])
    assert len(edges) >= 1
    edge = next(e for e in edges if e.source_decision_id == "dec_2" and e.target_decision_id == "dec_1")
    assert edge.rule == RULE_3_EXPLICIT_PR_TEXT
    assert edge.review_state == REVIEW_STATE_PROBABLE
    assert edge.confidence == 0.6


# ===========================================================================
# 4. Tests for Rule 3b: Design doc status line (confirmed)
# ===========================================================================

def test_rule3b_design_doc_status_supersedes() -> None:
    decisions = [
        {"id": "dec_adr1", "source_id": "doc:repo:docs/adr/0001.md", "summary": "ADR 1: Monolithic architecture", "created_at": "2023-01-01T00:00:00Z"},
        {"id": "dec_adr2", "source_id": "doc:repo:docs/adr/0002.md", "summary": "ADR 2: Modular plugin architecture", "created_at": "2023-06-01T00:00:00Z"},
    ]
    links = [
        {
            "id": "adr_link",
            "rel_type": "SUPERSEDES",
            "derivation_method": "adr_status",
            "source_id": "doc:repo:docs/adr/0002.md",
            "target_id": "doc:repo:docs/adr/0001.md",
        }
    ]

    edges = compute_supersession_edges(decisions, links=links)
    assert len(edges) == 1
    edge = edges[0]
    assert edge.source_decision_id == "dec_adr2"
    assert edge.target_decision_id == "dec_adr1"
    assert edge.rule == RULE_3B_DESIGN_DOC_STATUS
    assert edge.review_state == REVIEW_STATE_CONFIRMED


# ===========================================================================
# 5. Critical Negative Invariant: Newer PR on the same file alone NEVER counts
# ===========================================================================

def test_newer_pr_on_same_file_alone_never_supersedes() -> None:
    decisions = [
        {
            "id": "dec_file_1",
            "source_id": "pr:repo#100",
            "summary": "Add timeout parameter to connectionpool.py",
            "affected_entities": ["src/urllib3/connectionpool.py"],
            "created_at": "2024-01-01T00:00:00Z",
        },
        {
            "id": "dec_file_2",
            "source_id": "pr:repo#200",
            "summary": "Refactor error handling in connectionpool.py",
            "affected_entities": ["src/urllib3/connectionpool.py"],
            "created_at": "2024-06-01T00:00:00Z",
        },
    ]

    # No revert, no config key, no ADR, no explicit supersession text
    edges = compute_supersession_edges(decisions, links=[])
    assert edges == []

    analysis = compute_decision_states(decisions, edges=[])
    assert analysis.states["dec_file_1"].state == DecisionState.ACTIVE
    assert analysis.states["dec_file_2"].state == DecisionState.ACTIVE


# ===========================================================================
# 6. Critical Negative Invariant: Unmerged changes NEVER count
# ===========================================================================

def test_unmerged_change_produces_rejected_and_supersedes_nothing() -> None:
    decisions = [
        {"id": "dec_base", "source_id": "pr:repo#41", "summary": "Base decision", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "dec_unmerged", "source_id": "pr:repo#55", "summary": "Unmerged proposal. Replaces #41", "created_at": "2024-02-01T00:00:00Z"},
    ]
    source_meta = {
        "pr:repo#41": {"merged": True},
        "pr:repo#55": {"merged": False, "state": "CLOSED"},
    }

    edges = compute_supersession_edges(decisions, links=[], source_metadata=source_meta)
    assert edges == []

    analysis = compute_decision_states(decisions, edges=edges, source_metadata=source_meta)
    assert analysis.states["dec_unmerged"].state == DecisionState.REJECTED
    assert analysis.states["dec_unmerged"].supersedes == []
    assert analysis.states["dec_unmerged"].superseded_by == []
    assert analysis.states["dec_base"].state == DecisionState.ACTIVE


# ===========================================================================
# 7. Reversal-of-Reversal Chain: B replaces A, C reverts B -> B SUPERSEDED, A ACTIVE
# ===========================================================================

def test_revert_of_revert_reactivates_original_decision() -> None:
    """Core Phase 4 Invariant:

    B replaces A, C reverts B:
    - C is ACTIVE (the revert)
    - B is SUPERSEDED (by C)
    - A is reactivated to ACTIVE (because B, which superseded A, is itself superseded!)
    """
    decisions = [
        {"id": "dec_A", "summary": "Cap MAX_RETRIES at 3", "created_at": "2024-02-01T00:00:00Z"},
        {"id": "dec_B", "summary": "Raise MAX_RETRIES to 6", "created_at": "2024-06-01T00:00:00Z"},
        {"id": "dec_C", "summary": "Revert MAX_RETRIES to 3", "created_at": "2024-08-01T00:00:00Z"},
    ]

    edges = [
        SupersessionEdge(
            source_decision_id="dec_B",
            target_decision_id="dec_A",
            rule=RULE_2_CONFIG_KEY_CHANGED,
            method="config_value_change",
            confidence=1.0,
            source_evidence_id="cfg_1",
            review_state=REVIEW_STATE_CONFIRMED,
        ),
        SupersessionEdge(
            source_decision_id="dec_C",
            target_decision_id="dec_B",
            rule=RULE_1_REVERT_COMMIT,
            method="revert_commit",
            confidence=1.0,
            source_evidence_id="revert_1",
            review_state=REVIEW_STATE_CONFIRMED,
        ),
    ]

    analysis = compute_decision_states(decisions, edges=edges)

    assert analysis.states["dec_C"].state == DecisionState.ACTIVE
    assert analysis.states["dec_B"].state == DecisionState.SUPERSEDED
    assert analysis.states["dec_A"].state == DecisionState.ACTIVE  # Reactivated!

    # Edge linkages recorded
    assert analysis.states["dec_C"].supersedes == ["dec_B"]
    assert "dec_C" in analysis.states["dec_B"].superseded_by
    assert "dec_B" in analysis.states["dec_A"].superseded_by

    # Code differs check
    assert check_code_differs_from_latest("dec_B", analysis, decisions) is True
    assert check_code_differs_from_latest("dec_C", analysis, decisions) is False


# ===========================================================================
# 8. Ambiguous / Cycle / Contradiction cases (UNRESOLVED)
# ===========================================================================

def test_cycle_produces_unresolved_and_contradiction() -> None:
    decisions = [
        {"id": "dec_X", "summary": "Feature X", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "dec_Y", "summary": "Feature Y", "created_at": "2024-02-01T00:00:00Z"},
    ]
    # Pathological mutual supersession cycle
    edges = [
        SupersessionEdge(
            source_decision_id="dec_Y",
            target_decision_id="dec_X",
            rule=RULE_3_EXPLICIT_PR_TEXT,
            method="explicit_text",
            confidence=1.0,
            source_evidence_id="e1",
            review_state=REVIEW_STATE_CONFIRMED,
        ),
        SupersessionEdge(
            source_decision_id="dec_X",
            target_decision_id="dec_Y",
            rule=RULE_3_EXPLICIT_PR_TEXT,
            method="explicit_text",
            confidence=1.0,
            source_evidence_id="e2",
            review_state=REVIEW_STATE_CONFIRMED,
        ),
    ]

    analysis = compute_decision_states(decisions, edges=edges)
    assert analysis.has_contradiction is True


# ===========================================================================
# 9. Confidence Formula: Contradiction Cap at 0.70
# ===========================================================================

def test_contradiction_caps_confidence_score_at_070() -> None:
    # Even with max directness, provenance, agreement, relevance, and temporal consistency
    conf_no_contradiction = calculate_confidence(
        directness=1.0,
        provenance=1.0,
        agreement=1.0,
        relevance=1.0,
        temporal_consistency=1.0,
        contradiction=0.0,
    )
    assert conf_no_contradiction.score == 1.0
    assert conf_no_contradiction.label == ConfidenceLabel.HIGH

    conf_with_contradiction = calculate_confidence(
        directness=1.0,
        provenance=1.0,
        agreement=1.0,
        relevance=1.0,
        temporal_consistency=1.0,
        contradiction=1.0,
    )
    assert conf_with_contradiction.score <= 0.70
    assert conf_with_contradiction.label == ConfidenceLabel.MEDIUM


# ===========================================================================
# 10. WhoToAsk Contributor Ranking & Bot Filtering
# ===========================================================================

def test_who_to_ask_filters_bots_and_limits_to_three() -> None:
    decisions = [
        {"id": "dec_1", "source_author": "alice", "created_at": "2024-05-01T00:00:00Z"},
        {"id": "dec_2", "source_author": "dependabot[bot]", "created_at": "2024-06-01T00:00:00Z"},
        {"id": "dec_3", "source_author": "renovate-bot", "created_at": "2024-07-01T00:00:00Z"},
    ]
    sources = [
        {
            "id": "pr_1",
            "reviewers": [
                {"login": "bob", "submittedAt": "2024-05-02T00:00:00Z"},
                {"login": "github-actions[bot]", "submittedAt": "2024-05-02T00:00:00Z"},
                {"login": "charlie", "submittedAt": "2024-05-03T00:00:00Z"},
                {"login": "dave", "submittedAt": "2024-05-04T00:00:00Z"},
            ]
        }
    ]

    ref_date = datetime.datetime(2024, 8, 1, tzinfo=datetime.timezone.utc)
    candidates = determine_who_to_ask(decisions, sources=sources, reference_date=ref_date)

    assert len(candidates) <= 3
    logins = [c.login for c in candidates]
    assert "alice" in logins
    assert "bob" in logins
    assert "charlie" in logins
    assert "dependabot[bot]" not in logins
    assert "github-actions[bot]" not in logins
    assert "renovate-bot" not in logins


def test_inactive_person_marked_inactive() -> None:
    ref_date = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)

    # Activity 2 years ago (> 365 days) -> inactive
    assert is_active_contributor("2023-01-01T00:00:00Z", reference_date=ref_date) is False

    # Activity 2 months ago (within 365 days) -> active
    assert is_active_contributor("2024-11-01T00:00:00Z", reference_date=ref_date) is True
