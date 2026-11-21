"""Unit tests for dynamic confidence signals, scoped people graph,
single-query embedding retrieval, who_to_ask on refusals, and LRU /ask cache.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.config import Settings
from app.providers.embeddings import DeterministicFallbackEmbeddingProvider
from app.providers.llm_provider import MockLLMProvider
from app.schemas.ask import AskRequest
from app.services.answer import (
    provenance_from_citations,
    temporal_consistency_from_bundle,
)
from app.services.data_source import GraphDataSource
from app.services.retrieval import EvidenceBundle, retrieve_evidence
from app.stores.graph_store import InMemoryGraphStore


def test_provenance_from_citations_scales_with_completeness() -> None:
    full = [SimpleNamespace(source_url="https://github.com/a/b/pull/1", author="ann", timestamp="2025-01-01T00:00:00Z")]
    no_ts = [SimpleNamespace(source_url="https://github.com/a/b/pull/1", author="ann", timestamp=None)]
    url_only = [SimpleNamespace(source_url="https://github.com/a/b/pull/1", author=None, timestamp=None)]

    assert provenance_from_citations(full) == 1.0
    assert provenance_from_citations(no_ts) == 0.9
    assert provenance_from_citations(url_only) == 0.8


def test_temporal_consistency_from_bundle_reflects_state_and_truncation() -> None:
    active_bundle = EvidenceBundle(
        question="q",
        resolved_entity={"id": "e1"},
        decisions=[{"id": "d1", "state": "ACTIVE"}],
        chain_truncated=False,
    )
    truncated_bundle = EvidenceBundle(
        question="q",
        resolved_entity={"id": "e1"},
        decisions=[{"id": "d1", "state": "ACTIVE"}],
        chain_truncated=True,
    )
    inactive_bundle = EvidenceBundle(
        question="q",
        resolved_entity={"id": "e1"},
        decisions=[{"id": "d1", "state": "REJECTED"}],
        chain_truncated=False,
    )

    assert temporal_consistency_from_bundle(active_bundle) == 1.0
    assert temporal_consistency_from_bundle(truncated_bundle) == 0.85
    assert temporal_consistency_from_bundle(inactive_bundle) == 0.5


def test_inmemory_get_people_for_entity_is_scoped_by_repo_and_entity() -> None:
    store = InMemoryGraphStore()
    store.merge_node("Person", {"id": "person:alice", "login": "alice", "repo": "owner/a"})
    store.merge_node("Person", {"id": "person:bob", "login": "bob", "repo": "owner/b"})
    store.merge_node("PullRequest", {"id": "pr:owner/a#1", "repo": "owner/a", "created_at": "2026-01-01T00:00:00Z"})
    store.merge_node("PullRequest", {"id": "pr:owner/b#2", "repo": "owner/b", "created_at": "2026-01-01T00:00:00Z"})
    store.merge_node("Decision", {"id": "d1", "repo": "owner/a"})
    store.merge_node("Decision", {"id": "d2", "repo": "owner/b"})
    store.merge_node("CodeEntity", {"id": "file:owner/a:x.py", "repo": "owner/a", "name": "x.py", "path": "x.py"})
    store.merge_node("CodeEntity", {"id": "file:owner/b:y.py", "repo": "owner/b", "name": "y.py", "path": "y.py"})

    store.merge_relationship("AUTHORED", "person:alice", "pr:owner/a#1")
    store.merge_relationship("DECIDED_IN", "d1", "pr:owner/a#1")
    store.merge_relationship("GOVERNS", "d1", "file:owner/a:x.py")

    store.merge_relationship("AUTHORED", "person:bob", "pr:owner/b#2")
    store.merge_relationship("DECIDED_IN", "d2", "pr:owner/b#2")
    store.merge_relationship("GOVERNS", "d2", "file:owner/b:y.py")

    people_a = store.get_people_for_entity("owner/a", "file:owner/a:x.py")
    assert [p["login"] for p in people_a] == ["alice"]


def test_retrieval_uses_stored_embedding_and_populates_sources() -> None:
    emb = DeterministicFallbackEmbeddingProvider()
    store = InMemoryGraphStore()
    ent = {"id": "file:owner/a:ssl.py", "repo": "owner/a", "name": "ssl.py", "path": "ssl.py", "entity_type": "File"}
    store.merge_node("CodeEntity", ent)
    dec_text = "ssl.py Enforce TLS 1.3 for security"
    store.merge_node("Decision", {
        "id": "d1",
        "repo": "owner/a",
        "summary": "Enforce TLS 1.3",
        "rationale": "for security",
        "state": "ACTIVE",
        "source_id": "pr:owner/a#10",
        "embedding": emb.embed_text(dec_text),
    })
    store.merge_node("PullRequest", {
        "id": "pr:owner/a#10",
        "repo": "owner/a",
        "author": "seth",
        "reviewers": [{"login": "quentin", "submittedAt": "2026-01-02T00:00:00Z"}],
    })
    store.merge_relationship("GOVERNS", "d1", ent["id"])

    class CountingEmbedder(DeterministicFallbackEmbeddingProvider):
        calls = 0

        def embed_text(self, text: str) -> list[float]:
            self.calls += 1
            return super().embed_text(text)

    counting = CountingEmbedder()
    bundle = retrieve_evidence("Why enforce TLS 1.3?", ent, store, embedder=counting)
    assert counting.calls == 1, "should embed the question once and reuse stored Decision.embedding"
    assert len(bundle.sources) == 1
    assert bundle.sources[0]["id"] == "pr:owner/a#10"


def test_ask_lru_cache_and_who_to_ask_on_low_score_refusal() -> None:
    emb = DeterministicFallbackEmbeddingProvider()
    store = InMemoryGraphStore()
    repo = "owner-a"
    store.merge_node("Repository", {
        "id": repo,
        "repo": repo,
        "name": "a",
        "full_name": "owner/a",
        "last_rebuilt_at": "2026-11-21T00:00:00Z",
        "decisions_count": 1,
        "entities_count": 1,
        "pull_requests_count": 1,
        "commits_count": 0,
    })
    ent = {
        "id": "file:owner/a:ssl.py",
        "repo": repo,
        "name": "ssl.py",
        "path": "ssl.py",
        "entity_type": "File",
        "decision_count": 1,
    }
    store.merge_node("CodeEntity", ent)
    store.merge_node("PullRequest", {
        "id": "pr:owner/a#10",
        "repo": repo,
        "author": "alice",
        "created_at": "2026-10-01T00:00:00Z",
        "reviewers": [{"login": "bob", "submittedAt": "2026-10-02T00:00:00Z"}],
    })
    store.merge_node("Decision", {
        "id": "d1",
        "repo": repo,
        "summary": "Enforce TLS 1.3",
        "rationale": "for security",
        "state": "ACTIVE",
        "source_id": "pr:owner/a#10",
        "embedding": emb.embed_text("ssl.py Enforce TLS 1.3 for security"),
    })
    store.merge_node("Evidence", {
        "id": "ev1",
        "decision_id": "d1",
        "source_id": "pr:owner/a#10",
        "source_type": "pull_request",
        "source_url": "https://github.com/owner/a/pull/10",
        "quote": "Enforce TLS 1.3 for security.",
        "author": "alice",
        "timestamp": "2026-10-01T00:00:00Z",
        "quote_verified": True,
    })
    store.merge_relationship("GOVERNS", "d1", ent["id"])
    store.merge_relationship("SUPPORTED_BY", "d1", "ev1")
    store.source_texts["pr:owner/a#10"] = "Enforce TLS 1.3 for security."

    ds = GraphDataSource(Settings(_env_file=None, allow_mock_providers=True, min_score=0.99), store=store)
    ds.provider = MockLLMProvider(canned_response=json.dumps({"answer": "ok", "cited_evidence_ids": ["ev1"]}))

    res1 = ds.ask(repo, AskRequest(question="Why was ssl.py changed for bananas?"))
    assert res1.reason_code == "low_score"
    assert len(res1.who_to_ask) >= 1
    assert res1.who_to_ask[0].login == "alice"

    res2 = ds.ask(repo, AskRequest(question="Why was ssl.py changed for bananas?"))
    assert res2 is res1, "second identical ask should hit the per-repo LRU cache"
