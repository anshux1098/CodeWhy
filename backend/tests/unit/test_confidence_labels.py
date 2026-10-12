from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.common import ConfidenceLabel
from app.schemas.confidence import ConfidenceScore, ConfidenceSignals
from app.services.confidence import derive_label


def signals(contradiction: float = 0.0) -> ConfidenceSignals:
    return ConfidenceSignals(
        directness=1.0,
        provenance=0.8,
        agreement=0.4,
        relevance=0.9,
        temporal_consistency=1.0,
        contradiction=contradiction,
    )


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.49, ConfidenceLabel.LOW),
        (0.50, ConfidenceLabel.MEDIUM),
        (0.74, ConfidenceLabel.MEDIUM),
        (0.75, ConfidenceLabel.HIGH),
        (0.0, ConfidenceLabel.LOW),
        (1.0, ConfidenceLabel.HIGH),
    ],
)
def test_derive_label_boundaries(score: float, expected: ConfidenceLabel) -> None:
    assert derive_label(score) is expected


@pytest.mark.parametrize(
    ("score", "expected"),
    [(0.49, "LOW"), (0.50, "MEDIUM"), (0.74, "MEDIUM"), (0.75, "HIGH")],
)
def test_omitted_label_is_derived(score: float, expected: str) -> None:
    confidence = ConfidenceScore(score=score, signals=signals())
    assert confidence.label.value == expected


def test_supplied_matching_label_is_accepted() -> None:
    confidence = ConfidenceScore(score=0.75, label="HIGH", signals=signals())
    assert confidence.label is ConfidenceLabel.HIGH


def test_supplied_mismatched_label_is_rejected() -> None:
    with pytest.raises(ValidationError) as excinfo:
        ConfidenceScore(score=0.42, label="HIGH", signals=signals())
    assert "R4_LABEL_MISMATCH" in str(excinfo.value)


def test_signals_must_be_between_zero_and_one() -> None:
    with pytest.raises(ValidationError):
        ConfidenceSignals(directness=1.5)


def test_missing_signals_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ConfidenceScore(score=0.9)