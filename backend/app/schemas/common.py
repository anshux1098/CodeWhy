from __future__ import annotations

from enum import StrEnum
from typing import Final

GRAPH_NODE_CAP: Final[int] = 80


class Outcome(StrEnum):
    FULL = "full"
    PARTIAL = "partial"
    REFUSAL = "refusal"


class ReasonCode(StrEnum):
    ENTITY_NOT_FOUND = "entity_not_found"
    AMBIGUOUS_ENTITY = "ambiguous_entity"
    OUT_OF_SCOPE = "out_of_scope"
    NO_DECISION_PATH = "no_decision_path"
    NO_VERIFIED_QUOTE = "no_verified_quote"
    LOW_SCORE = "low_score"


class ConfidenceLabel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class EntityType(StrEnum):
    FILE = "File"
    MODULE = "Module"
    CONFIG_KEY = "ConfigKey"


class DecisionState(StrEnum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"
    UNRESOLVED = "UNRESOLVED"


class SourceType(StrEnum):
    PULL_REQUEST = "PullRequest"
    ISSUE = "Issue"
    DOCUMENT = "Document"
    COMMIT = "Commit"


class CitationKind(StrEnum):
    SOURCE = "SOURCE"
    INFERRED = "INFERRED"


class WhoToAskReason(StrEnum):
    AUTHOR = "author"
    REVIEWER = "reviewer"
    RECENT_CONTRIBUTOR = "recent_contributor"


class DependencyState(StrEnum):
    CONFIGURED = "configured"
    NOT_CONFIGURED = "not configured"
