"""Unit tests for Point 5: Learned / Calibrated Confidence Scoring Model."""

from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.schemas.common import ConfidenceLabel
from app.services.confidence import (
    CalibratedConfidenceModel,
    ConfidenceExample,
    calculate_confidence,
    compute_brier_score,
)


def _sample_benchmark() -> list[ConfidenceExample]:
    return [
        # Correct, well-grounded answers
        ConfidenceExample(1.0, 0.9, 0.9, 0.92, 1.0, 0.0, is_correct=1),
        ConfidenceExample(1.0, 0.8, 0.8, 0.88, 1.0, 0.0, is_correct=1),
        ConfidenceExample(0.9, 0.8, 0.7, 0.85, 0.9, 0.0, is_correct=1),
        ConfidenceExample(1.0, 0.9, 0.6, 0.82, 1.0, 0.0, is_correct=1),
        # Incorrect / hallucinated / contradicted answers
        ConfidenceExample(0.3, 0.4, 0.2, 0.35, 0.5, 1.0, is_correct=0),
        ConfidenceExample(0.4, 0.5, 0.2, 0.40, 0.6, 0.0, is_correct=0),
        ConfidenceExample(0.2, 0.3, 0.1, 0.25, 0.4, 1.0, is_correct=0),
        ConfidenceExample(0.4, 0.4, 0.3, 0.30, 0.5, 0.0, is_correct=0),
    ]


def test_calibrated_model_fits_benchmark_with_low_brier_and_ece() -> None:
    examples = _sample_benchmark()
    model = CalibratedConfidenceModel.fit(examples)
    report = model.evaluate(examples, n_bins=4)

    assert model.mode == "logistic"
    assert report.brier_score < 0.08
    assert report.ece < 0.20

    high = calculate_confidence(1.0, 0.9, 0.9, 0.92, 1.0, 0.0, model=model)
    low = calculate_confidence(0.3, 0.4, 0.2, 0.35, 0.5, 1.0, model=model)
    assert high.label == ConfidenceLabel.HIGH
    assert low.label == ConfidenceLabel.LOW
    assert high.score > low.score + 0.50


def test_calibrated_model_roundtrips_json_and_loads_from_settings(tmp_path: Path) -> None:
    model = CalibratedConfidenceModel.fit(_sample_benchmark())
    artifact = tmp_path / "confidence_model.json"
    model.save(artifact)

    loaded = CalibratedConfidenceModel.load(artifact)
    assert loaded == model

    cfg = Settings(_env_file=None, offline=True, confidence_model_path=str(artifact))
    scored = calculate_confidence(1.0, 0.9, 0.9, 0.92, 1.0, 0.0, cfg=cfg)
    assert scored.label == ConfidenceLabel.HIGH
    assert scored.score == model.predict(
        directness=1.0, provenance=0.9, agreement=0.9, relevance=0.92, temporal_consistency=1.0, contradiction=0.0
    )


def test_contradiction_cap_enforced_even_in_logistic_mode() -> None:
    model = CalibratedConfidenceModel.fit(_sample_benchmark())
    scored = calculate_confidence(1.0, 1.0, 1.0, 1.0, 1.0, 1.0, model=model)
    assert scored.score <= 0.70
    assert scored.label != ConfidenceLabel.HIGH


def test_brier_score_accuracy() -> None:
    assert compute_brier_score([1.0, 0.0], [1, 0]) == 0.0
    assert compute_brier_score([0.5, 0.5], [1, 0]) == 0.25
