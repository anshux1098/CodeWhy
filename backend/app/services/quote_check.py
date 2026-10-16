from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Optional, Sequence

FALLBACK_RATIONALE_UNKNOWN: Final[str] = "change recorded, rationale unknown"

#: A quote longer than this is kept whole and flagged rather than cut. The value is
#: generous enough for a long parenthetical, because the alternative — a quote that
#: stops mid-sentence — reads as complete and is not.
MAX_QUOTE_CHARS: Final[int] = 500

#: Characters that close an aside without ending the sentence: the prose continues
#: after them. A quote ending here is still mid-sentence.
CLOSERS: Final[str] = ")]}\"'"

#: A sentence ends at one of these, followed by whitespace or the end of the text.
SENTENCE_END: Final[str] = ".!?…"


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
class QuoteCompletion:
    """A quote checked for ending on a sentence boundary.

    `status` is one of:
      complete        - already whole
      extended        - completed to the end of its sentence
      long_sentence   - the whole sentence is over the limit, kept whole and flagged
      quote_incomplete - the quote could not be located in the source at all
    """

    quote: str
    status: str
    #: True when the completed sentence is over MAX_QUOTE_CHARS and was kept anyway.
    over_limit: bool = False


def _locate(quote: str, source_text: str) -> Optional[tuple[int, int]]:
    """Where the quote sits in the source, tolerating whitespace differences.

    Returns the (start, end) offsets of the matched span, or None when the quote
    cannot be found at all. Whitespace is collapsed on both sides because the stored
    body carries CRLF while a quoted sentence is usually typed with plain spaces.
    """
    if quote in source_text:
        index = source_text.index(quote)
        return index, index + len(quote)

    # Walk the source on a whitespace-insensitive basis, keeping the offsets.
    def squash(text: str) -> tuple[str, list[int]]:
        chars: list[str] = []
        offsets: list[int] = []
        previous_space = True
        for position, char in enumerate(text):
            if char.isspace():
                if previous_space:
                    continue
                chars.append(" ")
                offsets.append(position)
                previous_space = True
            else:
                chars.append(char.lower())
                offsets.append(position)
                previous_space = False
        if chars and chars[-1] == " ":
            chars.pop()
            offsets.pop()
        return "".join(chars), offsets

    squashed_quote, quote_offsets = squash(quote)
    squashed_source, source_offsets = squash(source_text)
    index = squashed_source.find(squashed_quote)
    if index < 0:
        return None
    start = source_offsets[index]
    end_offset = index + len(squashed_quote) - 1
    end = source_offsets[end_offset] + 1
    return start, end


def _is_boundary(text: str, position: int) -> bool:
    """Whether a sentence terminator at `position` really ends a sentence.

    A terminator followed by a closing bracket still ends one: "support.)" closes a
    parenthetical. A terminator mid-word, as in a version number, does not.
    """
    if position >= len(text):
        return True
    if text[position] not in SENTENCE_END:
        return False
    cursor = position
    while cursor < len(text) and text[cursor] in SENTENCE_END:
        cursor += 1
    while cursor < len(text) and text[cursor] in CLOSERS:
        cursor += 1
    return cursor >= len(text) or text[cursor].isspace()


def _extent_at(text: str, end: int) -> Optional[int]:
    """Offset just past the sentence that finishes at `end`, if one does.

    Closing brackets between `end` and the terminator belong to the sentence, so
    "support.)" is one boundary rather than a terminator with a stray bracket.
    """
    index = end - 1
    while index >= 0 and text[index] in CLOSERS:
        index -= 1
    if index < 0 or text[index] not in SENTENCE_END:
        return None
    cursor = index
    while cursor < len(text) and text[cursor] in SENTENCE_END:
        cursor += 1
    while cursor < len(text) and text[cursor] in CLOSERS:
        cursor += 1
    if cursor < len(text) and not text[cursor].isspace():
        return None
    return cursor


def _next_sentence_extent(text: str, start: int) -> Optional[int]:
    """Offset just past the next sentence boundary at or after `start`."""
    for index in range(max(0, start), len(text)):
        if text[index] in SENTENCE_END and _is_boundary(text, index):
            cursor = index
            while cursor < len(text) and text[cursor] in SENTENCE_END:
                cursor += 1
            while cursor < len(text) and text[cursor] in CLOSERS:
                cursor += 1
            return cursor
    return None


def complete_quote(quote: str, source_text: str) -> QuoteCompletion:
    """Complete a quote to the end of its sentence, never cutting inside one.

    A model asked to quote verbatim sometimes returns a prefix of the sentence it
    means, and the prefix still verifies as a substring, so nothing downstream can
    tell a whole quote from a cut one. This resolves the sentence the quote sits in
    and takes all of it.
    """
    clean = quote.strip()
    if not clean or not source_text:
        return QuoteCompletion(quote=clean, status="quote_incomplete")

    located = _locate(clean, source_text)
    if located is None:
        return QuoteCompletion(quote=clean, status="quote_incomplete")
    start, end = located

    boundary = _extent_at(source_text, end)
    if boundary is not None:
        if boundary <= end:
            return QuoteCompletion(quote=clean, status="complete")
        target = boundary
    else:
        target = _next_sentence_extent(source_text, end)
        if target is None:
            # The text simply runs out; there is nothing to complete the quote to.
            return QuoteCompletion(quote=clean, status="complete")

    extended = source_text[start:target].strip()
    if len(extended) > MAX_QUOTE_CHARS:
        # Kept whole and flagged. Cutting here would produce exactly the defect
        # this function exists to prevent.
        return QuoteCompletion(quote=extended, status="long_sentence", over_limit=True)
    return QuoteCompletion(quote=extended, status="extended")


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


def quote_match_rung(quote: str, source_text: str) -> str:
    """Deepest normalization rung at which `quote` matches `source_text`.

    Reporting only. It mirrors the ladder `verify_quote` walks but never decides
    whether a quote is accepted; a rejected candidate is classified here so a run
    can record what was proposed and where it stopped matching. Returns one of
    ``exact``, ``case``, ``whitespace``, ``markdown``, ``none`` (matched no rung) or
    ``empty`` (nothing to compare).
    """
    clean_quote = quote.strip()
    if not clean_quote or not source_text or not source_text.strip():
        return "empty"
    if clean_quote in source_text:
        return "exact"
    if clean_quote.lower() in source_text.lower():
        return "case"
    if normalize_whitespace(clean_quote).lower() in normalize_whitespace(source_text).lower():
        return "whitespace"
    if normalize_for_quote_check(clean_quote) in normalize_for_quote_check(source_text):
        return "markdown"
    return "none"


def deepest_rung_over_sources(quote: str, source_texts: Sequence[str]) -> str:
    """Best rung any of `source_texts` reaches for `quote`, for reporting."""
    order = {"exact": 4, "case": 3, "whitespace": 2, "markdown": 1, "none": 0, "empty": -1}
    best = "empty"
    for text in source_texts:
        rung = quote_match_rung(quote, text)
        if order[rung] > order[best]:
            best = rung
    return best
