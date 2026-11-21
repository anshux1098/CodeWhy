from __future__ import annotations

import hashlib
import logging
import re
import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

EMAIL_SHAPED = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

from app.prompts.extract_decision import build_extraction_prompt
from app.providers.llm_provider import BaseLLMProvider, LLMSchemaValidationError
from app.schemas.common import DecisionState
from app.services.quote_check import (
    FALLBACK_RATIONALE_UNKNOWN,
    MAX_QUOTE_CHARS,
    complete_quote,
    deepest_rung_over_sources,
    verify_quote,
)

logger = logging.getLogger(__name__)

EXTRACTION_VERSION: Final[str] = "v1"

#: Universal non-library directories dropped from entity attribution so tests,
#: docs, CI scripts, build tooling, and vendored third-party bundles never
#: pollute a decision's GOVERNS edges.
NON_LIBRARY_DIRS: frozenset[str] = frozenset({
    "test", "tests", "testing", "__tests__", "spec",
    "doc", "docs", "documentation",
    "example", "examples", "sample", "samples",
    "benchmark", "benchmarks",
    "script", "scripts",
    "dummyserver",
    "packages", "vendor", "third_party", "node_modules", "dist", "build",
    ".github", ".circleci", ".gitlab", "_travis",
})

NON_LIBRARY_SUFFIXES: frozenset[str] = frozenset({
    ".pyi", ".md", ".rst", ".txt", ".adoc", ".markdown",
    ".sh", ".bat", ".ps1", ".lock",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2",
})

NON_LIBRARY_FILENAMES: frozenset[str] = frozenset({
    "setup.py", "noxfile.py", "conftest.py", "tox.ini",
    "pyproject.toml", "setup.cfg", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
})


def is_library_source_file(
    path: str,
    excluded_globs: Sequence[str] = (),
) -> bool:
    """Return True when a path is part of the repository's own source code (repo-agnostic)."""
    clean = path.strip().replace("\\", "/").lstrip("./")
    if not clean:
        return False
    parts = [p for p in clean.split("/") if p]
    if not parts:
        return False
    # Root-level files (e.g. setup.py, noxfile.py, CHANGES.rst) are build/meta, not package source
    if len(parts) == 1:
        return False
    filename = parts[-1]
    if filename in NON_LIBRARY_FILENAMES:
        return False
    lower_name = filename.lower()
    if any(lower_name.endswith(sfx) for sfx in NON_LIBRARY_SUFFIXES):
        return False
    if lower_name.startswith("test_") or lower_name.endswith("_test.py") or ".test." in lower_name or ".spec." in lower_name:
        return False
    dir_parts = {p.lower() for p in parts[:-1]}
    if dir_parts & NON_LIBRARY_DIRS:
        return False
    if any(p.startswith((".", "_")) and p != "__init__.py" for p in parts[:-1]):
        return False
    if excluded_globs:
        from fnmatch import fnmatch
        if any(fnmatch(clean, pat) for pat in excluded_globs):
            return False
    return True


def filter_affected_entities(
    changed_files: Sequence[str],
    config_keys: Sequence[str] = (),
    *,
    excluded_globs: Sequence[str] = (),
) -> list[str]:
    """The entities that explain a decision, narrowed to what actually matters.

    Works for any repository layout (`src/urllib3/`, `alembic/`, `src/flask/`, `app/`,
    etc.) while excluding tests, docs, build scripts, and vendored third-party code.
    A configuration key is kept as given — the caller supplies only keys read from a
    target file, so a key that merely appears in some diff is not attributed here.

    The result is sorted and de-duplicated, so the same set is stored however the
    payload happened to order it.
    """
    kept: set[str] = set()
    for name in changed_files:
        if not isinstance(name, str):
            continue
        candidate = name.strip()
        if is_library_source_file(candidate, excluded_globs=excluded_globs):
            kept.add(candidate)
    for key in config_keys:
        if isinstance(key, str) and key.strip():
            kept.add(key.strip())
    return sorted(kept)


# ---------------------------------------------------------------------------
# Decision Types
# ---------------------------------------------------------------------------

class DecisionType(StrEnum):
    ARCHITECTURE = "Architecture"
    RELIABILITY = "Reliability"
    PERFORMANCE = "Performance"
    SECURITY = "Security"
    COMPATIBILITY = "Compatibility"
    CONFIGURATION = "Configuration"
    MIGRATION = "Migration"
    TESTING = "Testing"
    OPERATIONAL_BEHAVIOR = "Operational behavior"
    OTHER = "Other"


# ---------------------------------------------------------------------------
# LLM Extraction Input & Output Schemas (Strict Pydantic Models)
# ---------------------------------------------------------------------------

class RawEvidenceItem(BaseModel):
    """Evidence quote produced by LLM."""
    model_config = ConfigDict(extra="ignore")

    quote: str = Field(description="Exact verbatim quote from the source text")
    claim: str = Field(default="", description="The specific claim or rationale supported by this quote")
    timestamp: Optional[str] = None


class RawCandidateDecision(BaseModel):
    """Candidate decision output schema produced by LLM."""
    model_config = ConfigDict(extra="ignore")

    summary: str = Field(description="Concise description of the engineering decision")
    decision_type: DecisionType = Field(default=DecisionType.OTHER)
    rationale: Optional[str] = Field(default=None, description="The reason or technical motivation for the decision")
    alternatives_considered: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    supporting_evidence: list[RawEvidenceItem] = Field(default_factory=list)
    opposing_evidence: list[RawEvidenceItem] = Field(default_factory=list)
    explicit_reversal_language: bool = Field(default=False)
    unknown_fields: list[str] = Field(default_factory=list)

class LLMExtractionPayload(BaseModel):
    """Top-level LLM completion schema.

    `extra="forbid"` is deliberate. With the default `extra="ignore"` a model that
    returns a flat object instead of `{"decisions": [...]}` has its fields silently
    discarded, `decisions` falls back to an empty list, and the run reports success
    with no decisions extracted. Refusing the reply turns that silent loss into a
    recorded failure.
    """

    model_config = ConfigDict(extra="forbid")

    no_decision: bool = Field(default=False, description="True if no deliberate engineering decision exists")
    #: Required, with no default. `{"decisions": []}` is how a model says there is
    #: nothing to extract; a reply that omits the key entirely has not followed the
    #: contract and is rejected rather than read as "no decision".
    decisions: list[RawCandidateDecision]


#: The JSON schema sent as `response_format` where the endpoint supports it, so the
#: model is constrained to the agreed shape instead of being asked politely in prose.
#: Generated from the model so the two cannot drift apart.
EXTRACTION_JSON_SCHEMA: Final[dict[str, Any]] = LLMExtractionPayload.model_json_schema()


class ExtractionSchemaRejected(RuntimeError):
    """Raised when a reply cannot be read as the agreed extraction shape.

    Carries the key names that arrived so the operator can see what the model
    actually sent. Values are never included: a rejected reply may quote
    untrusted repository text, and that text does not belong in a log line.
    """

    #: Recorded as the failure status so the run summary can count it separately
    #: from a transport failure or a genuine absence of decisions.
    status = "schema_rejected"

    def __init__(
        self,
        source_id: str,
        received_keys: Sequence[str],
        reason: str,
        finish_reason: str = "",
    ) -> None:
        self.source_id = source_id
        self.received_keys = list(received_keys)
        self.reason = reason
        self.finish_reason = finish_reason
        super().__init__(
            f"extraction for {source_id} was rejected: {reason}; "
            f"top-level keys received: {', '.join(self.received_keys) or '(none)'} "
            f"(values are not logged); finish_reason={finish_reason or 'unknown'}"
        )


# ---------------------------------------------------------------------------
# Code-Constructed Entity Models (Saved to SQLite and Graph)
# ---------------------------------------------------------------------------

@dataclass
class VerifiedEvidence:
    """Evidence record verified by code against source text."""

    id: str
    decision_id: str
    source_id: str
    source_type: str
    source_url: str
    quote: str
    author: Optional[str]
    timestamp: Optional[str]
    classification: Literal["explicit", "inferred"]
    claim: str
    quote_verified: bool


@dataclass
class ExtractedDecisionRecord:
    """Fully formed decision record enriched by code."""

    id: str
    source_id: str
    repo: str
    summary: str
    decision_type: str
    rationale: Optional[str]
    state: DecisionState
    alternatives_considered: list[str]
    constraints: list[str]
    affected_entities: list[str]
    source_references: list[str]
    decision_date: Optional[str]
    source_author: Optional[str]
    explicit_reversal_language: bool
    unknown_fields: list[str]
    evidence: list[VerifiedEvidence]
    quote_verified: bool
    #: True when the source never said why and the model supplied no rationale.
    #: The decision still stands as a record that something changed; it just cannot
    #: be presented as an explained choice.
    reason_unstated: bool
    extraction_version: str
    content_hash: str
    created_at: str


# ---------------------------------------------------------------------------
# ID Generation & Hashing Helpers
# ---------------------------------------------------------------------------

def make_decision_id(source_id: str, extraction_version: str, index: int) -> str:
    """Deterministic decision ID generated by code from source_id, version, and index."""
    raw = f"{source_id}:{extraction_version}:{index}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:16]
    return f"dec_{digest}"


def make_evidence_id(decision_id: str, index: int, quote: str) -> str:
    """Deterministic evidence ID generated by code."""
    raw = f"{decision_id}:{index}:{quote}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:16]
    return f"ev_{digest}"


def compute_content_hash(text: str) -> str:
    """Computes SHA-256 digest of source content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Extraction Engine
# ---------------------------------------------------------------------------

def summarise_injection_flags(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Count flagged sources for logging.

    Only counts are returned. The offending text never enters a log line, so an
    attack payload cannot smuggle itself into the audit trail.
    """
    return {
        "sources_total": len(rows),
        "sources_flagged": sum(1 for row in rows if row.get("injection_detected")),
    }


def attribution_for(author: Optional[str]) -> Optional[str]:
    """Normalise an author taken from the ingested record.

    Author identity is a factual claim, so it is read from the source payload and
    never from model output. A value that looks like an email address is dropped
    rather than stored or returned, because a login is the only identifier the
    system is prepared to hold.
    """
    if not author:
        return None
    cleaned = author.strip()
    if not cleaned or EMAIL_SHAPED.search(cleaned):
        return None
    return cleaned


_THREAD_LOCAL = threading.local()


def _last_call_store() -> dict[str, Any]:
    store = getattr(_THREAD_LOCAL, "last_call", None)
    if store is None:
        store = {}
        _THREAD_LOCAL.last_call = store
    return store


def _last_rejected_store() -> list[dict[str, Any]]:
    store = getattr(_THREAD_LOCAL, "last_rejected", None)
    if store is None:
        store = []
        _THREAD_LOCAL.last_rejected = store
    return store


def last_call_metadata() -> dict[str, Any]:
    """Model, mode, finish reason and tokens for the most recent extraction call."""
    return dict(_last_call_store())


def last_rejected_quotes() -> list[dict[str, Any]]:
    """Candidate quotes dropped by the most recent extraction call (defensive copy)."""
    return [dict(item) for item in _last_rejected_store()]


def extract_decisions_from_source(
    provider: BaseLLMProvider,
    source_id: str,
    source_type: str,
    source_url: str,
    repo: str,
    title: str,
    body: str,
    author: Optional[str] = None,
    created_at: Optional[str] = None,
    diff_or_patch: Optional[str] = None,
    comments: Sequence[dict[str, str]] = (),
    changed_files: Sequence[str] = (),
    config_keys: Sequence[str] = (),
    source_references: Sequence[str] = (),
    extraction_version: str = EXTRACTION_VERSION,
) -> list[ExtractedDecisionRecord]:
    """Runs LLM extraction and applies code-level validation and enrichment.

    Enforces the following rules from the specification:
    1. Delimited prompt structure (repository data is untrusted).
    2. Code produces decision_id, affected_entities, dates, author, and hashes.
    3. Verbatim quote verification: every candidate quote is checked against source text.
       Quotes that fail are dropped.
    4. If no verified quote remains for a decision, it is marked as
       "change recorded, rationale unknown" with quote_verified=False.
    """
    # 1. Compile tagged source sections for quote verification & per-section attribution
    tagged_sections: list[tuple[str, Optional[str], Optional[str]]] = [
        (title or "", author, created_at),
        (body or "", author, created_at),
    ]
    for c in comments:
        c_body = c.get("body")
        if c_body:
            c_author = c.get("author") or author
            c_ts = c.get("createdAt") or c.get("submittedAt") or created_at
            tagged_sections.append((c_body, c_author, c_ts))
    if diff_or_patch:
        tagged_sections.append((diff_or_patch, author, created_at))

    all_source_texts = [sec_text for sec_text, _, _ in tagged_sections]

    full_text_corpus = "\n".join(all_source_texts)
    content_hash = compute_content_hash(full_text_corpus)
    _LAST_REJECTED = _last_rejected_store()
    _LAST_CALL = _last_call_store()
    _LAST_REJECTED.clear()

    # 2. Build prompt
    system_prompt, user_prompt = build_extraction_prompt(
        source_type=source_type,
        source_id=source_id,
        title=title,
        body=body,
        diff_or_patch=diff_or_patch,
        comments=comments,
    )

    # 3. Call LLM for structured output
    try:
        parsed, response = provider.complete_structured(
            schema=LLMExtractionPayload,
            prompt=user_prompt,
            system=system_prompt,
            response_json_schema=EXTRACTION_JSON_SCHEMA,
        )
        logger.info(
            "extraction for %s: response_format=%s finish_reason=%s",
            source_id,
            getattr(response, "response_format_mode", "unknown"),
            getattr(response, "finish_reason", "") or "unknown",
        )
        _LAST_CALL.clear()
        _LAST_CALL.update({
            "model": getattr(response, "model", "") or "",
            "response_format_mode": getattr(response, "response_format_mode", "") or "",
            "finish_reason": getattr(response, "finish_reason", "") or "",
            "tokens": int(getattr(response, "total_tokens", 0) or 0),
        })
    except LLMSchemaValidationError as exc:
        # The reply was text but not the agreed shape. That is a rejection, and the
        # operator has to see it; returning an empty list would report success.
        _LAST_CALL.clear()
        _LAST_CALL.update({
            "model": "",
            "response_format_mode": "",
            "finish_reason": exc.finish_reason,
            "tokens": 0,
        })
        raise ExtractionSchemaRejected(
            source_id=source_id,
            received_keys=exc.received_keys,
            reason=exc.reason,
            finish_reason=exc.finish_reason,
        ) from exc
    except Exception as exc:
        logger.error("LLM provider error extracting from %s: %s", source_id, exc)
        raise

    if parsed.no_decision or not parsed.decisions:
        return []

    # 4. Code enrichment and quote verification
    records: list[ExtractedDecisionRecord] = []
    affected_entities = filter_affected_entities(changed_files, config_keys)

    for idx, raw_dec in enumerate(parsed.decisions):
        dec_id = make_decision_id(source_id, extraction_version, idx)

        # Verify candidate supporting quotes against tagged sections for accurate attribution
        verified_evidence: list[VerifiedEvidence] = []
        for ev_idx, raw_ev in enumerate(raw_dec.supporting_evidence):
            q_res = None
            matched_author: Optional[str] = author
            matched_ts: Optional[str] = created_at
            matched_section_text: str = "\n".join(all_source_texts)
            for sec_text, sec_author, sec_ts in tagged_sections:
                res = verify_quote(raw_ev.quote, sec_text)
                if res.is_verified:
                    q_res = res
                    matched_author = sec_author or author
                    matched_ts = sec_ts or created_at
                    matched_section_text = sec_text
                    break
            if q_res is not None and q_res.is_verified:
                completed = complete_quote(q_res.quote, matched_section_text)
                if completed.status == "quote_incomplete":
                    logger.debug(
                        "Dropped quote for %s: could not be completed to a whole sentence",
                        dec_id,
                    )
                    _LAST_REJECTED.append({
                        "decision_id": dec_id,
                        "decision_summary": raw_dec.summary.strip(),
                        "candidate": q_res.quote,
                        "failed_rung": "complete_quote",
                        "failure_reason": "could not be completed to a whole sentence",
                        "claim": raw_ev.claim,
                    })
                    continue
                if completed.status == "long_sentence":
                    logger.info(
                        "Quote for %s kept whole at %d characters, over the %d limit: %s",
                        dec_id, len(completed.quote), MAX_QUOTE_CHARS,
                        source_id,
                    )
                elif completed.status == "extended":
                    logger.debug(
                        "Completed a cut quote for %s: %r -> %r",
                        dec_id, q_res.quote, completed.quote,
                    )
                ev_id = make_evidence_id(dec_id, ev_idx, completed.quote)
                verified_evidence.append(
                    VerifiedEvidence(
                        id=ev_id,
                        decision_id=dec_id,
                        source_id=source_id,
                        source_type=source_type,
                        source_url=source_url,
                        quote=completed.quote,
                        author=attribution_for(matched_author),
                        timestamp=raw_ev.timestamp or matched_ts,
                        classification="explicit",
                        claim=raw_ev.claim,
                        quote_verified=True,
                    )
                )
            else:
                logger.debug(
                    "Dropped unverified quote for %s: %r",
                    dec_id,
                    raw_ev.quote,
                )
                _LAST_REJECTED.append({
                    "decision_id": dec_id,
                    "decision_summary": raw_dec.summary.strip(),
                    "candidate": raw_ev.quote,
                    "failed_rung": deepest_rung_over_sources(raw_ev.quote, all_source_texts),
                    "failure_reason": "Quote not found in any source section",
                    "claim": raw_ev.claim,
                })

        has_verified_quotes = len(verified_evidence) > 0

        # Enforce rule: if no verified quote remains, summary is "change recorded, rationale unknown"
        if has_verified_quotes:
            summary = raw_dec.summary.strip()
            rationale = raw_dec.rationale.strip() if raw_dec.rationale else None
            quote_verified = True
        else:
            summary = FALLBACK_RATIONALE_UNKNOWN
            rationale = None
            quote_verified = False

        # Decided here rather than asked of the model: the flag is a statement about
        # what the record contains, not something inference should be able to assert
        # about itself.
        reason_unstated = not bool(rationale)

        records.append(
            ExtractedDecisionRecord(
                id=dec_id,
                source_id=source_id,
                repo=repo,
                summary=summary,
                decision_type=raw_dec.decision_type.value,
                rationale=rationale,
                state=DecisionState.ACTIVE,
                alternatives_considered=raw_dec.alternatives_considered,
                constraints=raw_dec.constraints,
                affected_entities=affected_entities,
                source_references=list(source_references),
                decision_date=created_at,
                source_author=attribution_for(author),
                explicit_reversal_language=raw_dec.explicit_reversal_language,
                unknown_fields=raw_dec.unknown_fields,
                evidence=verified_evidence,
                quote_verified=quote_verified,
                reason_unstated=reason_unstated,
                extraction_version=extraction_version,
                content_hash=content_hash,
                created_at=created_at or "",
            )
        )

    return records
