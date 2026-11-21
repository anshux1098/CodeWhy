"""Declarative Gate Policy Engine, Per-Repo Profiles & Offline Replay (Point 6).

Separates pure Signal Collection from Declarative Policy Evaluation so gate
thresholds, tier restrictions, and refusal rules can be configured per-repository
(e.g. ``strict``, ``balanced``, ``exploratory``, or JSON policy files) and
shadow-evaluated via offline replay without changing code.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Optional, Sequence

from pydantic import BaseModel, Field

from app.config import Settings, settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GateSignals:
    """Pure, normalized signals collected before policy evaluation."""

    entity_resolved: bool
    entity_outcome: str
    entity_reason_code: Optional[str] = None
    entity_name: Optional[str] = None
    entity_error_detail: Optional[str] = None
    grounding_method: Optional[str] = None
    score_margin: Optional[float] = None
    decision_count: int = 0
    evidence_tier: str = "none"
    evidence_sufficiency: float = 0.0
    verified_quote_count: int = 0
    total_evidence_count: int = 0
    entailment_score: float = 0.0
    calibrated_relevance: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GatePolicyRule(BaseModel):
    """One declarative predicate rule evaluated against GateSignals."""

    gate_name: str
    signal: str
    op: Literal["eq", "ne", "lt", "lte", "gt", "gte", "in", "not_in"]
    value: Any
    outcome: Literal["pass", "partial", "refusal"]
    reason_code: str
    detail: str = ""
    enabled: bool = True

    def matches(self, signals: GateSignals) -> bool:
        if not self.enabled:
            return False
        actual = getattr(signals, self.signal, None)
        if self.op == "eq":
            return actual == self.value
        if self.op == "ne":
            return actual != self.value
        if self.op == "in":
            return actual in self.value
        if self.op == "not_in":
            return actual not in self.value
        if actual is None:
            return False
        if self.op == "lt":
            return float(actual) < float(self.value)
        if self.op == "lte":
            return float(actual) <= float(self.value)
        if self.op == "gt":
            return float(actual) > float(self.value)
        if self.op == "gte":
            return float(actual) >= float(self.value)
        return False


class GatePolicyProfile(BaseModel):
    """Named collection of declarative gate rules."""

    name: str
    description: str = ""
    min_relevance: float = 0.55
    rules: list[GatePolicyRule] = Field(default_factory=list)

    def with_min_relevance(self, threshold: float) -> GatePolicyProfile:
        updated_rules: list[GatePolicyRule] = []
        for rule in self.rules:
            if rule.gate_name == "G4" and rule.signal == "calibrated_relevance":
                updated_rules.append(rule.model_copy(update={"value": threshold}))
            else:
                updated_rules.append(rule)
        return self.model_copy(update={"min_relevance": threshold, "rules": updated_rules})


@dataclass(frozen=True)
class GateTelemetryEvent:
    """Structured telemetry record emitted for every policy evaluation (for replay/audit)."""

    profile: str
    outcome: str
    gate_name: str
    reason_code: Optional[str]
    signals: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyReplaySummary:
    """Comparison summary from replaying logged telemetry under a candidate policy."""

    profile_name: str
    total_events: int
    outcome_counts: dict[str, int]
    changed_decisions: int


# ---------------------------------------------------------------------------
# Built-in Policy Profiles
# ---------------------------------------------------------------------------

def _base_rules(
    *,
    min_relevance: float,
    allowed_tiers: list[str],
    min_sufficiency: float,
) -> list[GatePolicyRule]:
    return [
        GatePolicyRule(
            gate_name="G1",
            signal="entity_outcome",
            op="eq",
            value="refusal",
            outcome="refusal",
            reason_code="{entity_reason_code}",
            detail="{entity_error_detail}",
        ),
        GatePolicyRule(
            gate_name="G1",
            signal="entity_outcome",
            op="eq",
            value="ambiguous",
            outcome="refusal",
            reason_code="ambiguous_entity",
            detail="{entity_error_detail}",
        ),
        GatePolicyRule(
            gate_name="G1",
            signal="entity_resolved",
            op="eq",
            value=False,
            outcome="refusal",
            reason_code="entity_not_found",
            detail="Entity could not be resolved.",
        ),
        GatePolicyRule(
            gate_name="G2",
            signal="decision_count",
            op="lte",
            value=0,
            outcome="refusal",
            reason_code="no_decision_path",
            detail="No engineering decision path governs entity {entity_name}.",
        ),
        GatePolicyRule(
            gate_name="G2",
            signal="evidence_tier",
            op="not_in",
            value=allowed_tiers,
            outcome="refusal",
            reason_code="no_decision_path",
            detail="Evidence tier '{evidence_tier}' is disallowed by policy for {entity_name}.",
        ),
        GatePolicyRule(
            gate_name="G2",
            signal="evidence_sufficiency",
            op="lte",
            value=min_sufficiency,
            outcome="refusal",
            reason_code="no_decision_path",
            detail="Evidence sufficiency {evidence_sufficiency:.2f} does not meet policy minimum.",
        ),
        GatePolicyRule(
            gate_name="G3",
            signal="verified_quote_count",
            op="lte",
            value=0,
            outcome="partial",
            reason_code="no_verified_quote",
            detail="Change is recorded in history, but no verified rationale quote exists.",
        ),
        GatePolicyRule(
            gate_name="G4",
            signal="calibrated_relevance",
            op="lt",
            value=min_relevance,
            outcome="refusal",
            reason_code="low_score",
            detail="Calibrated evidence relevance {calibrated_relevance:.2f} is below threshold {threshold:.2f}.",
        ),
    ]


def builtin_profiles(default_min_score: float = 0.55) -> dict[str, GatePolicyProfile]:
    """Return built-in policy profiles: strict, balanced, and exploratory."""
    return {
        "balanced": GatePolicyProfile(
            name="balanced",
            description="Default production policy allowing Tier 1/2/3 multi-hop fallback.",
            min_relevance=default_min_score,
            rules=_base_rules(
                min_relevance=default_min_score,
                allowed_tiers=["direct", "module", "source"],
                min_sufficiency=0.0,
            ),
        ),
        "strict": GatePolicyProfile(
            name="strict",
            description="High-assurance policy requiring direct GOVERNS decisions and high relevance.",
            min_relevance=max(0.70, default_min_score),
            rules=_base_rules(
                min_relevance=max(0.70, default_min_score),
                allowed_tiers=["direct"],
                min_sufficiency=0.50,
            ),
        ),
        "exploratory": GatePolicyProfile(
            name="exploratory",
            description="Permissive onboarding/docs policy with lower relevance cutoff.",
            min_relevance=min(0.25, default_min_score),
            rules=_base_rules(
                min_relevance=min(0.25, default_min_score),
                allowed_tiers=["direct", "module", "source"],
                min_sufficiency=0.0,
            ),
        ),
    }


class PolicyRegistry(BaseModel):
    """Per-repository declarative policy registry loadable from JSON."""

    default_profile: str = "balanced"
    profiles: dict[str, GatePolicyProfile] = Field(default_factory=dict)
    repo_overrides: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_settings(cls, cfg: Optional[Settings] = None) -> PolicyRegistry:
        config = cfg or settings
        profiles = builtin_profiles(default_min_score=config.min_score)
        default_name = config.gate_policy_profile or "balanced"
        overrides: dict[str, str] = {}

        if config.gate_policy_path:
            path = Path(config.gate_policy_path)
            if path.exists():
                raw = json.loads(path.read_text(encoding="utf-8"))
                default_name = raw.get("default_profile", default_name)
                overrides = dict(raw.get("repo_overrides") or {})
                for pname, pdata in (raw.get("profiles") or {}).items():
                    profiles[pname] = GatePolicyProfile.model_validate({"name": pname, **pdata})

        return cls(
            default_profile=default_name,
            profiles=profiles,
            repo_overrides=overrides,
        )

    def for_repository(self, repository_id: Optional[str] = None) -> GatePolicyProfile:
        if repository_id and repository_id in self.repo_overrides:
            override_name = self.repo_overrides[repository_id]
            if override_name in self.profiles:
                return self.profiles[override_name]
        return self.profiles.get(self.default_profile) or self.profiles["balanced"]


# ---------------------------------------------------------------------------
# Declarative Evaluator & Offline Replay
# ---------------------------------------------------------------------------

def _render_template(template: str, signals: GateSignals, threshold: float) -> str:
    ctx = signals.to_dict()
    ctx["entity_reason_code"] = signals.entity_reason_code or "entity_not_found"
    ctx["entity_error_detail"] = signals.entity_error_detail or "Entity could not be resolved."
    ctx["entity_name"] = signals.entity_name or "unknown"
    ctx["threshold"] = threshold
    try:
        return template.format(**ctx)
    except Exception:  # noqa: BLE001
        return template


def evaluate_policy(
    signals: GateSignals,
    profile: GatePolicyProfile,
    *,
    telemetry_sink: Optional[Callable[[GateTelemetryEvent], None]] = None,
) -> tuple[str, Optional[str], str, Optional[str]]:
    """Evaluate declarative rules against signals.

    Returns ``(outcome, reason_code, gate_name, detail)`` and emits a structured
    ``GateTelemetryEvent``.
    """
    for rule in profile.rules:
        if rule.matches(signals):
            reason = _render_template(rule.reason_code, signals, profile.min_relevance)
            detail = _render_template(rule.detail, signals, profile.min_relevance)
            event = GateTelemetryEvent(
                profile=profile.name,
                outcome=rule.outcome,
                gate_name=rule.gate_name,
                reason_code=reason,
                signals=signals.to_dict(),
            )
            if telemetry_sink is not None:
                telemetry_sink(event)
            else:
                logger.debug("gate_policy_decision %s", event)
            return rule.outcome, reason, rule.gate_name, detail

    event = GateTelemetryEvent(
        profile=profile.name,
        outcome="pass",
        gate_name="ALL",
        reason_code=None,
        signals=signals.to_dict(),
    )
    if telemetry_sink is not None:
        telemetry_sink(event)
    else:
        logger.debug("gate_policy_decision %s", event)
    return "pass", None, "ALL", None


def replay_policy(
    events: Sequence[GateTelemetryEvent],
    candidate_profile: GatePolicyProfile,
) -> PolicyReplaySummary:
    """Offline shadow evaluation: replay historical telemetry against a candidate profile."""
    counts: dict[str, int] = {"pass": 0, "partial": 0, "refusal": 0}
    changed = 0
    for ev in events:
        sig = GateSignals(**ev.signals)
        outcome, _reason, _gate, _detail = evaluate_policy(sig, candidate_profile)
        counts[outcome] = counts.get(outcome, 0) + 1
        if outcome != ev.outcome:
            changed += 1
    return PolicyReplaySummary(
        profile_name=candidate_profile.name,
        total_events=len(events),
        outcome_counts=counts,
        changed_decisions=changed,
    )
