from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Optional, Sequence

from app.config import Settings, settings
from app.providers.embeddings import (
    BaseEmbeddingProvider,
    DeterministicFallbackEmbeddingProvider,
    compute_cosine_similarity,
    get_embedding_provider,
)


class ResolutionOutcome(StrEnum):
    SUCCESS = "success"
    AMBIGUOUS = "ambiguous"
    REFUSAL = "refusal"


@dataclass(frozen=True)
class EntityCandidate:
    id: str
    name: str
    path: str
    entity_type: str
    score: float
    signals: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolutionResult:
    outcome: ResolutionOutcome
    entity: Optional[EntityCandidate] = None
    candidates: list[EntityCandidate] = field(default_factory=list)
    reason_code: Optional[str] = None
    error_message: Optional[str] = None
    grounding_method: Optional[str] = None
    score_margin: Optional[float] = None


@dataclass(frozen=True)
class EntityResolutionConfig:
    """Configurable policy parameters for G1 Hybrid Entity Grounding."""

    ambiguity_margin: float = 0.08
    min_grounding_score: float = 0.35
    rrf_k: int = 60
    enable_semantic_grounding: bool = True

    @classmethod
    def from_settings(cls, cfg: Optional[Settings] = None) -> EntityResolutionConfig:
        c = cfg or settings
        return cls(
            ambiguity_margin=c.entity_ambiguity_margin,
            min_grounding_score=c.entity_min_grounding_score,
            rrf_k=c.entity_rrf_k,
            enable_semantic_grounding=c.entity_enable_semantic_grounding,
        )


# ---------------------------------------------------------------------------
# Code-reference syntax extractors (structural anchors, not domain hardcoding)
# ---------------------------------------------------------------------------

PATH_PATTERN = re.compile(
    r"[\w./-]+\.(?:py|tsx|ts|jsx|js|mjs|cjs|go|rs|java|kt|cpp|cc|c|hpp|h|cs|rb|php|sh|sql|env|cfg|ini|json|yaml|yml|toml|md|rst|txt)"
)
UPPER_CONST_PATTERN = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")
DOTTED_PATTERN = re.compile(r"\b[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w+)+\b")
QUOTED_PATTERN = re.compile(r"['\"]([a-zA-Z0-9_./-]+)['\"]")
_CAMEL_SPLIT = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

#: A structural score at or above this is an explicit reference (exact path, basename, or name).
STRONG_MATCH = 0.85

#: Legacy minimum partial threshold kept for backward compatibility.
PARTIAL_MATCH = 0.70

_STOPWORDS: frozenset[str] = frozenset(
    {
        "why", "how", "what", "when", "where", "which", "who", "does", "did", "was",
        "were", "are", "the", "and", "for", "with", "into", "from", "this", "that",
        "these", "those", "about", "have", "has", "had", "been", "still", "like",
        "code", "repo", "make", "made", "team", "time", "test", "work", "use", "used",
        "using", "add", "added", "remove", "removed", "revert", "reverted", "change",
        "changed", "changes", "support", "will", "would", "should", "could",
    }
)

# ---------------------------------------------------------------------------
# Semantic Domain Scope Classifier (replaces hardcoded OUT_OF_SCOPE_PATTERNS)
# ---------------------------------------------------------------------------

_IN_DOMAIN_PROTOTYPES: tuple[str, ...] = (
    "software architecture design decision rationale codebase repository module file",
    "pull request commit diff refactor bug fix revert regression incident postmortem",
    "configuration constant timeout retry backoff connection pool cache rate limit",
    "http https tls ssl certificate encryption authentication authorization token oauth",
    "database query schema migration index transaction latency performance memory thread",
    "api endpoint route middleware serialization validation dependency package version",
    "kubernetes docker container orchestration deployment pipeline build ci testing logging",
)

_OUT_OF_DOMAIN_PROTOTYPES: tuple[str, ...] = (
    "weather forecast rain snow temperature sunny climate umbrella outside today",
    "food pizza lunch dinner breakfast restaurant coffee recipe cook order meal",
    "team late meeting standup party demo late schedule calendar holiday vacation",
    "sports football soccer basketball cricket tennis match score world cup championship",
    "movie film music song celebrity gossip entertainment tv show concert ticket",
    "flight hotel travel booking airport passport tourist beach road trip",
)


def _resolve_embedder(
    embedder: Optional[BaseEmbeddingProvider] = None,
    cfg: Optional[Settings] = None,
) -> BaseEmbeddingProvider:
    if embedder is not None:
        return embedder
    config = cfg or settings
    if config.offline:
        return DeterministicFallbackEmbeddingProvider(dimensions=config.embedding_dimensions)
    return get_embedding_provider(cfg=config)


def classify_domain_scope(
    question: str,
    *,
    embedder: Optional[BaseEmbeddingProvider] = None,
    cfg: Optional[Settings] = None,
) -> tuple[bool, float]:
    """Classify whether a question is in-scope for software repository reasoning."""
    q = (question or "").strip()
    if not q:
        return False, -1.0

    if (
        PATH_PATTERN.search(q)
        or UPPER_CONST_PATTERN.search(q)
        or DOTTED_PATTERN.search(q)
        or QUOTED_PATTERN.search(q)
    ):
        return True, 1.0

    emb = _resolve_embedder(embedder, cfg)
    q_vec = emb.embed_text(q)

    in_scores = [compute_cosine_similarity(q_vec, emb.embed_text(p)) for p in _IN_DOMAIN_PROTOTYPES]
    out_scores = [compute_cosine_similarity(q_vec, emb.embed_text(p)) for p in _OUT_OF_DOMAIN_PROTOTYPES]

    best_in = max(in_scores, default=0.0)
    best_out = max(out_scores, default=0.0)
    margin = best_in - best_out

    min_out_signal = 0.08 if isinstance(emb, DeterministicFallbackEmbeddingProvider) else 0.28
    if best_out >= min_out_signal and best_out > best_in:
        return False, round(margin, 4)

    return True, round(margin, 4)


def is_out_of_scope(
    question: str,
    *,
    embedder: Optional[BaseEmbeddingProvider] = None,
    cfg: Optional[Settings] = None,
) -> bool:
    """Checks if a natural language question is unrelated to repository code."""
    in_scope, _ = classify_domain_scope(question, embedder=embedder, cfg=cfg)
    return not in_scope


# ---------------------------------------------------------------------------
# Tokenization & Structural Helpers
# ---------------------------------------------------------------------------

def extract_query_tokens(question: str) -> set[str]:
    """Extract candidate entity identifiers from question text."""
    tokens: set[str] = set()

    for m in PATH_PATTERN.finditer(question):
        tokens.add(m.group(0))

    for m in UPPER_CONST_PATTERN.finditer(question):
        tokens.add(m.group(0))

    for m in DOTTED_PATTERN.finditer(question):
        tokens.add(m.group(0))

    for m in QUOTED_PATTERN.finditer(question):
        tokens.add(m.group(1))

    words = re.findall(r"\b[a-zA-Z0-9_]{3,}\b", question)
    common_stops = {
        "why", "how", "what", "when", "where", "which", "does", "change",
        "changed", "often", "still", "like", "this", "code", "repo", "make",
        "team", "time", "test", "work", "from", "with", "into", "been",
        "have", "more", "also", "some", "that", "than", "then", "were",
    }
    for w in words:
        if w.lower() not in common_stops:
            tokens.add(w)

    return tokens


def _tokenize_identifier(text: str) -> list[str]:
    """Split paths, snake_case, kebab-case, and camelCase into lowercase terms."""
    parts = re.split(r"[/\\._\-:\s]+", text or "")
    out: list[str] = []
    for part in parts:
        if not part:
            continue
        for sub in _CAMEL_SPLIT.sub(" ", part).split():
            low = sub.lower()
            if len(low) >= 2 and low not in _STOPWORDS:
                out.append(low)
    return out


def _is_pyi_stub(entity: dict[str, Any]) -> bool:
    """A type stub is not a separate entity from the module it describes."""
    for key in ("path", "name"):
        if str(entity.get(key, "")).endswith(".pyi"):
            return True
    return False


def _repository_tokens(repository: str) -> set[str]:
    """Tokens that come from the repository name and name no entity."""
    text = str(repository or "").strip().lower()
    if not text:
        return set()
    tokens = {text}
    tokens.update(part for part in re.split(r"[/\-_.]", text) if part)
    return tokens


def _distinct_ids(candidates: Sequence[EntityCandidate]) -> set[str]:
    return {candidate.id for candidate in candidates}


def names_an_explicit_path_or_quote(question: str) -> bool:
    """Whether the question names an explicit file path or quoted identifier."""
    return bool(PATH_PATTERN.search(question) or QUOTED_PATTERN.search(question))


def _explicit_symbol_tokens(question: str) -> set[str]:
    """Explicit paths, quoted identifiers, or ALL_CAPS constants named in the question."""
    explicit: set[str] = set()
    for m in PATH_PATTERN.finditer(question):
        explicit.add(m.group(0))
    for m in QUOTED_PATTERN.finditer(question):
        explicit.add(m.group(1))
    for m in UPPER_CONST_PATTERN.finditer(question):
        tok = m.group(0)
        if "_" in tok or len(tok) >= 6:
            explicit.add(tok)
    return explicit


def _drop_redundant_tokens(tokens: set[str]) -> set[str]:
    """Drop tokens that are contained in a longer token."""
    kept = set(tokens)
    for token in list(tokens):
        if any(other != token and token in other for other in tokens):
            kept.discard(token)
    return kept


def _significant_words(question: str) -> list[str]:
    """Lower-cased words from a question that could name a decision's subject."""
    words: list[str] = []
    for word in re.findall(r"[a-zA-Z0-9_]{3,}", question):
        low = word.lower()
        if low in _STOPWORDS or low in words:
            continue
        words.append(low)
    return words


# ---------------------------------------------------------------------------
# Signal 1: Structural Identifier Matching
# ---------------------------------------------------------------------------

def score_entity_match(query_tokens: set[str], entity: dict[str, Any]) -> float:
    """Computes structural similarity score [0.0 .. 1.0] between extracted tokens and an entity."""
    name = entity.get("name", "")
    path = entity.get("path", "")
    ident = entity.get("id", "")

    for tok in query_tokens:
        if tok == name or tok == path or tok == ident:
            return 1.0

    basename = path.split("/")[-1] if "/" in path else path
    is_file = entity.get("entity_type") in ("File", "Module") or "/" in name
    for tok in query_tokens:
        if tok == basename:
            return 0.90 if is_file else 0.75

    for tok in query_tokens:
        if tok.lower() == name.lower():
            return 0.85

    best_partial = 0.0
    for tok in query_tokens:
        tok_low = tok.lower()
        if tok_low in name.lower():
            best_partial = max(best_partial, 0.70)
        elif tok_low in basename.lower():
            best_partial = max(best_partial, 0.65)

    return best_partial


# ---------------------------------------------------------------------------
# Signal 2: BM25 Lexical Scoring over Entity Identifiers (IDF-weighted)
# ---------------------------------------------------------------------------

def _score_entities_bm25(
    query_terms: Sequence[str],
    entities: Sequence[dict[str, Any]],
    repo_tokens: set[str],
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> dict[str, float]:
    """Compute normalized BM25 scores [0.0 .. 1.0] across entity names and paths."""
    filtered_query = [t for t in query_terms if t not in repo_tokens]
    if not filtered_query or not entities:
        return {}

    docs: list[tuple[str, list[str]]] = []
    df: Counter[str] = Counter()
    for ent in entities:
        eid = str(ent.get("id") or ent.get("name") or "")
        doc_terms = [
            t
            for t in _tokenize_identifier(
                f"{ent.get('name', '')} {ent.get('path', '')} {ent.get('summary', '')}"
            )
            if t not in repo_tokens
        ]
        docs.append((eid, doc_terms))
        for term in set(doc_terms):
            df[term] += 1

    n_docs = len(docs)
    avgdl = sum(len(terms) for _, terms in docs) / max(n_docs, 1)

    raw_scores: dict[str, float] = {}
    for eid, doc_terms in docs:
        if not doc_terms:
            continue
        tf = Counter(doc_terms)
        dl = len(doc_terms)
        score = 0.0
        for q_term in filtered_query:
            freq = tf.get(q_term, 0)
            if freq == 0:
                continue
            doc_freq = df.get(q_term, 0)
            if n_docs > 2 and (doc_freq / n_docs) > 0.75:
                continue
            idf = math.log((n_docs - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0)
            denom = freq + k1 * (1.0 - b + b * (dl / max(avgdl, 1.0)))
            score += idf * (freq * (k1 + 1.0)) / max(denom, 1e-6)
        if score > 0.0:
            raw_scores[eid] = score

    if not raw_scores:
        return {}
    max_s = max(raw_scores.values())
    if max_s <= 0.0:
        return {}
    return {eid: round(val / max_s, 4) for eid, val in raw_scores.items()}


# ---------------------------------------------------------------------------
# Signal 3: Dense Semantic Similarity over Entity Descriptors
# ---------------------------------------------------------------------------

def _score_entities_semantic(
    question: str,
    entities: Sequence[dict[str, Any]],
    embedder: BaseEmbeddingProvider,
    repo_tokens: set[str],
) -> dict[str, float]:
    """Compute cosine similarity between the question and each entity descriptor."""
    if not entities:
        return {}
    q_vec = embedder.embed_text(question)
    scores: dict[str, float] = {}
    is_fallback = isinstance(embedder, DeterministicFallbackEmbeddingProvider)
    floor = 0.20 if is_fallback else 0.30

    for ent in entities:
        eid = str(ent.get("id") or ent.get("name") or "")
        stored_vec = ent.get("embedding")
        if isinstance(stored_vec, (list, tuple)) and len(stored_vec) == len(q_vec) and len(q_vec) > 0:
            sim = compute_cosine_similarity(q_vec, stored_vec)
        else:
            desc_tokens = [
                t
                for t in _tokenize_identifier(
                    f"{ent.get('name', '')} {ent.get('path', '')} {ent.get('summary', '')}"
                )
                if t not in repo_tokens
            ]
            if not desc_tokens:
                continue
            sim = compute_cosine_similarity(q_vec, embedder.embed_text(" ".join(desc_tokens)))
        if sim >= floor:
            scores[eid] = round(float(sim), 4)
    return scores


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion (RRF) & Margin-Based Disambiguation
# ---------------------------------------------------------------------------

def _fuse_rrf(
    channel_scores: dict[str, dict[str, float]],
    channel_weights: dict[str, float],
    k: int = 60,
) -> dict[str, float]:
    """Fuse multiple ranked signal channels using weighted Reciprocal Rank Fusion."""
    fused: dict[str, float] = {}
    max_possible = sum(w / (k + 1) for name, w in channel_weights.items() if channel_scores.get(name))
    if max_possible <= 0.0:
        return {}

    for channel, scores in channel_scores.items():
        if not scores:
            continue
        weight = channel_weights.get(channel, 1.0)
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        for rank, (eid, _val) in enumerate(ranked, start=1):
            fused[eid] = fused.get(eid, 0.0) + weight / (k + rank)

    return {eid: round(val / max_possible, 4) for eid, val in fused.items()}


def _decide_by_margin(
    candidates: Sequence[EntityCandidate],
    *,
    margin: float,
    grounding_method: str,
    ambiguity_message: str = "Question matches multiple code entities. Please select one.",
) -> ResolutionResult:
    """Resolve top candidate if it beats #2 by at least ``margin``; otherwise AMBIGUOUS."""
    if not candidates:
        return ResolutionResult(
            outcome=ResolutionOutcome.REFUSAL,
            reason_code="entity_not_found",
            error_message="No matching code entity was found in the repository.",
        )

    ordered = sorted(candidates, key=lambda c: c.score, reverse=True)
    deduped: list[EntityCandidate] = []
    seen: set[str] = set()
    for c in ordered:
        if c.id not in seen:
            seen.add(c.id)
            deduped.append(c)

    if len(deduped) == 1:
        return ResolutionResult(
            outcome=ResolutionOutcome.SUCCESS,
            entity=deduped[0],
            grounding_method=grounding_method,
            score_margin=round(deduped[0].score, 4),
        )

    best = deduped[0]
    gap = round(best.score - deduped[1].score, 4)
    if gap >= margin:
        return ResolutionResult(
            outcome=ResolutionOutcome.SUCCESS,
            entity=best,
            grounding_method=grounding_method,
            score_margin=gap,
        )

    competing = [c for c in deduped if (best.score - c.score) < margin]
    return ResolutionResult(
        outcome=ResolutionOutcome.AMBIGUOUS,
        candidates=competing,
        reason_code="ambiguous_entity",
        error_message=ambiguity_message,
        grounding_method=grounding_method,
        score_margin=gap,
    )


# ---------------------------------------------------------------------------
# Public Entrypoint 1: Hybrid Entity Grounding (Structural + BM25 + Semantic)
# ---------------------------------------------------------------------------

def resolve_entity(
    question: str,
    available_entities: Sequence[dict[str, Any]],
    repository: str = "",
    *,
    embedder: Optional[BaseEmbeddingProvider] = None,
    cfg: Optional[Settings] = None,
) -> ResolutionResult:
    """Resolve an entity using Hybrid Semantic + Structural + BM25 Grounding."""
    policy = EntityResolutionConfig.from_settings(cfg)
    emb = _resolve_embedder(embedder, cfg)

    if is_out_of_scope(question, embedder=emb, cfg=cfg):
        return ResolutionResult(
            outcome=ResolutionOutcome.REFUSAL,
            reason_code="out_of_scope",
            error_message="Question is not about a repository code entity, file, or configuration.",
        )

    repo_tokens = _repository_tokens(repository)
    tokens = _drop_redundant_tokens(extract_query_tokens(question) - repo_tokens)
    if not tokens:
        return ResolutionResult(
            outcome=ResolutionOutcome.REFUSAL,
            reason_code="entity_not_found",
            error_message="No code entity could be identified in the question.",
        )

    clean_entities = [ent for ent in available_entities if not _is_pyi_stub(ent)]
    if not clean_entities:
        return ResolutionResult(
            outcome=ResolutionOutcome.REFUSAL,
            reason_code="entity_not_found",
            error_message="No matching code entity was found in the repository.",
        )

    entity_by_id: dict[str, dict[str, Any]] = {}
    structural_scores: dict[str, float] = {}
    for ent in clean_entities:
        eid = str(ent.get("id") or ent.get("name") or "")
        entity_by_id[eid] = ent
        s = score_entity_match(tokens, ent)
        if s > 0.0:
            structural_scores[eid] = s

    explicit_symbols = _explicit_symbol_tokens(question)
    if explicit_symbols:
        strong_structural = {eid: s for eid, s in structural_scores.items() if s >= STRONG_MATCH}
        if not strong_structural:
            return ResolutionResult(
                outcome=ResolutionOutcome.REFUSAL,
                reason_code="entity_not_found",
                error_message="No matching code entity was found in the repository.",
            )

    strong = {eid: s for eid, s in structural_scores.items() if s >= STRONG_MATCH}
    if strong:
        strong_candidates = [
            EntityCandidate(
                id=eid,
                name=str(entity_by_id[eid].get("name", "")),
                path=str(entity_by_id[eid].get("path", "")),
                entity_type=str(entity_by_id[eid].get("entity_type", "File")),
                score=score,
                signals={"structural": score},
            )
            for eid, score in strong.items()
        ]
        return _decide_by_margin(
            strong_candidates,
            margin=policy.ambiguity_margin,
            grounding_method="structural",
        )

    query_terms = _tokenize_identifier(question)
    bm25_scores = _score_entities_bm25(query_terms, clean_entities, repo_tokens)

    semantic_scores: dict[str, float] = {}
    if policy.enable_semantic_grounding:
        semantic_scores = _score_entities_semantic(question, clean_entities, emb, repo_tokens)

    candidate_ids = set(structural_scores) | set(bm25_scores) | set(semantic_scores)
    if not candidate_ids:
        return ResolutionResult(
            outcome=ResolutionOutcome.REFUSAL,
            reason_code="entity_not_found",
            error_message="No matching code entity was found in the repository.",
        )

    rrf_scores = _fuse_rrf(
        channel_scores={
            "structural": structural_scores,
            "bm25": bm25_scores,
            "semantic": semantic_scores,
        },
        channel_weights={"structural": 1.5, "bm25": 1.2, "semantic": 1.0},
        k=policy.rrf_k,
    )

    hybrid_candidates: list[EntityCandidate] = []
    for eid in candidate_ids:
        s_struct = structural_scores.get(eid, 0.0)
        s_bm25 = bm25_scores.get(eid, 0.0)
        s_sem = semantic_scores.get(eid, 0.0)
        s_rrf = rrf_scores.get(eid, 0.0)

        blended = round(
            0.40 * max(s_struct, s_bm25) + 0.30 * s_sem + 0.30 * s_rrf,
            4,
        )
        if blended < policy.min_grounding_score:
            continue
        ent = entity_by_id[eid]
        hybrid_candidates.append(
            EntityCandidate(
                id=eid,
                name=str(ent.get("name", "")),
                path=str(ent.get("path", "")),
                entity_type=str(ent.get("entity_type", "File")),
                score=blended,
                signals={
                    "structural": round(s_struct, 4),
                    "bm25": round(s_bm25, 4),
                    "semantic": round(s_sem, 4),
                    "rrf": round(s_rrf, 4),
                },
            )
        )

    if not hybrid_candidates:
        return ResolutionResult(
            outcome=ResolutionOutcome.REFUSAL,
            reason_code="entity_not_found",
            error_message="No code entity matched with sufficient confidence.",
        )

    return _decide_by_margin(
        hybrid_candidates,
        margin=policy.ambiguity_margin,
        grounding_method="hybrid_semantic",
    )


# ---------------------------------------------------------------------------
# Signal 4: Graph Decision-Neighborhood Grounding + Module Fallback
# ---------------------------------------------------------------------------

def _find_common_parent_module(
    candidates: Sequence[EntityCandidate],
    available_entities: Optional[Sequence[dict[str, Any]]],
) -> Optional[EntityCandidate]:
    """If competing file candidates share a parent Module entity in the graph, return it."""
    if not available_entities or len(candidates) < 2:
        return None

    dirs: set[str] = set()
    for c in candidates:
        path = (c.path or c.name or "").strip("/")
        if "/" not in path:
            return None
        dirs.add(path.rsplit("/", 1)[0])

    if len(dirs) != 1:
        return None
    common_dir = next(iter(dirs))

    for ent in available_entities:
        if str(ent.get("entity_type", "")).lower() != "module":
            continue
        ent_path = str(ent.get("path") or ent.get("name") or "").strip("/")
        if ent_path == common_dir or ent_path.endswith(f"/{common_dir}"):
            avg_score = round(sum(c.score for c in candidates) / len(candidates), 4)
            return EntityCandidate(
                id=str(ent.get("id") or ent.get("name") or ""),
                name=str(ent.get("name", "")),
                path=str(ent.get("path", ent.get("name", ""))),
                entity_type="Module",
                score=avg_score,
                signals={"module_fallback": 1.0},
            )
    return None


def resolve_entity_from_decisions(
    question: str,
    store: Any,
    repo: str,
    limit: int = 8,
    *,
    entities: Optional[Sequence[dict[str, Any]]] = None,
    embedder: Optional[BaseEmbeddingProvider] = None,
    cfg: Optional[Settings] = None,
) -> Optional[ResolutionResult]:
    """Resolve an entity from decisions via Hybrid Lexical + Semantic Graph Propagation."""
    policy = EntityResolutionConfig.from_settings(cfg)
    emb = _resolve_embedder(embedder, cfg)
    repo_tokens = _repository_tokens(repo)

    tokens = [
        word
        for word in _significant_words(question)
        if word not in repo_tokens
    ]
    if not tokens:
        return None

    decisions = list(store.search_decisions(repo, tokens, limit=limit))
    if not decisions:
        return None

    q_vec = emb.embed_text(question)
    scored_decisions: list[tuple[float, dict[str, Any]]] = []
    for idx, dec in enumerate(decisions):
        lex_rank_score = 1.0 / (idx + 1)
        stored_vec = dec.get("embedding")
        if isinstance(stored_vec, (list, tuple)) and len(stored_vec) == len(q_vec) and len(q_vec) > 0:
            sem_sim = compute_cosine_similarity(q_vec, stored_vec)
        else:
            dec_text = f"{dec.get('summary', '')} {dec.get('rationale', '')}".strip()
            sem_sim = compute_cosine_similarity(q_vec, emb.embed_text(dec_text)) if dec_text else 0.0
        combined_weight = 0.55 * lex_rank_score + 0.45 * max(0.0, sem_sim)
        scored_decisions.append((combined_weight, dec))

    scored_decisions.sort(key=lambda pair: pair[0], reverse=True)

    support: dict[str, tuple[float, dict[str, Any]]] = {}
    for weight, decision in scored_decisions[:5]:
        for entity in store.get_entities_for_decision(str(decision.get("id", ""))):
            if _is_pyi_stub(entity):
                continue
            key = str(entity.get("id") or entity.get("name"))
            total_w, _ = support.get(key, (0.0, entity))
            support[key] = (total_w + weight, entity)

    if not support:
        return None

    max_support = max(w for w, _ in support.values())
    if max_support <= 0.0:
        return None

    candidates = [
        EntityCandidate(
            id=str(entity.get("id", entity.get("name", ""))),
            name=str(entity.get("name", "")),
            path=str(entity.get("path", entity.get("name", ""))),
            entity_type=str(entity.get("entity_type", "File")),
            score=round(w / max_support, 4),
            signals={"graph_decision": round(w / max_support, 4)},
        )
        for w, entity in support.values()
    ]

    result = _decide_by_margin(
        candidates,
        margin=policy.ambiguity_margin,
        grounding_method="graph_decision",
        ambiguity_message="The matching decisions point at more than one entity. Please name one.",
    )

    if result.outcome == ResolutionOutcome.AMBIGUOUS and entities:
        module_candidate = _find_common_parent_module(result.candidates, entities)
        if module_candidate is not None:
            return ResolutionResult(
                outcome=ResolutionOutcome.SUCCESS,
                entity=module_candidate,
                grounding_method="module_fallback",
                score_margin=result.score_margin,
            )

    return result


# ---------------------------------------------------------------------------
# Public Entrypoint 2: End-to-End Question Grounding (G1)
# ---------------------------------------------------------------------------

def resolve_question(
    question: str,
    entities: Sequence[dict[str, Any]],
    repo: str,
    store: Any,
    *,
    embedder: Optional[BaseEmbeddingProvider] = None,
    cfg: Optional[Settings] = None,
) -> ResolutionResult:
    """Resolve a question via Hybrid Semantic + Graph Grounding."""
    resolution = resolve_entity(
        question,
        entities,
        repo,
        embedder=embedder,
        cfg=cfg,
    )
    names_an_entity = (
        resolution.outcome == ResolutionOutcome.SUCCESS
        and resolution.entity is not None
        and resolution.entity.signals.get("structural", resolution.entity.score) >= STRONG_MATCH
    )
    if (
        not names_an_entity
        and resolution.reason_code != "out_of_scope"
        and not _explicit_symbol_tokens(question)
    ):
        from_decisions = resolve_entity_from_decisions(
            question,
            store,
            repo,
            entities=entities,
            embedder=embedder,
            cfg=cfg,
        )
        if from_decisions is not None:
            return from_decisions
    return resolution
