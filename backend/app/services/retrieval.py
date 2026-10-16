from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app.config import Settings, settings
from app.providers.embeddings import BaseEmbeddingProvider, get_embedding_provider
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
    decisions = store.get_decisions_for_entity(entity_id)

    bundle = EvidenceBundle(
        question=question,
        resolved_entity=entity,
        decisions=decisions,
    )

    if not decisions:
        return bundle

    # Compute similarity between question and decisions
    best_score = 0.0
    all_evidence: list[RetrievedEvidenceItem] = []

    ent_name = entity.get("name", "")
    for d in decisions:
        summary = d.get("summary", "")
        rationale = d.get("rationale", "")
        text_to_compare = f"{ent_name} {summary} {rationale}".strip()
        sim = emb.similarity(question, text_to_compare)
        d["similarity_score"] = sim
        if sim > best_score:
            best_score = sim

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
                similarity_score=sim,
            )
            all_evidence.append(item)

        # Contradiction checks
        if d.get("state") == "UNRESOLVED":
            bundle.has_contradiction = True

    bundle.best_similarity_score = round(best_score, 4)

    # Sort evidence items by similarity descending and cap at max_evidence_items
    all_evidence.sort(key=lambda x: x.similarity_score, reverse=True)
    bundle.evidence_items = all_evidence[:cap_evidence]

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
