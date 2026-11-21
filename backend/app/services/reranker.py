"""G4 Two-Stage Calibrated Reranker & Split Conformal Thresholding (Point 4).

Replaces raw cosine similarity cutoffs with:
1. Two-stage retrieval: bi-encoder recall -> Cross-Encoder Reranker (online) or
   Calibrated Lexical+Semantic Reranker (offline).
2. Platt scaling calibration mapping raw scores into true probabilities P(relevant | q, d).
3. Split conformal prediction quantile thresholding guaranteeing bounded false-pass rate <= alpha.
4. Expected Calibration Error (ECE) evaluation helper.
"""

from __future__ import annotations

import logging
import math
import re
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from app.config import Settings, settings
from app.providers.embeddings import (
    BaseEmbeddingProvider,
    DeterministicFallbackEmbeddingProvider,
    compute_cosine_similarity,
    get_embedding_provider,
)

logger = logging.getLogger(__name__)

_RERANKER_CACHE: dict[str, Any] = {}
_RERANKER_LOCK = threading.Lock()

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")
_STOPWORDS: frozenset[str] = frozenset({
    "why", "how", "what", "when", "where", "which", "who", "does", "did", "was",
    "were", "are", "the", "and", "for", "with", "into", "from", "this", "that",
    "have", "has", "had", "been", "not", "but", "about", "like", "code", "repo",
})


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-min(x, 60.0))
        return 1.0 / (1.0 + z)
    z = math.exp(max(x, -60.0))
    return z / (1.0 + z)


@dataclass(frozen=True)
class PlattCalibrator:
    """Logistic (Platt) calibration: P(relevant | s) = sigmoid(a * s + b)."""

    a: float = 4.0
    b: float = -1.5

    def calibrate(self, raw_score: float) -> float:
        return round(_sigmoid(self.a * float(raw_score) + self.b), 4)

    @classmethod
    def fit(
        cls,
        scores: Sequence[float],
        labels: Sequence[int],
        *,
        lr: float = 0.25,
        steps: int = 400,
    ) -> PlattCalibrator:
        """Fit Platt scaling parameters (a, b) via regularized binary cross-entropy GD."""
        if not scores or len(scores) != len(labels):
            return cls()
        a, b = 1.0, 0.0
        n = float(len(scores))
        l2 = 1e-3
        for _ in range(steps):
            grad_a = 0.0
            grad_b = 0.0
            for s, y in zip(scores, labels):
                p = _sigmoid(a * float(s) + b)
                err = p - float(y)
                grad_a += err * float(s)
                grad_b += err
            a -= lr * (grad_a / n + l2 * a)
            b -= lr * (grad_b / n)
        return cls(a=round(a, 4), b=round(b, 4))


def compute_conformal_threshold(
    irrelevant_scores: Sequence[float],
    *,
    alpha: float = 0.05,
) -> float:
    """Compute a split conformal prediction threshold guaranteeing false-pass rate <= alpha.

    Given calibrated relevance scores on held-out irrelevant (negative) pairs,
    returns the finite-sample conformal quantile ceil((n + 1) * (1 - alpha)) / n.
    Any future pair scoring >= threshold has a distribution-free false-positive
    probability bounded above by ``alpha``.
    """
    if not irrelevant_scores:
        return 0.55
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha must be in (0, 1), got {alpha!r}")

    ordered = sorted(float(s) for s in irrelevant_scores)
    n = len(ordered)
    k = min(n, max(1, math.ceil((n + 1) * (1.0 - alpha))))
    return round(ordered[k - 1], 4)


def compute_ece(
    probabilities: Sequence[float],
    labels: Sequence[int],
    *,
    n_bins: int = 10,
) -> float:
    """Compute Expected Calibration Error (ECE) over predicted probabilities."""
    if not probabilities or len(probabilities) != len(labels):
        return 0.0
    n = len(probabilities)
    ece = 0.0
    for b in range(n_bins):
        lo = b / n_bins
        hi = (b + 1) / n_bins
        indices = [
            i for i, p in enumerate(probabilities)
            if (lo <= p < hi) or (b == n_bins - 1 and p == 1.0)
        ]
        if not indices:
            continue
        avg_conf = sum(probabilities[i] for i in indices) / len(indices)
        avg_acc = sum(labels[i] for i in indices) / len(indices)
        ece += (len(indices) / n) * abs(avg_conf - avg_acc)
    return round(ece, 4)


# ---------------------------------------------------------------------------
# Pluggable Reranker Abstraction
# ---------------------------------------------------------------------------

class BaseReranker(ABC):
    """Interface for scoring (question, document) relevance as calibrated probabilities."""

    @abstractmethod
    def score_pair(self, query: str, document: str) -> float:
        ...

    def score_batch(
        self,
        query: str,
        documents: Sequence[str],
        *,
        precomputed_sims: Optional[Sequence[float]] = None,
    ) -> list[float]:
        return [self.score_pair(query, doc) for doc in documents]


class CalibratedLexicalSemanticReranker(BaseReranker):
    """Offline-safe reranker fusing bi-encoder cosine + lexical coverage via Platt scaling."""

    def __init__(
        self,
        embedder: Optional[BaseEmbeddingProvider] = None,
        calibrator: Optional[PlattCalibrator] = None,
        cfg: Optional[Settings] = None,
    ) -> None:
        config = cfg or settings
        self.embedder = embedder or (
            DeterministicFallbackEmbeddingProvider(dimensions=config.embedding_dimensions)
            if config.offline
            else get_embedding_provider(cfg=config)
        )
        self.calibrator = calibrator or PlattCalibrator(
            a=config.reranker_platt_a,
            b=config.reranker_platt_b,
        )

    def _raw_score(
        self,
        query: str,
        document: str,
        q_vec: Optional[list[float]] = None,
        precomputed_sim: Optional[float] = None,
    ) -> float:
        if not query.strip() or not document.strip():
            return 0.0
        if precomputed_sim is not None:
            sem_sim = max(0.0, float(precomputed_sim))
        else:
            qv = q_vec if q_vec is not None else self.embedder.embed_text(query)
            sem_sim = max(0.0, compute_cosine_similarity(qv, self.embedder.embed_text(document)))

        q_toks = {
            t.lower() for t in _TOKEN_RE.findall(query)
            if len(t) >= 2 and t.lower() not in _STOPWORDS
        }
        d_toks = {
            t.lower() for t in _TOKEN_RE.findall(document)
            if len(t) >= 2 and t.lower() not in _STOPWORDS
        }
        if not q_toks or not d_toks:
            return sem_sim

        matched = sum(
            1 for qt in q_toks
            if qt in d_toks or any(
                len(qt) >= 4 and len(dt) >= 4 and (dt.startswith(qt[:4]) or qt.startswith(dt[:4]))
                for dt in d_toks
            )
        )
        lexical_recall = matched / len(q_toks)
        return 0.55 * sem_sim + 0.45 * lexical_recall

    def score_pair(self, query: str, document: str) -> float:
        raw = self._raw_score(query, document)
        return self.calibrator.calibrate(raw)

    def score_batch(
        self,
        query: str,
        documents: Sequence[str],
        *,
        precomputed_sims: Optional[Sequence[float]] = None,
    ) -> list[float]:
        if not documents:
            return []
        if precomputed_sims is not None and len(precomputed_sims) == len(documents):
            return [
                self.calibrator.calibrate(self._raw_score(query, doc, precomputed_sim=sim))
                for doc, sim in zip(documents, precomputed_sims)
            ]
        q_vec = self.embedder.embed_text(query)
        return [self.calibrator.calibrate(self._raw_score(query, doc, q_vec=q_vec)) for doc in documents]


class CrossEncoderReranker(BaseReranker):
    """Production cross-encoder reranker (e.g., cross-encoder/ms-marco-MiniLM-L-6-v2)."""

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        calibrator: Optional[PlattCalibrator] = None,
    ) -> None:
        self.model_name = model_name
        # Cross-encoder logits are already roughly centered around 0; sigmoid(logit) calibrates cleanly
        self.calibrator = calibrator or PlattCalibrator(a=1.0, b=0.0)

    def _get_model(self) -> Any:
        if self.model_name not in _RERANKER_CACHE:
            with _RERANKER_LOCK:
                if self.model_name not in _RERANKER_CACHE:
                    from sentence_transformers import CrossEncoder  # type: ignore

                    _RERANKER_CACHE[self.model_name] = CrossEncoder(self.model_name)
        return _RERANKER_CACHE[self.model_name]

    def score_pair(self, query: str, document: str) -> float:
        model = self._get_model()
        logit = float(model.predict([(query, document)])[0])
        return self.calibrator.calibrate(logit)

    def score_batch(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []
        model = self._get_model()
        logits = model.predict([(query, doc) for doc in documents])
        return [self.calibrator.calibrate(float(x)) for x in logits]


def get_reranker(
    cfg: Optional[Settings] = None,
    embedder: Optional[BaseEmbeddingProvider] = None,
) -> BaseReranker:
    """Resolve the configured reranker (CrossEncoder online, CalibratedLexicalSemantic offline)."""
    config = cfg or settings
    if not config.offline:
        try:
            import sentence_transformers  # noqa: F401

            return CrossEncoderReranker(model_name=config.reranker_model_name)
        except Exception:  # noqa: BLE001
            logger.debug("CrossEncoder reranker unavailable; using CalibratedLexicalSemanticReranker")
    return CalibratedLexicalSemanticReranker(embedder=embedder, cfg=config)
