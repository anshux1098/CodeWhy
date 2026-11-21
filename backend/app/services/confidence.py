"""Calibrated Confidence Scoring Model & Evaluation Metrics (Point 5).

Replaces hardcoded linear weights with a configurable, trainable
``CalibratedConfidenceModel`` that can be fit on labeled evaluation benchmarks
using L2-regularized logistic regression, serialized to JSON, loaded via
``CONFIDENCE_MODEL_PATH``, and validated with ECE and Brier score.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal, Optional, Sequence

from app.config import Settings, settings
from app.services.reranker import compute_ece
from app.schemas.common import ConfidenceLabel

if TYPE_CHECKING:
    from app.schemas.confidence import ConfidenceScore

HIGH_THRESHOLD: Final[float] = 0.75
MEDIUM_THRESHOLD: Final[float] = 0.50
CONTRADICTION_SCORE_CAP: Final[float] = 0.70

FEATURE_NAMES: Final[tuple[str, ...]] = (
    "directness",
    "provenance",
    "agreement",
    "relevance",
    "temporal_consistency",
    "contradiction",
)


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-min(x, 60.0))
        return 1.0 / (1.0 + z)
    z = math.exp(max(x, -60.0))
    return z / (1.0 + z)


def derive_label(
    score: float,
    *,
    high_threshold: float = HIGH_THRESHOLD,
    medium_threshold: float = MEDIUM_THRESHOLD,
) -> ConfidenceLabel:
    """Derives HIGH, MEDIUM, or LOW label from numeric score."""
    if score >= high_threshold:
        return ConfidenceLabel.HIGH
    if score >= medium_threshold:
        return ConfidenceLabel.MEDIUM
    return ConfidenceLabel.LOW


@dataclass(frozen=True)
class ConfidenceExample:
    """One labeled evaluation example for fitting/evaluating the confidence model."""

    directness: float
    provenance: float
    agreement: float
    relevance: float
    temporal_consistency: float
    contradiction: float
    is_correct: int  # 1 = verified correct answer, 0 = incorrect/hallucinated

    def feature_vector(self) -> tuple[float, ...]:
        return (
            float(self.directness),
            float(self.provenance),
            float(self.agreement),
            float(self.relevance),
            float(self.temporal_consistency),
            float(self.contradiction),
        )


@dataclass(frozen=True)
class CalibrationReport:
    """Calibration quality metrics for a confidence scoring model."""

    ece: float
    brier_score: float
    sample_count: int
    mean_predicted: float
    empirical_accuracy: float


def compute_brier_score(
    probabilities: Sequence[float],
    labels: Sequence[int],
) -> float:
    """Compute Brier score (mean squared error of predicted probabilities; lower is better)."""
    if not probabilities or len(probabilities) != len(labels):
        return 0.0
    mse = sum((float(p) - float(y)) ** 2 for p, y in zip(probabilities, labels)) / len(probabilities)
    return round(mse, 4)


def compute_calibration_report(
    probabilities: Sequence[float],
    labels: Sequence[int],
    *,
    n_bins: int = 10,
) -> CalibrationReport:
    """Evaluate ECE, Brier score, and calibration alignment on a labeled set."""
    if not probabilities or len(probabilities) != len(labels):
        return CalibrationReport(0.0, 0.0, 0, 0.0, 0.0)
    return CalibrationReport(
        ece=compute_ece(probabilities, labels, n_bins=n_bins),
        brier_score=compute_brier_score(probabilities, labels),
        sample_count=len(probabilities),
        mean_predicted=round(sum(probabilities) / len(probabilities), 4),
        empirical_accuracy=round(sum(labels) / len(labels), 4),
    )


@dataclass(frozen=True)
class CalibratedConfidenceModel:
    """Configurable/trainable confidence scorer over the 6 evidence signals."""

    weights: tuple[float, ...]
    bias: float = 0.0
    mode: Literal["linear", "logistic"] = "linear"
    high_threshold: float = HIGH_THRESHOLD
    medium_threshold: float = MEDIUM_THRESHOLD
    contradiction_cap: float = CONTRADICTION_SCORE_CAP

    @classmethod
    def linear_default(cls) -> CalibratedConfidenceModel:
        return cls(
            weights=(0.30, 0.20, 0.20, 0.15, 0.15, -0.30),
            bias=0.0,
            mode="linear",
        )

    @classmethod
    def logistic_default(cls) -> CalibratedConfidenceModel:
        return cls(
            weights=(2.2, 1.4, 1.3, 1.6, 1.0, -2.5),
            bias=-4.2,
            mode="logistic",
        )

    def predict(
        self,
        *,
        directness: float,
        provenance: float,
        agreement: float,
        relevance: float,
        temporal_consistency: float,
        contradiction: float,
    ) -> float:
        features = (
            float(directness),
            float(provenance),
            float(agreement),
            float(relevance),
            float(temporal_consistency),
            float(contradiction),
        )
        raw = sum(w * x for w, x in zip(self.weights, features)) + self.bias
        score = _sigmoid(raw) if self.mode == "logistic" else raw
        clipped = max(0.0, min(1.0, score))
        if contradiction >= 1.0:
            clipped = min(clipped, self.contradiction_cap)
        return round(clipped, 4)

    @classmethod
    def fit(
        cls,
        examples: Sequence[ConfidenceExample],
        *,
        lr: float = 0.35,
        steps: int = 500,
        l2: float = 1e-3,
    ) -> CalibratedConfidenceModel:
        """Fit a calibrated logistic regression model on labeled evaluation examples."""
        if not examples:
            return cls.logistic_default()

        w = [0.0] * len(FEATURE_NAMES)
        b = 0.0
        n = float(len(examples))

        for _ in range(steps):
            grad_w = [0.0] * len(FEATURE_NAMES)
            grad_b = 0.0
            for ex in examples:
                feats = ex.feature_vector()
                p = _sigmoid(sum(wi * xi for wi, xi in zip(w, feats)) + b)
                err = p - float(ex.is_correct)
                for i, xi in enumerate(feats):
                    grad_w[i] += err * xi
                grad_b += err
            for i in range(len(w)):
                w[i] -= lr * (grad_w[i] / n + l2 * w[i])
            b -= lr * (grad_b / n)

        return cls(
            weights=tuple(round(val, 4) for val in w),
            bias=round(b, 4),
            mode="logistic",
        )

    def evaluate(self, examples: Sequence[ConfidenceExample], *, n_bins: int = 10) -> CalibrationReport:
        probs = [
            self.predict(
                directness=ex.directness,
                provenance=ex.provenance,
                agreement=ex.agreement,
                relevance=ex.relevance,
                temporal_consistency=ex.temporal_consistency,
                contradiction=ex.contradiction,
            )
            for ex in examples
        ]
        labels = [int(ex.is_correct) for ex in examples]
        return compute_calibration_report(probs, labels, n_bins=n_bins)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "weights": dict(zip(FEATURE_NAMES, self.weights)),
            "bias": self.bias,
            "high_threshold": self.high_threshold,
            "medium_threshold": self.medium_threshold,
            "contradiction_cap": self.contradiction_cap,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CalibratedConfidenceModel:
        w_map = payload.get("weights") or {}
        weights = tuple(float(w_map.get(name, 0.0)) for name in FEATURE_NAMES)
        mode = "logistic" if payload.get("mode") == "logistic" else "linear"
        return cls(
            weights=weights,
            bias=float(payload.get("bias", 0.0)),
            mode=mode,
            high_threshold=float(payload.get("high_threshold", HIGH_THRESHOLD)),
            medium_threshold=float(payload.get("medium_threshold", MEDIUM_THRESHOLD)),
            contradiction_cap=float(payload.get("contradiction_cap", CONTRADICTION_SCORE_CAP)),
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> CalibratedConfidenceModel:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def resolve_confidence_model(cfg: Optional[Settings] = None) -> CalibratedConfidenceModel:
    """Load configured confidence model artifact or return default model."""
    config = cfg or settings
    if config.confidence_model_path:
        path = Path(config.confidence_model_path)
        if path.exists():
            return CalibratedConfidenceModel.load(path)
    if config.confidence_use_calibrated_model:
        return CalibratedConfidenceModel.logistic_default()
    return CalibratedConfidenceModel.linear_default()


def calculate_confidence(
    directness: float = 1.0,
    provenance: float = 0.8,
    agreement: float = 0.4,
    relevance: float = 0.8,
    temporal_consistency: float = 1.0,
    contradiction: Literal[0.0, 1.0] = 0.0,
    *,
    model: Optional[CalibratedConfidenceModel] = None,
    cfg: Optional[Settings] = None,
) -> ConfidenceScore:
    """Calculate confidence score using a calibrated/configurable scoring model."""
    active_model = model or resolve_confidence_model(cfg)
    score_val = active_model.predict(
        directness=directness,
        provenance=provenance,
        agreement=agreement,
        relevance=relevance,
        temporal_consistency=temporal_consistency,
        contradiction=contradiction,
    )
    label = derive_label(
        score_val,
        high_threshold=active_model.high_threshold,
        medium_threshold=active_model.medium_threshold,
    )

    from app.schemas.confidence import ConfidenceScore, ConfidenceSignals

    signals = ConfidenceSignals(
        directness=round(directness, 2),
        provenance=round(provenance, 2),
        agreement=round(agreement, 2),
        relevance=round(relevance, 2),
        temporal_consistency=round(temporal_consistency, 2),
        contradiction=contradiction,
    )

    return ConfidenceScore(
        score=score_val,
        label=label,
        signals=signals,
    )
