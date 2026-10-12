from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import ConfidenceLabel
from app.services.confidence import derive_label


class ConfidenceSignals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    directness: float = Field(ge=0.0, le=1.0)
    provenance: float = Field(ge=0.0, le=1.0)
    agreement: float = Field(ge=0.0, le=1.0)
    relevance: float = Field(ge=0.0, le=1.0)
    temporal_consistency: float = Field(ge=0.0, le=1.0)
    contradiction: Literal[0.0, 1.0]


class ConfidenceScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float = Field(ge=0.0, le=1.0)
    label: ConfidenceLabel
    signals: ConfidenceSignals

    @model_validator(mode="before")
    @classmethod
    def _fill_or_check_label(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        score = data.get("score")
        if score is None:
            return data
        try:
            derived = derive_label(float(score))
        except (TypeError, ValueError):
            return data
        supplied = data.get("label")
        if supplied is None:
            return {**data, "label": derived.value}
        if ConfidenceLabel(supplied) is not derived:
            raise ValueError(
                f"R4_LABEL_MISMATCH: label {supplied!r} does not match score {score} "
                f"which derives {derived.value!r}"
            )
        return data