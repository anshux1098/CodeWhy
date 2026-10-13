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
    """Computes similarity score [0.0 .. 1.0] between extracted tokens and an entity."""
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
            return 0.95 if is_file else 0.75

    # Case-insensitive name match
    for tok in query_tokens:
        if tok.lower() == name.lower():
            return 0.90

    # Token contained in name or path
    best_partial = 0.0
    for tok in query_tokens:
        tok_low = tok.lower()
        if tok_low in name.lower():
            best_partial = max(best_partial, 0.80)
        elif tok_low in basename.lower():
            best_partial = max(best_partial, 0.75)

    return best_partial


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

    # If exact match exists (1.0), it wins immediately unless another exact match ties
    top = scored[0]
    exact_matches = [c for c in scored if c.score >= 0.99]
    if len(exact_matches) == 1:
        return ResolutionResult(outcome=ResolutionOutcome.SUCCESS, entity=exact_matches[0])
    elif len(exact_matches) > 1:
        return ResolutionResult(
            outcome=ResolutionOutcome.AMBIGUOUS,
            candidates=exact_matches,
            reason_code="ambiguous_entity",
            error_message="Multiple exact matching entities found. Please select one.",
        )

    # Check for candidates within 0.05 of top score
    close_candidates = [c for c in scored if (top.score - c.score) <= 0.05]
    if len(close_candidates) > 1:
        return ResolutionResult(
            outcome=ResolutionOutcome.AMBIGUOUS,
            candidates=close_candidates,
            reason_code="ambiguous_entity",
            error_message="Question matches multiple code entities. Please select one.",
        )

    # Single winner
    if top.score >= 0.60:
        return ResolutionResult(outcome=ResolutionOutcome.SUCCESS, entity=top)

    return ResolutionResult(
        outcome=ResolutionOutcome.REFUSAL,
        reason_code="entity_not_found",
        error_message="No code entity matched with sufficient confidence.",
    )
