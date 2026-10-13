from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Optional, Sequence

FALLBACK_RATIONALE_UNKNOWN: Final[str] = "change recorded, rationale unknown"


def normalize_whitespace(text: str) -> str:
    """Collapses runs of whitespace, tabs, and newlines into single spaces."""
    return " ".join(text.split())


def strip_markdown(text: str) -> str:
    """Removes common markdown formatting characters to prevent quote mismatches."""
    # Convert markdown links [text](url) to text
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    # Remove bold, italics, strikethrough: **, *, __, _, ~~
    text = re.sub(r"[*_~`]", "", text)
    # Remove blockquote markers
    text = re.sub(r"^\s*>\s*", "", text, flags=re.MULTILINE)
    # Remove markdown header hashes
    text = re.sub(r"^\s*#+\s*", "", text, flags=re.MULTILINE)
    return text


def normalize_for_quote_check(text: str) -> str:
    """Full normalization pipeline: strip markdown formatting, collapse whitespace, lower-case."""
    return normalize_whitespace(strip_markdown(text)).lower()


@dataclass(frozen=True)
class QuoteVerificationResult:
    """Result of a verbatim substring check."""

    is_verified: bool
    quote: str
    failure_reason: Optional[str] = None


def verify_quote(quote: str, source_text: str) -> QuoteVerificationResult:
    """Verifies that `quote` is a legitimate substring of `source_text`.

    Follows the spec:
    1. Exact substring check.
    2. Case-insensitive substring check.
    3. Whitespace-normalized substring check.
    4. Markdown-stripped and normalized substring check.
    """
    clean_quote = quote.strip()
    if not clean_quote:
        return QuoteVerificationResult(
            is_verified=False,
            quote=quote,
            failure_reason="Quote is empty or whitespace-only",
        )

    if not source_text or not source_text.strip():
        return QuoteVerificationResult(
            is_verified=False,
            quote=clean_quote,
            failure_reason="Source text is empty",
        )

    # 1. Exact match
    if clean_quote in source_text:
        return QuoteVerificationResult(is_verified=True, quote=clean_quote)

    # 2. Case-insensitive match
    if clean_quote.lower() in source_text.lower():
        return QuoteVerificationResult(is_verified=True, quote=clean_quote)

    # 3. Whitespace-normalized match
    norm_quote = normalize_whitespace(clean_quote).lower()
    norm_source = normalize_whitespace(source_text).lower()
    if norm_quote in norm_source:
        return QuoteVerificationResult(is_verified=True, quote=clean_quote)

    # 4. Markdown-stripped and normalized match
    md_norm_quote = normalize_for_quote_check(clean_quote)
    md_norm_source = normalize_for_quote_check(source_text)
    if md_norm_quote in md_norm_source:
        return QuoteVerificationResult(is_verified=True, quote=clean_quote)

    return QuoteVerificationResult(
        is_verified=False,
        quote=clean_quote,
        failure_reason="Quote not found in source text after normalization",
    )


def verify_quote_against_sources(
    quote: str,
    source_texts: Sequence[str],
) -> QuoteVerificationResult:
    """Verifies if quote appears in any of the provided source texts (e.g. title, body, comments, diff)."""
    for text in source_texts:
        res = verify_quote(quote, text)
        if res.is_verified:
            return res

    return QuoteVerificationResult(
        is_verified=False,
        quote=quote.strip(),
        failure_reason="Quote not found in any source section",
    )
