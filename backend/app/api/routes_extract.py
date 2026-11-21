from __future__ import annotations

import time
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import get_settings, get_source
from app.config import Settings
from app.prompts.extract_decision import detect_injection_attempt
from app.providers.llm_provider import get_llm_provider
from app.services.data_source import DataSource
from app.services.extraction import (
    ExtractionSchemaRejected,
    extract_decisions_from_source,
    last_rejected_quotes,
)

router = APIRouter(tags=["extract"])


class PreviewComment(BaseModel):
    author: Optional[str] = None
    body: str
    createdAt: Optional[str] = None


class ExtractPreviewRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(default="", max_length=50_000)
    source_type: Literal["pull_request", "issue", "doc"] = "pull_request"
    author: Optional[str] = None
    comments: list[PreviewComment] = Field(default_factory=list)


@router.post(
    "/extract/preview",
    summary="Live Extraction & Quote Verification Sandbox",
)
def preview_extraction(
    request: ExtractPreviewRequest,
    source: DataSource = Depends(get_source),
    cfg: Settings = Depends(get_settings),
) -> dict:
    """Run prompt-injection screening, LLM extraction, and verbatim quote verification live."""
    t0 = time.perf_counter()
    combined_text = "\n".join(
        [request.title, request.body] + [c.body for c in request.comments if c.body]
    )
    injection_detected = detect_injection_attempt(combined_text)

    provider = getattr(source, "provider", None) or get_llm_provider(cfg=cfg)
    schema_error: Optional[str] = None
    try:
        records = extract_decisions_from_source(
            provider=provider,
            source_id="sandbox:preview#0",
            source_type=request.source_type,
            source_url="https://github.com/sandbox/preview",
            repo="sandbox/preview",
            title=request.title,
            body=request.body,
            author=request.author,
            comments=[c.model_dump(exclude_none=True) for c in request.comments],
        )
    except ExtractionSchemaRejected as exc:
        records = []
        schema_error = str(exc)
    rejected = last_rejected_quotes()
    latency_ms = round((time.perf_counter() - t0) * 1000, 1)

    return {
        "injection_detected": injection_detected,
        "schema_error": schema_error,
        "decisions": [
            {
                "id": dec.id,
                "summary": dec.summary,
                "decision_type": dec.decision_type,
                "rationale": dec.rationale,
                "quote_verified": dec.quote_verified,
                "reason_unstated": dec.reason_unstated,
                "evidence": [
                    {
                        "quote": ev.quote,
                        "claim": ev.claim,
                        "author": ev.author,
                        "quote_verified": ev.quote_verified,
                    }
                    for ev in dec.evidence
                ],
            }
            for dec in records
        ],
        "rejected_quotes": rejected,
        "latency_ms": latency_ms,
        "fixture": not bool(getattr(provider, "is_real", False)),
    }
