from __future__ import annotations

import json

from app.config import Settings
from app.providers.embeddings import DeterministicFallbackEmbeddingProvider
from app.providers.llm_provider import MockLLMProvider
from app.schemas.ask import AskRequest
from app.services.data_source import GraphDataSource
from app.services.entity_resolution import extract_query_tokens
from app.services.retrieval import retrieve_evidence
from app.stores.graph_store import InMemoryGraphStore


def test_polyglot_path_pattern_extracts_ts_go_rs():
    tokens = extract_query_tokens("Why did src/App.tsx and pkg/server.go and src/main.rs change?")
    assert "src/App.tsx" in tokens
    assert "pkg/server.go" in tokens
    assert "src/main.rs" in tokens


def test_retrieve_evidence_embeds_question_once_and_skips_links_when_state_present():
    emb = DeterministicFallbackEmbeddingProvider()
    calls = {"embed": 0, "links": 0}
    orig_embed = emb.embed_text

    def counted_embed(text: str):
        calls["embed"] += 1
        return orig_embed(text)

    emb.embed_text = counted_embed  # type: ignore[method-assign]

    store = InMemoryGraphStore()
    store.merge_node("CodeEntity", {
        "id": "file:acme/app:src/retry.py", "repo": "acme-app", "name": "src/retry.py",
        "path": "src/retry.py", "entity_type": "File",
    })
    store.merge_node("Decision", {
        "id": "dec_1", "repo": "acme-app", "summary": "Pin retry budget",
        "rationale": "Avoid timeouts", "state": "ACTIVE", "source_id": "pr:acme/app#1",
        "embedding": orig_embed("src/retry.py Pin retry budget Avoid timeouts"),
    })
    store.merge_relationship("GOVERNS", "dec_1", "file:acme/app:src/retry.py")

    def spy_links(_repo: str):
        calls["links"] += 1
        return []

    store.get_links_for_repo = spy_links  # type: ignore[method-assign]

    bundle = retrieve_evidence(
        question="Why pin retry budget?",
        entity={"id": "file:acme/app:src/retry.py", "name": "src/retry.py", "repo": "acme-app"},
        store=store,
        embedder=emb,
    )
    assert calls["embed"] == 1
    assert calls["links"] == 0
    assert bundle.best_similarity_score > 0.0


def test_ask_lru_cache_hits_and_invalidates_on_rebuild():
    store = InMemoryGraphStore()
    store.merge_node("Repository", {
        "id": "acme-app", "repo": "acme-app", "name": "app", "full_name": "acme/app",
        "last_rebuilt_at": "2026-11-21T10:00:00Z",
    })
    store.merge_node("CodeEntity", {
        "id": "file:acme/app:src/retry.py", "repo": "acme-app", "name": "src/retry.py",
        "path": "src/retry.py", "entity_type": "File",
    })
    store.merge_node("PullRequest", {
        "id": "pr:acme/app#1", "repo": "acme-app", "number": 1,
        "text": "Mobile clients kept timing out on flaky networks.",
    })
    store.merge_node("Decision", {
        "id": "dec_1", "repo": "acme-app", "summary": "Raise retry budget",
        "rationale": "Mobile clients kept timing out on flaky networks.",
        "state": "ACTIVE", "source_id": "pr:acme/app#1",
    })
    store.merge_node("Evidence", {
        "id": "ev_1", "repo": "acme-app", "decision_id": "dec_1",
        "source_id": "pr:acme/app#1", "source_type": "PullRequest",
        "source_url": "https://github.com/acme/app/pull/1",
        "quote": "Mobile clients kept timing out on flaky networks.",
        "claim": "Timeout rationale", "quote_verified": True,
    })
    store.merge_relationship("GOVERNS", "dec_1", "file:acme/app:src/retry.py")
    store.merge_relationship("SUPPORTED_BY", "dec_1", "ev_1")

    ds = GraphDataSource(cfg=Settings(_env_file=None, offline=True, min_score=0.0), store=store)
    canned = json.dumps({"answer": "Retry budget was raised due to mobile timeouts.", "cited_evidence_ids": ["ev_1"]})
    ds.provider = MockLLMProvider(canned_response=canned)

    req = AskRequest(question="Why was src/retry.py changed?", entity_id="file:acme/app:src/retry.py")
    r1 = ds.ask("acme-app", req)
    r2 = ds.ask("acme-app", req)
    assert len(ds.provider.call_history) == 1
    assert r1.answer == r2.answer

    # Rebuild updates last_rebuilt_at -> cache auto-invalidates
    store.merge_node("Repository", {
        "id": "acme-app", "repo": "acme-app", "name": "app", "full_name": "acme/app",
        "last_rebuilt_at": "2026-11-21T11:00:00Z",
    })
    ds.ask("acme-app", req)
    assert len(ds.provider.call_history) == 2
