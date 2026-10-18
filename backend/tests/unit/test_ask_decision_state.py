"""The ask path must reuse the state the graph already stores.

The graph build persists `state`, `supersedes`, `superseded_by` and `rule` on each
Decision. Retrieval used to recompute those fields from links, which lost the
persisted supersession when the graph's links were not enough to rebuild it. The
result was an answer that said a change had been reverted while the decision list in
the same response still called the reverted decision ACTIVE.
"""

from __future__ import annotations

import json

from app.config import Settings
from app.providers.llm_provider import MockLLMProvider
from app.schemas.ask import AskRequest
from app.schemas.common import DecisionState
from app.services.data_source import GraphDataSource
from app.stores.graph_store import InMemoryGraphStore

REPO = "urllib3-urllib3"
ENTITY = "file:urllib3/urllib3:src/urllib3/util/ssl_.py"
ADD_DECISION = "dec_6dee7648b9ef5416"
REVERT_DECISION = "dec_ce303eb845540d38"
ADD_SOURCE = "pr:urllib3/urllib3#3456"
REVERT_SOURCE = "pr:urllib3/urllib3#3466"


def _store() -> InMemoryGraphStore:
    store = InMemoryGraphStore()
    store.merge_node("Repository", {"id": REPO, "repo": REPO, "name": "urllib3"})
    store.merge_node("CodeEntity", {
        "id": ENTITY,
        "repo": REPO,
        "name": "src/urllib3/util/ssl_.py",
        "path": "src/urllib3/util/ssl_.py",
        "entity_type": "File",
    })
    store.merge_node("Decision", {
        "id": ADD_DECISION,
        "repo": REPO,
        "summary": "Add TLS settings required for HTTP/2",
        "rationale": "This PR modifies create_urllib3_context for HTTP/2.",
        "state": "SUPERSEDED",
        "supersedes": [],
        "superseded_by": [REVERT_DECISION],
        "rule": "1_revert_commit",
        "source_id": ADD_SOURCE,
        "source_type": "PullRequest",
        "source_number": 3456,
        "source_url": "https://github.com/urllib3/urllib3/pull/3456",
    })
    store.merge_node("Decision", {
        "id": REVERT_DECISION,
        "repo": REPO,
        "summary": "Revert the HTTP/2 TLS settings",
        "rationale": "curl does not implement the new settings.",
        "state": "ACTIVE",
        "supersedes": [ADD_DECISION],
        "superseded_by": [],
        "rule": "1_revert_commit",
        "source_id": REVERT_SOURCE,
        "source_type": "PullRequest",
        "source_number": 3466,
        "source_url": "https://github.com/urllib3/urllib3/pull/3466",
    })
    for decision_id, source_id, quote in (
        (
            ADD_DECISION,
            ADD_SOURCE,
            "This PR modifies `create_urllib3_context` to add TLS settings required for HTTP/2 as per RFC 9113.",
        ),
        (
            REVERT_DECISION,
            REVERT_SOURCE,
            "Unfortunately, we realized after working on them that we can't really use those new settings. curl also does not implement them.",
        ),
    ):
        evidence_id = f"ev_{decision_id}"
        store.merge_node("Evidence", {
            "id": evidence_id,
            "repo": REPO,
            "decision_id": decision_id,
            "source_id": source_id,
            "source_type": "PullRequest",
            "source_url": f"https://github.com/urllib3/urllib3/pull/{3456 if decision_id == ADD_DECISION else 3466}",
            "quote": quote,
            "quote_verified": True,
        })
        store.source_texts[source_id] = quote
        store.merge_relationship("GOVERNS", decision_id, ENTITY)
        store.merge_relationship("SUPPORTED_BY", decision_id, evidence_id)
    return store


def test_ask_reuses_the_persisted_supersession_state() -> None:
    source = GraphDataSource(
        Settings(_env_file=None, data_source="graph", allow_mock_providers=True, min_score=0.0),
        store=_store(),
    )
    source.provider = MockLLMProvider(canned_response=json.dumps({
        "answer": "The HTTP/2 TLS settings were added and then reverted.",
        "cited_evidence_ids": [f"ev_{ADD_DECISION}", f"ev_{REVERT_DECISION}"],
    }))

    response = source.ask(
        REPO,
        AskRequest(question="Why was HTTP/2 TLS support added and then reverted?", entity_id=ENTITY),
    )

    assert response.outcome == "full", (response.reason_code, response.answer)
    by_id = {decision.id: decision for decision in response.decisions}
    assert by_id[ADD_DECISION].state == DecisionState.SUPERSEDED
    assert by_id[ADD_DECISION].superseded_by == [REVERT_DECISION]
    assert by_id[ADD_DECISION].supersedes == []
    assert by_id[ADD_DECISION].rule == "1_revert_commit"
    assert by_id[REVERT_DECISION].state == DecisionState.ACTIVE
    assert by_id[REVERT_DECISION].supersedes == [ADD_DECISION]
    assert by_id[REVERT_DECISION].superseded_by == []
    assert by_id[REVERT_DECISION].rule == "1_revert_commit"
