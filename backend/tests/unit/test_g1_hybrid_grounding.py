"""Unit tests for G1 Hybrid Semantic + Graph Grounding (Point 1)."""

from __future__ import annotations

from app.config import Settings
from app.providers.embeddings import DeterministicFallbackEmbeddingProvider
from app.services.entity_resolution import (
    ResolutionOutcome,
    classify_domain_scope,
    resolve_entity,
    resolve_entity_from_decisions,
    resolve_question,
)
from app.stores.graph_store import InMemoryGraphStore


def _cfg(**overrides) -> Settings:
    defaults = dict(_env_file=None, offline=True)
    defaults.update(overrides)
    return Settings(**defaults)


def test_semantic_domain_classifier_rejects_general_off_topic_without_hardcoded_regex() -> None:
    emb = DeterministicFallbackEmbeddingProvider()
    for q in (
        "Who won the football world cup championship?",
        "What is the weather forecast for rain today?",
        "Can you recommend a pizza restaurant for lunch?",
        "Why was the team late for the demo?",
    ):
        in_scope, margin = classify_domain_scope(q, embedder=emb, cfg=_cfg())
        assert not in_scope, f"Expected out-of-scope for: {q!r} (margin={margin})"

    for q in (
        "Why does urllib3 use Kubernetes for orchestration?",
        "Why is retry backoff configured with exponential delay?",
        "Why was src/auth/jwt.py refactored?",
    ):
        in_scope, margin = classify_domain_scope(q, embedder=emb, cfg=_cfg())
        assert in_scope, f"Expected in-scope for: {q!r} (margin={margin})"


def test_bm25_idf_and_hybrid_grounding_resolve_conceptual_entity_query() -> None:
    entities = [
        {
            "id": "file:acme/app:src/app/auth/oauth_token.py",
            "name": "src/app/auth/oauth_token.py",
            "path": "src/app/auth/oauth_token.py",
            "entity_type": "File",
            "summary": "OAuth bearer token refresh and rotation",
        },
        {
            "id": "file:acme/app:src/app/db/connection_pool.py",
            "name": "src/app/db/connection_pool.py",
            "path": "src/app/db/connection_pool.py",
            "entity_type": "File",
            "summary": "PostgreSQL connection pool sizing and idle timeout",
        },
        {
            "id": "file:acme/app:src/app/http/client.py",
            "name": "src/app/http/client.py",
            "path": "src/app/http/client.py",
            "entity_type": "File",
            "summary": "Outbound HTTP client",
        },
    ]
    res = resolve_entity(
        "Why does OAuth bearer token refresh rotate credentials?",
        entities,
        repository="acme/app",
        cfg=_cfg(),
    )
    assert res.outcome == ResolutionOutcome.SUCCESS
    assert res.entity is not None
    assert res.entity.path == "src/app/auth/oauth_token.py"
    assert res.grounding_method == "hybrid_semantic"
    assert res.score_margin is not None and res.score_margin >= 0.08
    assert "bm25" in res.entity.signals and "rrf" in res.entity.signals


def test_margin_based_disambiguation_respects_configurable_margin() -> None:
    entities = [
        {"id": "e1", "name": "a/retry.py", "path": "a/retry.py", "entity_type": "File"},
        {"id": "e2", "name": "b/retry.py", "path": "b/retry.py", "entity_type": "File"},
    ]
    res = resolve_entity("Why does retry.py cap backoff?", entities, cfg=_cfg(entity_ambiguity_margin=0.08))
    assert res.outcome == ResolutionOutcome.AMBIGUOUS
    assert res.reason_code == "ambiguous_entity"
    assert res.score_margin == 0.0


def test_module_fallback_resolves_parent_module_when_sibling_files_tie_in_decisions() -> None:
    repo = "acme/payments"
    store = InMemoryGraphStore()
    entities = [
        {
            "id": f"module:{repo}:src/auth",
            "repo": repo,
            "name": "src/auth",
            "path": "src/auth",
            "entity_type": "Module",
        },
        {
            "id": f"file:{repo}:src/auth/jwt.py",
            "repo": repo,
            "name": "src/auth/jwt.py",
            "path": "src/auth/jwt.py",
            "entity_type": "File",
        },
        {
            "id": f"file:{repo}:src/auth/session.py",
            "repo": repo,
            "name": "src/auth/session.py",
            "path": "src/auth/session.py",
            "entity_type": "File",
        },
    ]
    for ent in entities:
        store.merge_node("CodeEntity", ent)

    store.merge_node("Decision", {
        "id": "dec_auth_1",
        "repo": repo,
        "state": "ACTIVE",
        "summary": "Enforce strict zero-trust token expiry across authentication",
        "rationale": "Short token expiry mitigates replay attacks across jwt and session handlers.",
        "source_id": f"pr:{repo}#42",
    })
    store.merge_relationship("GOVERNS", "dec_auth_1", f"file:{repo}:src/auth/jwt.py", {})
    store.merge_relationship("GOVERNS", "dec_auth_1", f"file:{repo}:src/auth/session.py", {})

    res = resolve_question(
        "Why do we enforce strict zero-trust token expiry?",
        entities,
        repo,
        store,
        cfg=_cfg(),
    )
    assert res.outcome == ResolutionOutcome.SUCCESS
    assert res.entity is not None
    assert res.entity.entity_type == "Module"
    assert res.entity.path == "src/auth"
    assert res.grounding_method == "module_fallback"


def test_resolve_entity_from_decisions_uses_weighted_graph_propagation() -> None:
    repo = "acme/net"
    store = InMemoryGraphStore()
    store.merge_node("CodeEntity", {
        "id": f"file:{repo}:src/tls.py", "repo": repo,
        "name": "src/tls.py", "path": "src/tls.py", "entity_type": "File",
    })
    store.merge_node("CodeEntity", {
        "id": f"file:{repo}:src/proxy.py", "repo": repo,
        "name": "src/proxy.py", "path": "src/proxy.py", "entity_type": "File",
    })
    store.merge_node("Decision", {
        "id": "d1", "repo": repo, "state": "ACTIVE",
        "summary": "Pin TLS 1.3 cipher suite for certificate validation",
        "rationale": "Legacy TLS ciphers failed security audit.",
        "source_id": f"pr:{repo}#10",
    })
    store.merge_node("Decision", {
        "id": "d2", "repo": repo, "state": "ACTIVE",
        "summary": "Harden certificate hostname verification",
        "rationale": "Strict hostname verification avoids MITM.",
        "source_id": f"pr:{repo}#11",
    })
    store.merge_relationship("GOVERNS", "d1", f"file:{repo}:src/tls.py", {})
    store.merge_relationship("GOVERNS", "d2", f"file:{repo}:src/tls.py", {})
    store.merge_relationship("GOVERNS", "d1", f"file:{repo}:src/proxy.py", {})

    res = resolve_entity_from_decisions(
        "Why was certificate validation hardened?",
        store,
        repo,
        cfg=_cfg(),
    )
    assert res is not None
    assert res.outcome == ResolutionOutcome.SUCCESS
    assert res.entity is not None
    assert res.entity.path == "src/tls.py"
    assert res.grounding_method == "graph_decision"
