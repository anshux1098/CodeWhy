"""A quote must not stop in the middle of a sentence.

Investigation of the stored #3466 evidence against the real PR text:

  stored : "Unfortunately, we realized after working on them that we can't really use
            those new settings. curl also does not implement them."
  source : "...those new settings. curl also does not implement them. See
            https://github.com/urllib3/urllib3/issues/3306#issuecomment-2320997012
            for details."

The #3466 quote is not cut: it ends on a full stop and what follows begins a new
sentence. Nothing in this codebase caps or normalises quote length, so the stage
that produced it was the model.

The real cut is on #1448, where the model returned:

  "(I noticed this because the v2 branch dropped supports_set_ciphers when dropping
   Python 2.6 support."

and the source continues with ")". The closing bracket was dropped. `verify_quote`
accepted it, because a prefix of a sentence is still a substring, so nothing in the
pipeline could tell. A quote that reads as complete and is not is worse than one
that is obviously truncated.
"""

from __future__ import annotations

import pytest

from app.services.quote_check import MAX_QUOTE_CHARS, complete_quote

#: The exact fragment the model returned for #1448.
PARENTHETICAL_FRAGMENT = (
    "(I noticed this because the v2 branch dropped supports_set_ciphers when "
    "dropping Python 2.6 support."
)
PARENTHETICAL_SOURCE = (
    "Some body text.\r\n\r\n"
    "(I noticed this because the v2 branch dropped supports_set_ciphers when "
    "dropping Python 2.6 support.)\r\n\r\nA closing remark."
)

#: The exact stored #3466 quote, which is already whole.
S3466_QUOTE = (
    "Unfortunately, we realized after working on them that we can't really use "
    "those new settings. curl also does not implement them."
)
S3466_SOURCE = (
    "Reverts urllib3/urllib3#3456, Closes #3306 \r\n\r\nUnfortunately, we realized "
    "after working on them that we can't really use those new settings. curl also "
    "does not implement them. See "
    "https://github.com/urllib3/urllib3/issues/3306#issuecomment-2320997012 "
    "for details."
)

LONG_SENTENCE = "This is one very long sentence. " + ("padding words " * 90) + "End here."
LONG_SOURCE = f"Preamble.\n\n{LONG_SENTENCE}\n\nTrailer."


def test_a_quote_already_at_a_boundary_is_left_alone() -> None:
    result = complete_quote(S3466_QUOTE, S3466_SOURCE)

    assert result.quote == S3466_QUOTE, "a whole quote must not be altered"
    assert result.status == "complete"


def test_a_quote_ending_inside_a_sentence_is_extended_to_the_boundary() -> None:
    result = complete_quote(PARENTHETICAL_FRAGMENT, PARENTHETICAL_SOURCE)

    assert result.quote == PARENTHETICAL_FRAGMENT + ")"
    assert result.status == "extended", (
        "the closing bracket belongs to the sentence and the model dropped it"
    )


def test_the_s3466_fragment_needs_no_extension() -> None:
    """The exact stored #3466 quote is already whole, so nothing changes."""
    result = complete_quote(S3466_QUOTE, S3466_SOURCE)

    assert result.status == "complete"
    assert result.quote == S3466_QUOTE
    assert "See " not in result.quote, "the following sentence is a separate unit"


def test_a_sentence_longer_than_the_limit_is_kept_whole_and_flagged() -> None:
    truncated = LONG_SENTENCE[:200]

    result = complete_quote(truncated, LONG_SOURCE)

    assert result.status == "long_sentence"
    assert result.over_limit is True
    assert result.quote.strip() == LONG_SENTENCE.strip(), (
        "a sentence over the limit is kept whole rather than cut"
    )
    assert len(result.quote) > MAX_QUOTE_CHARS


def test_the_limit_is_the_documented_larger_value() -> None:
    assert MAX_QUOTE_CHARS == 500


def test_a_quote_that_appears_nowhere_is_reported_as_incomplete() -> None:
    result = complete_quote("this text is not in the source at all", "Some source.")

    assert result.status == "quote_incomplete"


def test_completion_works_through_whitespace_differences() -> None:
    """The stored body carries CRLF; a quote typed with spaces must still complete."""
    source = "First line.\r\n\r\n(A note that continues into a second sentence here.)"
    fragment = "(A note that continues into a second sentence here."

    result = complete_quote(fragment, source)

    assert result.status == "extended"
    assert result.quote.endswith(")")


def test_an_ending_bracket_does_not_count_as_mid_sentence() -> None:
    """A quote that already closes a parenthetical and the sentence is whole."""
    source = "A sentence in brackets (like this one)."
    fragment = source

    result = complete_quote(fragment, source)

    assert result.status == "complete"
    assert result.quote == fragment


def test_a_quote_ending_at_end_of_source_is_complete() -> None:
    result = complete_quote("The last sentence.", "Some text. The last sentence.")

    assert result.status == "complete"


def test_a_quote_missing_the_final_terminator_is_completed() -> None:
    source = "The decision was recorded because the queue backed up."
    fragment = "The decision was recorded because the queue backed up"

    result = complete_quote(fragment, source)

    assert result.status == "extended"
    assert result.quote.endswith(".")


@pytest.mark.parametrize("terminator", [".", "!", "?", "..."])
def test_each_terminator_ends_a_sentence(terminator: str) -> None:
    source = f"The decision was recorded{terminator}"
    quote = f"The decision was recorded{terminator}"

    assert complete_quote(quote, source).status == "complete"


@pytest.mark.parametrize("closer", [")", "]", "}", '"', "'"])
def test_a_terminator_followed_by_a_closer_ends_a_sentence(closer: str) -> None:
    """`support.)` closes a parenthetical; the bracket belongs to the sentence."""
    source = f"The aside closes here.{closer} And then a new sentence follows."
    quote = f"The aside closes here.{closer}"

    assert complete_quote(quote, source).status == "complete"


@pytest.mark.parametrize("closer", [")", "]", "}"])
def test_a_closing_bracket_alone_does_not_end_a_sentence(closer: str) -> None:
    """`here) and then more` is mid-sentence, so the quote is completed."""
    source = f"The aside closes here{closer} and then the sentence carries on for a while."
    quote = f"The aside closes here{closer}"

    result = complete_quote(quote, source)

    assert result.status == "extended"
    assert result.quote.endswith(".")