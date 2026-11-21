from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Optional

from app.config import Settings, settings
from app.providers.embeddings import (
    BaseEmbeddingProvider,
    compute_cosine_similarity,
    get_embedding_provider,
)
from app.stores.graph_store import BaseGraphStore

logger = logging.getLogger(__name__)


@dataclass
class RetrievedEvidenceItem:
    id: str
    decision_id: str
    source_id: str
    source_type: str
    source_url: str
    quote: str
    claim: str
    author: Optional[str] = None
    timestamp: Optional[str] = None
    # A record of what was true when the quote was extracted. It is NOT
    # authorisation to cite the quote: the answer path re-verifies against
    # the source text before any citation is built.
    quote_verified: bool = False
    similarity_score: float = 0.0


class EvidenceTier(StrEnum):
    """Granularity tier of retrieved evidence in the multi-hop G2 pipeline."""

    DIRECT = "direct"    # Tier 1: Direct Decision -[:GOVERNS]-> Entity
    MODULE = "module"    # Tier 2: Parent Module / Directory decisions
    SOURCE = "source"    # Tier 3: Raw touching PR / Commit / Document evidence
    NONE = "none"        # No evidence path found across any tier


@dataclass
class EvidenceBundle:
    """Bounded, grounded evidence bundle passed to the refusal gate and LLM answerer."""

    question: str
    resolved_entity: dict[str, Any]
    decisions: list[dict[str, Any]] = field(default_factory=list)
    evidence_items: list[RetrievedEvidenceItem] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    people: list[dict[str, Any]] = field(default_factory=list)
    supersession_chains: list[list[str]] = field(default_factory=list)
    has_contradiction: bool = False
    chain_truncated: bool = False
    best_similarity_score: float = 0.0
    current_value_differs: bool = False
    # source_id -> full stored source text, used to re-verify quotes at answer time.
    source_texts: dict[str, str] = field(default_factory=dict)
    # Multi-hop G2 provenance & continuous sufficiency
    evidence_tier: str = EvidenceTier.DIRECT.value
    evidence_sufficiency: float = 1.0
    fallback_note: Optional[str] = None
    # G4 Two-stage calibrated reranker relevance probability [0.0 .. 1.0]
    calibrated_relevance_score: Optional[float] = None


def _ancestor_directory_paths(path: str) -> list[str]:
    """Return parent directory paths ordered nearest-first (e.g., src/a/b.py -> ['src/a', 'src'])."""
    clean = (path or "").strip("/")
    if "/" not in clean:
        return []
    parts = clean.split("/")[:-1]
    return ["/".join(parts[:i]) for i in range(len(parts), 0, -1)]


def _expand_tier2_module_decisions(
    repo: str,
    entity: dict[str, Any],
    store: BaseGraphStore,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Tier 2 fallback: walk parent module/directory entities for governing decisions."""
    ent_path = str(entity.get("path") or entity.get("name") or "").strip("/")
    ancestors = _ancestor_directory_paths(ent_path)
    if not ancestors:
        return [], None

    for ancestor in ancestors:
        candidates = [
            f"module:{repo}:{ancestor}" if repo else "",
            ancestor,
        ]
        parent_node: Optional[dict[str, Any]] = None
        for cid in candidates:
            if not cid:
                continue
            if hasattr(store, "get_entity"):
                found = store.get_entity(repo, cid)
                if found:
                    parent_node = found
                    break
            if hasattr(store, "get_node"):
                found = store.get_node(cid)
                if found:
                    parent_node = found
                    break
        if parent_node is None:
            continue
        parent_id = str(parent_node.get("id") or "")
        if not parent_id or parent_id == entity.get("id"):
            continue
        parent_decisions = store.get_decisions_for_entity(parent_id)
        if parent_decisions:
            tagged: list[dict[str, Any]] = []
            for d in parent_decisions:
                copy = dict(d)
                copy.setdefault("retrieval_tier", EvidenceTier.MODULE.value)
                copy.setdefault("retrieval_hop_source", ancestor)
                tagged.append(copy)
            return tagged, ancestor

    return [], None


def _expand_tier3_touching_sources(
    repo: str,
    entity: dict[str, Any],
    store: BaseGraphStore,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Tier 3 fallback: synthesize caveated evidence from raw PRs/Commits/Docs touching the entity."""
    entity_id = str(entity.get("id") or "")
    if not entity_id or not hasattr(store, "get_sources_for_entity"):
        return [], {}
    try:
        raw_sources = store.get_sources_for_entity(repo, entity_id)
    except Exception:  # noqa: BLE001
        return [], {}

    synthesized: list[dict[str, Any]] = []
    source_texts: dict[str, str] = {}
    for idx, src in enumerate(raw_sources[:5]):
        src_id = str(src.get("id") or f"src:{idx}")
        title = str(src.get("title") or src.get("subject") or "").strip()
        body = str(src.get("text") or src.get("body") or src.get("message") or src.get("content") or "").strip()
        full_text = f"{title}\n{body}".strip() if title and body and title not in body else (body or title)
        if not full_text:
            continue
        quote = body[:280].strip() if body else title[:280].strip()
        source_texts[src_id] = full_text
        src_type = str(src.get("source_type") or "pull_request").lower()
        src_url = str(src.get("url") or src.get("source_url") or "")
        dec_id = f"tier3_src_{idx}_{src_id}"
        synthesized.append({
            "id": dec_id,
            "repo": repo,
            "summary": title or f"Historical change recorded in {src_id}",
            "rationale": quote,
            "state": "ACTIVE",
            "source_id": src_id,
            "source_url": src_url,
            "retrieval_tier": EvidenceTier.SOURCE.value,
            "evidence": [{
                "id": f"ev_tier3_{idx}",
                "decision_id": dec_id,
                "source_id": src_id,
                "source_type": src_type,
                "source_url": src_url,
                "quote": quote,
                "claim": title or quote,
                "author": src.get("author"),
                "timestamp": src.get("created_at") or src.get("timestamp"),
                "quote_verified": True,
            }],
        })
    return synthesized, source_texts


def _compute_evidence_sufficiency(
    tier: EvidenceTier,
    decision_count: int,
    best_similarity: float,
    cfg: Settings,
) -> float:
    """Compute a continuous [0.0 .. 1.0] evidence sufficiency score."""
    if tier == EvidenceTier.NONE or decision_count <= 0:
        return 0.0
    tier_weight = {
        EvidenceTier.DIRECT: cfg.evidence_tier1_directness,
        EvidenceTier.MODULE: cfg.evidence_tier2_directness,
        EvidenceTier.SOURCE: cfg.evidence_tier3_directness,
    }.get(tier, 0.0)
    volume_bonus = min(0.15, 0.05 * decision_count)
    sim_component = 0.25 * max(0.0, min(1.0, best_similarity))
    return round(max(0.0, min(1.0, 0.60 * tier_weight + sim_component + volume_bonus)), 4)


def retrieve_evidence(
    question: str,
    entity: dict[str, Any],
    store: BaseGraphStore,
    embedder: Optional[BaseEmbeddingProvider] = None,
    max_evidence_items: Optional[int] = None,
    max_chain_length: Optional[int] = None,
    source_text_provider: Optional[Callable[[str], str]] = None,
    cfg: Optional[Settings] = None,
) -> EvidenceBundle:
    """Retrieves decisions, evidence, sources, and supersession chains for a resolved entity.

    Enforces:
    - Bounded graph traversal up to MAX_CHAIN_LENGTH (default 6).
    - Capped evidence items up to MAX_EVIDENCE_ITEMS (default 12).
    - Semantic similarity scored only on candidate decisions in the entity's neighborhood.
    - Contradiction detection (OPPOSES, CONFLICTS_WITH, or UNRESOLVED supersession edges).
    """
    config = cfg or settings
    cap_evidence = max_evidence_items or config.max_evidence_items
    chain_limit = max_chain_length or config.max_chain_length
    emb = embedder or get_embedding_provider(cfg=config)

    entity_id = entity.get("id", "")
    repo = entity.get("repo") or (entity_id.split(":")[1] if ":" in entity_id else "")
    decisions = store.get_decisions_for_entity(entity_id)
    tier = EvidenceTier.DIRECT
    fallback_note: Optional[str] = None
    tier3_texts: dict[str, str] = {}

    if not decisions and config.enable_multihop_fallback:
        module_decisions, parent_dir = _expand_tier2_module_decisions(repo, entity, store)
        if module_decisions:
            decisions = module_decisions
            tier = EvidenceTier.MODULE
            fallback_note = (
                f"No direct decision governs {entity.get('name', entity_id)}; "
                f"retrieved parent module decisions from {parent_dir}."
            )
        else:
            source_decisions, tier3_texts = _expand_tier3_touching_sources(repo, entity, store)
            if source_decisions:
                decisions = source_decisions
                tier = EvidenceTier.SOURCE
                fallback_note = (
                    f"No formal decision node governs {entity.get('name', entity_id)}; "
                    "grounded from raw touching PR/commit history with reduced confidence."
                )

    if not decisions:
        tier = EvidenceTier.NONE

    bundle = EvidenceBundle(
        question=question,
        resolved_entity=entity,
        decisions=decisions,
        evidence_tier=tier.value,
        evidence_sufficiency=0.0 if tier == EvidenceTier.NONE else 1.0,
        fallback_note=fallback_note,
        source_texts=dict(tier3_texts),
    )

    if not decisions:
        return bundle

    # Compute similarity between question and decisions (embed question once!)
    q_vec = emb.embed_text(question)
    best_score = 0.0
    all_evidence: list[RetrievedEvidenceItem] = []

    ent_name = entity.get("name", "")
    decision_texts: list[str] = []
    for d in decisions:
        summary = d.get("summary", "")
        rationale = d.get("rationale", "")
        text_to_compare = f"{ent_name} {summary} {rationale}".strip()
        decision_texts.append(text_to_compare)
        stored_emb = d.get("embedding")
        if isinstance(stored_emb, (list, tuple)) and len(stored_emb) == len(q_vec):
            sim = compute_cosine_similarity(q_vec, stored_emb)
        else:
            d_vec = emb.embed_text(text_to_compare)
            sim = compute_cosine_similarity(q_vec, d_vec)
        d["similarity_score"] = sim
        if sim > best_score:
            best_score = sim

    # Stage 2 (G4): Cross-encoder / calibrated reranker over candidate decisions
    reranker_scores: list[float] = []
    if config.enable_reranker and decision_texts:
        from app.services.reranker import get_reranker

        reranker = get_reranker(cfg=config, embedder=emb)
        reranker_scores = reranker.score_batch(question, decision_texts)
        for d, r_score in zip(decisions, reranker_scores):
            d["reranker_score"] = r_score
        bundle.calibrated_relevance_score = round(max(reranker_scores, default=0.0), 4)

    for idx, d in enumerate(decisions):
        sim = float(d.get("similarity_score", 0.0))
        eff_sim = reranker_scores[idx] if idx < len(reranker_scores) else sim

        # Collect evidence items
        for raw_ev in d.get("evidence", []):
            item = RetrievedEvidenceItem(
                id=raw_ev.get("id", ""),
                decision_id=d.get("id", ""),
                source_id=raw_ev.get("source_id", ""),
                source_type=raw_ev.get("source_type", "pull_request"),
                source_url=raw_ev.get("source_url", ""),
                quote=raw_ev.get("quote", ""),
                claim=raw_ev.get("claim", ""),
                author=raw_ev.get("author"),
                timestamp=raw_ev.get("timestamp"),
                quote_verified=bool(raw_ev.get("quote_verified", True)),
                similarity_score=eff_sim,
            )
            all_evidence.append(item)

        # Contradiction checks
        if d.get("state") == "UNRESOLVED":
            bundle.has_contradiction = True

    bundle.best_similarity_score = round(best_score, 4)
    bundle.evidence_sufficiency = _compute_evidence_sufficiency(
        tier=tier,
        decision_count=len(decisions),
        best_similarity=bundle.best_similarity_score,
        cfg=config,
    )

    # Sort evidence items by similarity descending and cap at max_evidence_items
    all_evidence.sort(key=lambda x: x.similarity_score, reverse=True)
    bundle.evidence_items = all_evidence[:cap_evidence]

    links = []
    if any(not d.get("state") for d in decisions) and hasattr(store, "get_links_for_repo"):
        try:
            links = store.get_links_for_repo(repo)
        except Exception:
            links = []

    # Phase 4: Supersession & State Analysis
    from app.services.state import check_code_differs_from_latest, compute_decision_states
    from app.services.supersession import compute_supersession_edges

    edges = compute_supersession_edges(decisions, links=links)
    analysis = compute_decision_states(decisions, edges=edges, max_chain_length=chain_limit)

    for d in decisions:
        dec_id = d.get("id")
        if dec_id and dec_id in analysis.states:
            st = analysis.states[dec_id]
            # The graph already persists the state computed at build time. Reusing
            # it keeps /ask identical to /decisions/{id} even when retrieval cannot
            # rebuild an edge from the links available to it.
            if not d.get("state"):
                d["state"] = st.state.value
            d.setdefault("supersedes", st.supersedes)
            d.setdefault("superseded_by", st.superseded_by)
            d.setdefault("rule", st.rule)
            d.setdefault("probable_superseded_by", st.probable_superseded_by)
            d.setdefault("conflicts_with", st.conflicts_with)
            d.setdefault("reaffirms", st.reaffirms)

    bundle.supersession_chains = analysis.supersession_chains
    bundle.chain_truncated = analysis.chain_truncated
    bundle.has_contradiction = analysis.has_contradiction or bundle.has_contradiction
    bundle.current_value_differs = any(
        check_code_differs_from_latest(d.get("id", ""), analysis, decisions)
        for d in decisions
    )

    if hasattr(store, "get_people_for_entity"):
        try:
            bundle.people = store.get_people_for_entity(repo, entity_id)
        except Exception:
            bundle.people = []

    # Populate bundle.sources from unique source nodes so who_to_ask can rank reviewers
    if hasattr(store, "get_node"):
        seen_src_ids: set[str] = set()
        for d in decisions:
            sid = str(d.get("source_id") or "")
            if sid and sid not in seen_src_ids:
                seen_src_ids.add(sid)
                try:
                    s_node = store.get_node(sid)
                    if isinstance(s_node, dict):
                        bundle.sources.append(s_node)
                except Exception:
                    pass

    # Load the stored text behind every retained source so the answer path can
    # re-verify quotes instead of trusting the extraction-time flag.
    if source_text_provider is None:
        store_method = getattr(store, "source_text_for", None)
        source_text_provider = store_method if callable(store_method) else None
    if source_text_provider is not None:
        for item in bundle.evidence_items:
            if item.source_id not in bundle.source_texts:
                try:
                    bundle.source_texts[item.source_id] = source_text_provider(item.source_id) or ""
                except Exception:  # noqa: BLE001 - an unreadable source is not fatal here
                    logger.warning(
                        "could not load source text for %s; its quotes cannot be verified",
                        item.source_id,
                    )
                    bundle.source_texts[item.source_id] = ""

    return bundle
