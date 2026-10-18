"""An answer on a partly-checked file says how many PRs were not analyzed.

The note is added to `evidence_gaps` only. It must not change the outcome, the
confidence, or the answer text.
"""

from __future__ import annotations

import json

from app.providers.llm_provider import MockLLMProvider
from app.schemas.ask import AskRequest
from app.schemas.common import Outcome
from app.stores.graph_store import InMemoryGraphStore
from backend.tests.unit.test_ask_from_decisions import (
    REPO,
    SSL,
    _source,
    _store_with_evidence,
)

NOTE = "2 of 5 PRs touching this file were not analyzed."
QUESTION = "Why was HTTP/2 TLS support added and then reverted?"


def _store(*, not_analyzed: int) -> InMemoryGraphStore:
    store = _store_with_evidence()
    store.merge_node("CodeEntity", {
        "id": SSL, "repo": REPO, "name": "src/netclient/ssl_.py",
        "path": "src/netclient/ssl_.py", "entity_type": "File",
        "prs_touching": 5, "prs_analyzed": 3, "prs_noise_skipped": 5 - 3 - not_analyzed,
        "prs_not_analyzed": not_analyzed, "verified_decisions": 3,
    })
    return store


def _ask(*, not_analyzed: int):
    source = _source(_store(not_analyzed=not_analyzed))
    source.provider = MockLLMProvider(canned_response=json.dumps({
        "answer": "TLS support was added for HTTP/2 in #3456 and reverted in #3466.",
        "cited_evidence_ids": ["ev_add", "ev_revert"],
    }))
    return source.ask(REPO, AskRequest(question=QUESTION))


def test_a_partly_checked_file_carries_the_not_analyzed_note() -> None:
    response = _ask(not_analyzed=2)
    assert response.outcome == Outcome.FULL
    assert NOTE in response.evidence_gaps


def test_the_note_is_absent_when_every_touching_pr_was_analyzed_or_noise_skipped() -> None:
    response = _ask(not_analyzed=0)
    assert response.outcome == Outcome.FULL
    assert response.evidence_gaps == []


def test_the_note_does_not_change_the_answer_or_confidence() -> None:
    response = _ask(not_analyzed=2)
    assert response.answer == "TLS support was added for HTTP/2 in #3456 and reverted in #3466."
    assert response.confidence is not None
