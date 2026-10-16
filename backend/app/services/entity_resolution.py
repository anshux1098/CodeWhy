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


def _distinct_ids(candidates: Sequence[EntityCandidate]) -> set[str]:
    return {candidate.path or candidate.name for candidate in candidates}


def resolve_entity(
    question: str,
    available_entities: Sequence[dict[str, Any]],
) -> ResolutionResult:
    """Resolves an entity from the question according to Section 4, Layer 5 of the spec.

    Rules:
    - Out-of-scope question -> refusal (reason_code="out_of_scope")
    - Exact match wins
    - Multiple candidates scoring within 0.05 of each other -> refusal (reason_code="ambiguous_entity")
    - No candidate found -> refusal (reason_code="entity_not_found")
    """
    if is_out_of_scope(question):
        return ResolutionResult(
            outcome=ResolutionOutcome.REFUSAL,
            reason_code="out_of_scope",
            error_message="Question is not about a repository code entity, file, or configuration.",
        )

    tokens = extract_query_tokens(question)
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
    # single one; otherwise they are coincidences and nothing was named.
    top = scored[0]
    weak_ties = [c for c in scored if c.score == top.score]
    if top.score >= PARTIAL_MATCH and len(_distinct_ids(weak_ties)) == 1:
        return ResolutionResult(outcome=ResolutionOutcome.SUCCESS, entity=weak_ties[0])

    return ResolutionResult(
        outcome=ResolutionOutcome.REFUSAL,
        reason_code="entity_not_found",
        error_message="No code entity matched with sufficient confidence.",
    )
