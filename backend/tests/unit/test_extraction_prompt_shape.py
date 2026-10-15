"""The prompt has to state the shape, or the model invents one.

The prompt used to say `return {"no_decision": true}` when there is nothing, which
left the non-empty case completely unspecified. The model filled the gap by
inventing a flat shape, and the reply was then discarded. The contract needs to be
written down, with an example that shows the whole envelope.
"""

from __future__ import annotations

import json

from app.prompts.extract_decision import (
    EXAMPLE_BODY,
    EXAMPLE_QUOTE,
    EXAMPLE_TITLE,
    build_extraction_prompt,
    get_system_prompt,
)

# The example itself is imported rather than restated here, so this test cannot
# drift from what the prompt actually contains. It is a fictional repository: no
# real project's text is shown to the model.


def user_prompt() -> str:
    _, prompt = build_extraction_prompt(
        source_type="pr", source_id="pr:acme/widget#1",
        title="A title", body="A body",
    )
    return prompt


def system_prompt() -> str:
    return get_system_prompt()


# --- the required shape is stated -------------------------------------------


def test_the_prompt_names_the_required_top_level_key() -> None:
    assert '"decisions"' in user_prompt()


def test_the_prompt_says_an_empty_list_means_no_decision() -> None:
    text = user_prompt().lower()
    assert "empty list" in text or "empty array" in text
    assert "no decision" in text or "no decisions" in text


def test_the_prompt_forbids_unknown_top_level_keys() -> None:
    text = (user_prompt() + system_prompt()).lower()
    assert "no other top-level" in text or "do not add" in text


def test_the_prompt_does_not_ask_for_a_bare_no_decision_object() -> None:
    """`{"no_decision": true}` alone is no longer the agreed way to say nothing."""
    assert '{"no_decision": true}' not in user_prompt()


# --- the worked example -----------------------------------------------------


def test_the_example_is_invented_not_taken_from_a_real_repository() -> None:
    """A worked example must not smuggle real project text into the prompt."""
    combined = user_prompt() + system_prompt()
    for real in ("urllib3", "http2", "AES128-GCM", "MAX_RETRIES", "connectionpool"):
        assert real not in combined, f"the example references real data: {real}"


def example_reply(prompt: str) -> dict:
    """The full worked example, taken from after its label."""
    marker = "Correct response:\n"
    start = prompt.index(marker) + len(marker)
    return json.loads(prompt[start:prompt.index("\n", prompt.rindex("}]", start, start + 4000))])


def test_the_example_quote_appears_verbatim_in_the_example_body() -> None:
    """A model shown an example copies it, so a wrong quote teaches a wrong quote."""
    _, prompt = build_extraction_prompt(
        source_type="pr", source_id="pr:acme/widget#1",
        title=EXAMPLE_TITLE, body=EXAMPLE_BODY,
    )
    assert EXAMPLE_QUOTE in EXAMPLE_BODY
    assert EXAMPLE_QUOTE in prompt, "the example body must be shown, quote included"


def test_the_example_is_well_formed_json_that_validates() -> None:
    from app.services.extraction import LLMExtractionPayload

    _, prompt = build_extraction_prompt(
        source_type="pr", source_id="pr:acme/widget#1",
        title=EXAMPLE_TITLE, body=EXAMPLE_BODY,
    )
    example = example_reply(prompt)

    parsed = LLMExtractionPayload.model_validate(example)
    assert len(parsed.decisions) == 1
    assert parsed.decisions[0].supporting_evidence[0].quote == EXAMPLE_QUOTE


def test_the_example_shows_the_decisions_array_not_a_flat_object() -> None:
    prompt = user_prompt()
    example_start = prompt.index('{"decisions"')
    example = prompt[example_start:example_start + 400]
    assert "decisions" in example
    # The flat shape is what the real run produced; it must not appear as an example.
    assert '"decision_summary"' not in prompt


def test_the_example_includes_a_decision_type_from_the_allowed_list() -> None:
    from app.services.extraction import DecisionType

    allowed = {member.value for member in DecisionType}
    _, prompt = build_extraction_prompt(
        source_type="pr", source_id="pr:acme/widget#1",
        title=EXAMPLE_TITLE, body=EXAMPLE_BODY,
    )
    example = example_reply(prompt)
    assert example["decisions"][0]["decision_type"] in allowed