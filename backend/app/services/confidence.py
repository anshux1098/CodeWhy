from __future__ import annotations

from typing import Final

from app.schemas.common import ConfidenceLabel

HIGH_THRESHOLD: Final[float] = 0.75
MEDIUM_THRESHOLD: Final[float] = 0.50
CONTRADICTION_SCORE_CAP: Final[float] = 0.70


def derive_label(score: float) -> ConfidenceLabel:
    if score >= HIGH_THRESHOLD:
        return ConfidenceLabel.HIGH
    if score >= MEDIUM_THRESHOLD:
        return ConfidenceLabel.MEDIUM
    return ConfidenceLabel.LOW
