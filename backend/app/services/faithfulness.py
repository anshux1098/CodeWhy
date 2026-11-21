"""G3 Claim-Level NLI / Faithfulness Verification (Point 3).

Replaces binary non-empty quote checks with claim-level entailment verification:
1. Decomposes generated answers into atomic factual claims.
2. Scores each (evidence_premise, claim_hypothesis) pair as ENTAILED, NEUTRAL,
   or CONTRADICTED using either a real NLI cross-encoder (when online & installed)
   or a fast, deterministic semantic + polarity entailment verifier (when offline).
3. Computes an overall answer faithfulness rate and contradiction flag so
   ungrounded or contradicted LLM claims are caught and degraded transparently.
"""

from __future__ import annotations

import logging
import math
import re
import threading
from abc import ABC, abstractmethod
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

logger = logging.getLogger(__name__)

_NLI_MODEL_CACHE: dict[str, Any] = {}
_NLI_MODEL_LOCK = threading.Lock()


class EntailmentLabel(StrEnum):
    ENTAILED = "entailed"
    NEUTRAL = "neutral"
    CONTRADICTED = "contradicted"


@dataclass(frozen=True)
class EntailmentScore:
    label: EntailmentLabel
    entailment: float
    contradiction: float
    neutral: float


@dataclass(frozen=True)
class ClaimVerificationResult:
    claim: str
    label: EntailmentLabel
    score: float
    contradiction_score: float = 0.0
    best_evidence_id: Optional[str] = None


@dataclass(frozen=True)
class FaithfulnessReport:
    entailment_rate: float
    contradiction_detected: bool
    verified_claims: int
    total_claims: int
    claims: list[ClaimVerificationResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Claim Decomposition
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")

_STOPWORDS: frozenset[str] = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "was", "were", "are",
    "has", "have", "had", "been", "not", "but", "into", "onto", "also", "then",
    "than", "when", "where", "which", "while", "will", "would", "should", "could",
    "because", "since", "about", "after", "before", "level", "based", "notes",
    "states", "according", "history", "repository", "decision", "change", "changed",
})

_NEGATION_WORDS: frozenset[str] = frozenset({
    "not", "never", "no", "none", "without", "disabled", "disable", "removed",
    "remove", "dropped", "drop", "prevent", "forbid", "forbidden", "avoid",
})

_ANTONYM_PAIRS: tuple[tuple[str, str], ...] = (
    ("enabled", "disabled"),
    ("enable", "disable"),
    ("added", "removed"),
    ("increased", "decreased"),
    ("raised", "lowered"),
    ("always", "never"),
    ("allowed", "forbidden"),
    ("allow", "forbid"),
    ("true", "false"),
    ("synchronous", "asynchronous"),
    ("sync", "async"),
)


def decompose_claims(text: str) -> list[str]:
    """Split an answer into atomic factual claims while preserving file paths & decimals."""
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return []

    raw_sentences = _SENTENCE_SPLIT.split(clean)
    claims: list[str] = []
    for sent in raw_sentences:
        s = sent.strip()
        if len(s) < 8:
            continue
        claims.append(s)
    return claims or [clean]


def _content_tokens(text: str) -> set[str]:
    return {
        tok.lower()
        for tok in _TOKEN_RE.findall(text or "")
        if len(tok) >= 2 and tok.lower() not in _STOPWORDS
    }


def _extract_numbers(text: str) -> set[str]:
    # Ignore PR/issue references like #3456 when comparing numeric quantities
    cleaned = re.sub(r"#\d+", " ", text or "")
    return set(re.findall(r"\b\d+(?:\.\d+)?\b", cleaned))


def _detect_polarity_contradiction(premise: str, hypothesis: str) -> float:
    """Detect explicit negation or antonym contradictions between premise and claim."""
    p_toks = {t.lower() for t in _TOKEN_RE.findall(premise or "")}
    h_toks = {t.lower() for t in _TOKEN_RE.findall(hypothesis or "")}

    # Only flag contradiction when premise and hypothesis discuss overlapping concepts
    shared_content = _content_tokens(premise) & _content_tokens(hypothesis)
    if not shared_content:
        return 0.0

    # 1. Explicit antonym clash (e.g., "enabled" in premise vs "disabled" in claim)
    for a, b in _ANTONYM_PAIRS:
        if (a in p_toks and b in h_toks and b not in p_toks) or (
            b in p_toks and a in h_toks and a not in p_toks
        ):
            return 0.85

    # 2. Negation polarity flip (one negates a shared concept while the other affirms it)
    p_neg = bool(p_toks & _NEGATION_WORDS)
    h_neg = bool(h_toks & _NEGATION_WORDS)
    if p_neg != h_neg and len(shared_content) >= 2:
        # Don't flag "not" inside standard rationale phrasing like "avoid timeouts"
        if ("never" in h_toks and "never" not in p_toks) or (
            "not" in h_toks and "not" not in p_toks and len(shared_content) >= 3
        ):
            return 0.78

    return 0.0


# ---------------------------------------------------------------------------
# Pluggable NLI Verifier Abstraction
# ---------------------------------------------------------------------------

class BaseNLIVerifier(ABC):
    """Interface for scoring (premise, hypothesis) entailment."""

    @abstractmethod
    def verify_pair(self, premise: str, hypothesis: str) -> EntailmentScore:
        ...


class SemanticEntailmentVerifier(BaseNLIVerifier):
    """Fast, offline-safe entailment verifier combining semantic similarity,
    content-concept coverage, and polarity contradiction detection."""

    def __init__(
        self,
        embedder: Optional[BaseEmbeddingProvider] = None,
        entailment_threshold: float = 0.45,
        cfg: Optional[Settings] = None,
    ) -> None:
        config = cfg or settings
        self.embedder = embedder or (
            DeterministicFallbackEmbeddingProvider(dimensions=config.embedding_dimensions)
            if config.offline
            else get_embedding_provider(cfg=config)
        )
        self.entailment_threshold = entailment_threshold

    def verify_pair(self, premise: str, hypothesis: str) -> EntailmentScore:
        if not premise.strip() or not hypothesis.strip():
            return EntailmentScore(EntailmentLabel.NEUTRAL, 0.0, 0.0, 1.0)

        contradiction = _detect_polarity_contradiction(premise, hypothesis)
        if contradiction >= 0.75:
            return EntailmentScore(
                label=EntailmentLabel.CONTRADICTED,
                entailment=round(max(0.0, 1.0 - contradiction), 4),
                contradiction=round(contradiction, 4),
                neutral=0.0,
            )

        p_terms = _content_tokens(premise)
        h_terms = _content_tokens(hypothesis)
        if not h_terms:
            return EntailmentScore(EntailmentLabel.NEUTRAL, 0.0, 0.0, 1.0)

        # Concept coverage with stem-prefix tolerance (e.g., "retry" / "retries", "revert" / "reverted")
        matched = 0
        for ht in h_terms:
            if ht in p_terms or any(
                (len(ht) >= 4 and len(pt) >= 4 and (pt.startswith(ht[:4]) or ht.startswith(pt[:4])))
                for pt in p_terms
            ):
                matched += 1
        concept_recall = matched / len(h_terms)

        # Numeric consistency bonus/penalty
        p_nums = _extract_numbers(premise)
        h_nums = _extract_numbers(hypothesis)
        if p_nums and h_nums and not (p_nums & h_nums) and concept_recall >= 0.35:
            # Claim asserts a different number than the evidence for the same concept
            return EntailmentScore(
                label=EntailmentLabel.CONTRADICTED,
                entailment=0.15,
                contradiction=0.80,
                neutral=0.05,
            )

        sem_sim = max(0.0, compute_cosine_similarity(
            self.embedder.embed_text(premise),
            self.embedder.embed_text(hypothesis),
        ))
        entailment = round(min(1.0, 0.60 * concept_recall + 0.40 * sem_sim), 4)
        neutral = round(max(0.0, 1.0 - entailment - contradiction), 4)

        if entailment >= self.entailment_threshold:
            label = EntailmentLabel.ENTAILED
        else:
            label = EntailmentLabel.NEUTRAL

        return EntailmentScore(
            label=label,
            entailment=entailment,
            contradiction=round(contradiction, 4),
            neutral=neutral,
        )


class CrossEncoderNLIVerifier(BaseNLIVerifier):
    """Production NLI cross-encoder (e.g., cross-encoder/nli-deberta-v3-small)."""

    def __init__(
        self,
        model_name: str = "cross-encoder/nli-deberta-v3-small",
        entailment_threshold: float = 0.50,
    ) -> None:
        self.model_name = model_name
        self.entailment_threshold = entailment_threshold

    def _get_model(self) -> Any:
        if self.model_name not in _NLI_MODEL_CACHE:
            with _NLI_MODEL_LOCK:
                if self.model_name not in _NLI_MODEL_CACHE:
                    from sentence_transformers import CrossEncoder  # type: ignore

                    _NLI_MODEL_CACHE[self.model_name] = CrossEncoder(self.model_name)
        return _NLI_MODEL_CACHE[self.model_name]

    def verify_pair(self, premise: str, hypothesis: str) -> EntailmentScore:
        model = self._get_model()
        logits = model.predict([(premise, hypothesis)])[0]
        # DeBERTa NLI standard label order: [contradiction, entailment, neutral]
        exps = [math.exp(float(x)) for x in logits]
        total = sum(exps) or 1.0
        probs = [e / total for e in exps]
        p_contra, p_entail, p_neutral = probs[0], probs[1], probs[2]

        if p_contra >= 0.65 and p_contra > p_entail:
            label = EntailmentLabel.CONTRADICTED
        elif p_entail >= self.entailment_threshold and p_entail >= p_neutral:
            label = EntailmentLabel.ENTAILED
        else:
            label = EntailmentLabel.NEUTRAL

        return EntailmentScore(
            label=label,
            entailment=round(p_entail, 4),
            contradiction=round(p_contra, 4),
            neutral=round(p_neutral, 4),
        )


def get_nli_verifier(
    cfg: Optional[Settings] = None,
    embedder: Optional[BaseEmbeddingProvider] = None,
) -> BaseNLIVerifier:
    """Resolve the configured NLI verifier (CrossEncoder online, SemanticEntailment offline)."""
    config = cfg or settings
    if not config.offline:
        try:
            import sentence_transformers  # noqa: F401

            return CrossEncoderNLIVerifier(
                model_name=config.nli_model_name,
                entailment_threshold=config.nli_entailment_threshold,
            )
        except Exception:  # noqa: BLE001
            logger.debug("CrossEncoder NLI unavailable; using SemanticEntailmentVerifier")
    return SemanticEntailmentVerifier(
        embedder=embedder,
        entailment_threshold=config.nli_entailment_threshold,
        cfg=config,
    )


# ---------------------------------------------------------------------------
# High-Level Answer Faithfulness Verification
# ---------------------------------------------------------------------------

def verify_answer_faithfulness(
    answer_text: str,
    evidence_premises: Sequence[tuple[str, str]],
    *,
    verifier: Optional[BaseNLIVerifier] = None,
    cfg: Optional[Settings] = None,
) -> FaithfulnessReport:
    """Verify each atomic claim in ``answer_text`` against ``(evidence_id, premise_text)`` pairs."""
    claims = decompose_claims(answer_text)
    if not claims or not evidence_premises:
        return FaithfulnessReport(
            entailment_rate=0.0,
            contradiction_detected=False,
            verified_claims=0,
            total_claims=len(claims),
            claims=[],
        )

    nli = verifier or get_nli_verifier(cfg=cfg)
    results: list[ClaimVerificationResult] = []
    verified = 0
    contradiction_detected = False

    # Also build combined premise so multi-evidence synthesis claims can be entailed jointly
    combined_premise = " ".join(text for _, text in evidence_premises if text)

    for claim in claims:
        best_entail = -1.0
        best_contra = 0.0
        best_ev_id: Optional[str] = None
        best_label = EntailmentLabel.NEUTRAL

        for ev_id, premise in evidence_premises:
            score = nli.verify_pair(premise, claim)
            if score.label == EntailmentLabel.CONTRADICTED and score.contradiction > best_contra:
                best_contra = score.contradiction
            if score.entailment > best_entail:
                best_entail = score.entailment
                best_ev_id = ev_id
                best_label = score.label

        # If no single quote entailed the claim, check combined evidence premise
        if best_label != EntailmentLabel.ENTAILED and len(evidence_premises) > 1:
            joint = nli.verify_pair(combined_premise, claim)
            if joint.label == EntailmentLabel.ENTAILED and joint.entailment > best_entail:
                best_entail = joint.entailment
                best_label = EntailmentLabel.ENTAILED

        if best_contra >= 0.75 and best_label != EntailmentLabel.ENTAILED:
            best_label = EntailmentLabel.CONTRADICTED
            contradiction_detected = True
        elif best_label == EntailmentLabel.ENTAILED:
            verified += 1

        results.append(
            ClaimVerificationResult(
                claim=claim,
                label=best_label,
                score=round(max(0.0, best_entail), 4),
                contradiction_score=round(best_contra, 4),
                best_evidence_id=best_ev_id,
            )
        )

    rate = round(verified / len(claims), 4) if claims else 0.0
    return FaithfulnessReport(
        entailment_rate=rate,
        contradiction_detected=contradiction_detected,
        verified_claims=verified,
        total_claims=len(claims),
        claims=results,
    )
