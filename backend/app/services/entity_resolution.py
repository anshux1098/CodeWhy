from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Optional, Sequence


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


@dataclass(frozen=True)
class ResolutionResult:
    outcome: ResolutionOutcome
    entity: Optional[EntityCandidate] = None
    candidates: list[EntityCandidate] = field(default_factory=list)
    reason_code: Optional[str] = None
    error_message: Optional[str] = None


# Heuristic patterns for non-code / out-of-scope questions
OUT_OF_SCOPE_PATTERNS = (
    re.compile(r"why\s+was\s+the\s+team\s+late", re.IGNORECASE),
    re.compile(r"who\s+ordered\s+pizza", re.IGNORECASE),
    re.compile(r"what\s+is\s+the\s+weather", re.IGNORECASE),
    re.compile(r"when\s+is\s+lunch", re.IGNORECASE),
    re.compile(r"meeting|party|demo\s+late|standup", re.IGNORECASE),
)

PATH_PATTERN = re.compile(r"[\w./-]+\.(?:py|json|yaml|yml|toml|md|rst|txt)")
UPPER_CONST_PATTERN = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")
DOTTED_PATTERN = re.compile(r"\b[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w+)+\b")
QUOTED_PATTERN = re.compile(r"['\"]([a-zA-Z0-9_./-]+)['\"]")


def extract_query_tokens(question: str) -> set[str]:
    """Extract candidate entity identifiers from question text using rule-based patterns."""
    tokens: set[str] = set()

    for m in PATH_PATTERN.finditer(question):
        tokens.add(m.group(0))

    for m in UPPER_CONST_PATTERN.finditer(question):
        tokens.add(m.group(0))

    for m in DOTTED_PATTERN.finditer(question):
        tokens.add(m.group(0))

    for m in QUOTED_PATTERN.finditer(question):
        tokens.add(m.group(1))

    # Also extract individual alphanumeric words (>2 chars)
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


def is_out_of_scope(question: str) -> bool:
    """Checks if a natural language question is clearly unrelated to repository code."""
    for p in OUT_OF_SCOPE_PATTERNS:
        if p.search(question):
            return True
    return False


def score_entity_match(query_tokens: set[str], entity: dict[str, Any]) -> float:
    """Computes similarity score [0.0 .. 1.0] between extracted tokens and an entity.

    The score has three tiers. An exact id/name/path is 1.0 and beats everything. A
    basename and a case-insensitive name are strong (0.85-0.90). A bare substring is
    weak (0.65-0.70) and must never decide between entities on its own: the repository
    name appears inside every path, so a weak match is a coincidence, not a reference.
    """
    name = entity.get("name", "")
    path = entity.get("path", "")
    ident = entity.get("id", "")

    # Exact name or path match gives 1.0
    for tok in query_tokens:
        if tok == name or tok == path or tok == ident:
            return 1.0

    # Path basename match (e.g., "retry.py" vs "src/pkg/retry.py")
    basename = path.split("/")[-1] if "/" in path else path
    is_file = entity.get("entity_type") in ("File", "Module") or "/" in name
    for tok in query_tokens:
        if tok == basename:
            return 0.90 if is_file else 0.75

    # Case-insensitive name match
    for tok in query_tokens:
        if tok.lower() == name.lower():
            return 0.85

    # Token contained in name or basename: weak, never sufficient to choose.
    best_partial = 0.0
    for tok in query_tokens:
        tok_low = tok.lower()
        if tok_low in name.lower():
            best_partial = max(best_partial, 0.70)
        elif tok_low in basename.lower():
            best_partial = max(best_partial, 0.65)

    return best_partial


#: A score at or above this is a real reference: an exact match or a basename/name.
#: Below it, matches are coincidences (a shared token such as the repository name).
STRONG_MATCH = 0.85

#: A weak match must at least reach this to be considered at all.
PARTIAL_MATCH = 0.70


def _is_pyi_stub(entity: dict[str, Any]) -> bool:
    """A type stub is not a separate entity from the module it describes."""
    for key in ("path", "name"):
        if str(entity.get(key, "")).endswith(".pyi"):
            return True
    return False


def _repository_tokens(repository: str) -> set[str]:
    """Tokens that come from the repository name and name no entity.

    The name sits inside every path (`src/urllib3/...`), so without this a question
    that merely mentions the project makes every entity a partial match.
    """
    text = str(repository or "").strip().lower()
    if not text:
        return set()
    tokens = {text}
    tokens.update(part for part in re.split(r"[/\-_.]", text) if part)
    return tokens


def _distinct_ids(candidates: Sequence[EntityCandidate]) -> set[str]:
    return {candidate.id for candidate in candidates}


def names_an_explicit_path_or_quote(question: str) -> bool:
    """Whether the question names a file path or a quoted identifier.

    Such a question is asking about that name. If it is not in the graph the honest
    answer is that it is not found, not an entity derived from decisions that merely
    share a directory word.
    """
    return bool(PATH_PATTERN.search(question) or QUOTED_PATTERN.search(question))


def _drop_redundant_tokens(tokens: set[str]) -> set[str]:
    """Drop tokens that are contained in a longer token.

    A question naming ``src/urllib3/util/url.py`` also yields ``src``, ``util`` and
    ``url.py``. Those components match directory-mates by substring, so keeping them
    turns a missing file into a tie across every ``src/...`` entity. The longest form
    alone says what was named.
    """
    kept = set(tokens)
    for token in list(tokens):
        if any(other != token and token in other for other in tokens):
            kept.discard(token)
    return kept


def resolve_entity(
    question: str,
    available_entities: Sequence[dict[str, Any]],
    repository: str = "",
) -> ResolutionResult:
    """Resolves an entity from the question according to Section 4, Layer 5 of the spec.

    Rules:
    - Out-of-scope question -> refusal (reason_code="out_of_scope")
    - An exact or basename match beats a partial token match
    - Ambiguity is kept only when two genuinely different entities tie
    - Tokens from the repository name, which sit in every path, are ignored
    - No candidate found -> refusal (reason_code="entity_not_found")
    """
    if is_out_of_scope(question):
        return ResolutionResult(
            outcome=ResolutionOutcome.REFUSAL,
            reason_code="out_of_scope",
            error_message="Question is not about a repository code entity, file, or configuration.",
        )

    tokens = _drop_redundant_tokens(extract_query_tokens(question) - _repository_tokens(repository))
    if not tokens:
        return ResolutionResult(
            outcome=ResolutionOutcome.REFUSAL,
            reason_code="entity_not_found",
            error_message="No code entity could be identified in the question.",
        )

    scored: list[EntityCandidate] = []
    for ent in available_entities:
        if _is_pyi_stub(ent):
            continue
        score = score_entity_match(tokens, ent)
        if score > 0.0:
            scored.append(
                EntityCandidate(
                    id=ent.get("id", ent.get("name", "")),
                    name=ent.get("name", ""),
                    path=ent.get("path", ""),
                    entity_type=ent.get("entity_type", "File"),
                    score=score,
                )
            )

    if not scored:
        return ResolutionResult(
            outcome=ResolutionOutcome.REFUSAL,
            reason_code="entity_not_found",
            error_message="No matching code entity was found in the repository.",
        )

    # Sort descending by score
    scored.sort(key=lambda c: c.score, reverse=True)

    # A strong match (exact path/name or a basename) is a real reference. If one
    # entity alone holds the best strong score, it wins. If several genuinely
    # different entities tie, the caller must choose.
    strong = [c for c in scored if c.score >= STRONG_MATCH]
    if strong:
        best = strong[0]
        ties = [c for c in strong if (best.score - c.score) <= 0.05]
        if len(_distinct_ids(ties)) == 1:
            winner = max(ties, key=lambda c: c.score)
            return ResolutionResult(outcome=ResolutionOutcome.SUCCESS, entity=winner)
        return ResolutionResult(
            outcome=ResolutionOutcome.AMBIGUOUS,
            candidates=ties,
            reason_code="ambiguous_entity",
            error_message="Question matches multiple code entities. Please select one.",
        )

    # Only weak matches remain. They identify an entity solely when they agree on a
    # single one; a real tie between different entities is still ambiguous.
    top = scored[0]
    weak_ties = [c for c in scored if c.score == top.score]
    if top.score >= PARTIAL_MATCH:
        if len(_distinct_ids(weak_ties)) == 1:
            return ResolutionResult(outcome=ResolutionOutcome.SUCCESS, entity=weak_ties[0])
        return ResolutionResult(
            outcome=ResolutionOutcome.AMBIGUOUS,
            candidates=weak_ties,
            reason_code="ambiguous_entity",
            error_message="Question matches multiple code entities. Please select one.",
        )

    return ResolutionResult(
        outcome=ResolutionOutcome.REFUSAL,
        reason_code="entity_not_found",
        error_message="No code entity matched with sufficient confidence.",
    )


#: Words that carry no entity information and would match almost any decision text.
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


def _significant_words(question: str) -> list[str]:
    """Lower-cased words from a question that could name a decision's subject."""
    words: list[str] = []
    for word in re.findall(r"[a-zA-Z0-9_]{3,}", question):
        low = word.lower()
        if low in _STOPWORDS or low in words:
            continue
        words.append(low)
    return words


def resolve_entity_from_decisions(
    question: str,
    store: Any,
    repo: str,
    limit: int = 5,
) -> Optional[ResolutionResult]:
    """Resolve an entity from the decisions a question's own text matches.

    Used when the question names no entity: the decisions are found from their text
    (the evidence full-text index plus summary and rationale), and the entity is taken
    from the decisions through GOVERNS. Returns None when nothing matches, so the
    caller keeps its original refusal rather than inventing an entity.
    """
    tokens = [
        word
        for word in _significant_words(question)
        if word not in _repository_tokens(repo)
    ]
    if not tokens:
        return None

    decisions = store.search_decisions(repo, tokens, limit=limit)
    if not decisions:
        return None

    # How many of the top decisions each entity is governed by. The entity the
    # question is really about is the one the strongest decisions agree on.
    support: dict[str, tuple[int, dict[str, Any]]] = {}
    for decision in decisions[:3]:
        for entity in store.get_entities_for_decision(str(decision.get("id", ""))):
            key = str(entity.get("id") or entity.get("name"))
            count, _ = support.get(key, (0, entity))
            support[key] = (count + 1, entity)

    if not support:
        return None

    best = max(count for count, _ in support.values())
    winners = [entity for count, entity in support.values() if count == best]
    candidates = [
        EntityCandidate(
            id=str(entity.get("id", entity.get("name", ""))),
            name=str(entity.get("name", "")),
            path=str(entity.get("path", entity.get("name", ""))),
            entity_type=str(entity.get("entity_type", "File")),
            score=float(best),
        )
        for entity in winners
    ]
    if len(candidates) == 1:
        return ResolutionResult(outcome=ResolutionOutcome.SUCCESS, entity=candidates[0])
    return ResolutionResult(
        outcome=ResolutionOutcome.AMBIGUOUS,
        candidates=candidates,
        reason_code="ambiguous_entity",
        error_message="The matching decisions point at more than one entity. Please name one.",
    )


def resolve_question(
    question: str,
    entities: Sequence[dict[str, Any]],
    repo: str,
    store: Any,
) -> ResolutionResult:
    """Resolve a question the way the answer path does, including the text route.

    The question names an entity only when the best match is a real reference (a
    full path, an exact filename, or an exact name: ``STRONG_MATCH`` or above). A
    weaker match is a loose token inside a path (the "HTTP" in "http2", say) and
    must not preempt the text route. When the question names nothing, find the
    decisions from their own text and take the entity from them. An out-of-scope
    question, a real tie, and a named path that is simply absent are all left as
    they are.

    Both the API and the walkthrough call this, so the rule cannot drift between
    the two.
    """
    resolution = resolve_entity(question, entities, repo)
    names_an_entity = (
        resolution.outcome == ResolutionOutcome.SUCCESS
        and resolution.entity is not None
        and resolution.entity.score >= STRONG_MATCH
    )
    if (
        not names_an_entity
        and resolution.reason_code != "out_of_scope"
        and not names_an_explicit_path_or_quote(question)
    ):
        from_decisions = resolve_entity_from_decisions(question, store, repo)
        if from_decisions is not None:
            return from_decisions
    return resolution
