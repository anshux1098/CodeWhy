"""A refusal says what was checked, never that no history exists.

The rebuild stores coverage counts on the graph (see
`backend/app/services/coverage.py`). These pin the wording the answer path builds
from those stored facts, and that a refusal still makes no model call.
"""

from __future__ import annotations

from app.config import Settings
from app.schemas.ask import AskRequest
from app.schemas.common import Outcome
from app.services.data_source import GraphDataSource
from app.stores.graph_store import InMemoryGraphStore

REPO = "acme/netclient"
SSL = "file:acme/netclient:src/netclient/ssl_.py"
SCOPE = "acme/netclient at branch main, commits 2024-01-01..2024-02-01, 12 ingested file paths"


def _source(store: InMemoryGraphStore) -> GraphDataSource:
    cfg = Settings(_env_file=None, data_source="graph", allow_mock_providers=True, offline=True)
    return GraphDataSource(cfg, store=store)


class _SpyProvider:
    is_real = False

    def complete_structured(self, *args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("a refusal must not call the model")


def _store(*, touching: int, analyzed: int, noise: int, scope: str | None = SCOPE) -> InMemoryGraphStore:
    store = InMemoryGraphStore()
    repo: dict = {"id": REPO, "repo": REPO, "name": "netclient"}
    if scope is not None:
        repo["scope"] = scope
    store.merge_node("Repository", repo)
    store.merge_node("CodeEntity", {
        "id": SSL, "repo": REPO, "name": "src/netclient/ssl_.py",
        "path": "src/netclient/ssl_.py", "entity_type": "File",
        "prs_touching": touching, "prs_analyzed": analyzed,
        "prs_noise_skipped": noise, "prs_not_analyzed": touching - analyzed - noise,
        "verified_decisions": 0,
    })
    return store


def _refusal(store: InMemoryGraphStore, question: str) -> object:
    source = _source(store)
    source.provider = _SpyProvider()
    return source.ask(REPO, AskRequest(question=question, entity_id=SSL))


def test_a_file_with_analyzed_prs_says_so() -> None:
    response = _refusal(_store(touching=4, analyzed=3, noise=1), "Why was this SSL file changed?")
    assert response.outcome == Outcome.REFUSAL
    assert response.reason_code == "no_decision_path"
    assert response.evidence_gaps == [
        "3 of 4 PRs touching this file were analyzed (1 skipped as noise); "
        "no verified decision was found."
    ]


def test_a_file_touched_but_not_analyzed_says_so() -> None:
    response = _refusal(_store(touching=2, analyzed=0, noise=0), "Why was this SSL file changed?")
    assert response.reason_code == "no_decision_path"
    assert response.evidence_gaps == ["This file is touched by 2 PRs but none were analyzed yet."]


def test_a_file_nothing_touches_says_so() -> None:
    response = _refusal(_store(touching=0, analyzed=0, noise=0), "Why was this SSL file changed?")
    assert response.reason_code == "no_decision_path"
    assert response.evidence_gaps == ["No PR in the ingested history touches this file."]


def test_no_refusal_claims_that_no_history_exists() -> None:
    for touching, analyzed, noise in ((4, 3, 1), (2, 0, 0), (0, 0, 0)):
        response = _refusal(
            _store(touching=touching, analyzed=analyzed, noise=noise),
            "Why was this SSL file changed?",
        )
        joined = " ".join(response.evidence_gaps).lower()
        assert "no history" not in joined
        assert response.evidence_gaps


def test_an_unknown_file_reports_the_scope_that_was_searched() -> None:
    store = _store(touching=0, analyzed=0, noise=0)
    source = _source(store)
    source.provider = _SpyProvider()
    response = source.ask(REPO, AskRequest(question="Why was src/netclient/missing.py changed?"))
    assert response.reason_code == "entity_not_found"
    assert response.evidence_gaps == [
        f"This system covers {SCOPE}; no matching file was found."
    ]


def test_an_unknown_file_without_stored_scope_still_refuses_cleanly() -> None:
    store = _store(touching=0, analyzed=0, noise=0, scope=None)
    source = _source(store)
    source.provider = _SpyProvider()
    response = source.ask(REPO, AskRequest(question="Why was src/netclient/missing.py changed?"))
    assert response.reason_code == "entity_not_found"
    assert response.evidence_gaps
    assert "no history" not in " ".join(response.evidence_gaps).lower()
