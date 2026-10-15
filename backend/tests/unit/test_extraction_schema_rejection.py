"""A reply that does not match the schema must be recorded, never dropped.

The real run against OpenRouter returned this, for the HTTP/2 TLS revert:

    {"no_decision": false, "decision_type": "Compatibility",
     "decision_summary": "Revert of HTTP/2 TLS settings...", "supporting_evidence": [...]}

`LLMExtractionPayload` uses `extra="ignore"`, so the three top-level fields were
discarded, `decisions` fell back to its empty default, and the run reported success
with zero decisions and no error. A good extraction had vanished silently.

The fix is not to accept that shape. It is to refuse it loudly: an unknown
top-level key means the model did not follow the contract, and that is worth a row
in extraction_failures rather than an empty result.
"""

from __future__ import annotations

import json

import pytest

from app.services.extraction import (
    ExtractionSchemaRejected,
    LLMExtractionPayload,
    extract_decisions_from_source,
)
from app.providers.llm_provider import MockLLMProvider

#: The exact object the real run received, verbatim from the log.
FLAT_REPLY = {
    "no_decision": False,
    "decision_type": "Compatibility",
    "decision_summary": (
        "Revert of HTTP/2 TLS settings due to incompatibility with curl "
        "and inability to use the new settings."
    ),
    "supporting_evidence": [
        {"quote": "we can't really use those new settings", "claim": "reverted", "timestamp": None}
    ],
}

SOURCE = {
    "source_id": "pr:urllib3/urllib3#3466",
    "source_type": "pr",
    "source_url": "https://github.com/urllib3/urllib3/pull/3466",
    "repo": "urllib3/urllib3",
    "title": 'Revert "Add TLS settings for HTTP/2"',
    "body": "we can't really use those new settings",
}


def provider_replying(payload: object) -> MockLLMProvider:
    return MockLLMProvider(canned_response=json.dumps(payload))


# --- the schema itself ------------------------------------------------------


def test_the_flat_reply_is_refused_rather_than_accepted() -> None:
    with pytest.raises(Exception) as excinfo:
        LLMExtractionPayload.model_validate(FLAT_REPLY)

    assert "decisions" in str(excinfo.value) or "extra" in str(excinfo.value).lower()


def test_the_payload_forbids_unknown_top_level_keys() -> None:
    assert LLMExtractionPayload.model_config.get("extra") == "forbid"


def test_the_correct_shape_with_an_empty_list_still_validates() -> None:
    """An empty list is the only way to say "no decision", and it must be accepted."""
    payload = LLMExtractionPayload.model_validate({"decisions": []})
    assert payload.decisions == []


def test_a_well_formed_reply_validates() -> None:
    payload = LLMExtractionPayload.model_validate({
        "decisions": [{
            "summary": "Reverted the HTTP/2 TLS settings",
            "decision_type": "Compatibility",
            "rationale": "curl cannot use them",
            "supporting_evidence": [
                {"quote": "we can't really use those new settings", "claim": "why"}
            ],
        }]
    })
    assert len(payload.decisions) == 1


# --- extraction reports it ---------------------------------------------------


def test_extraction_raises_schema_rejected_for_the_flat_reply() -> None:
    provider = provider_replying(FLAT_REPLY)

    with pytest.raises(ExtractionSchemaRejected) as excinfo:
        extract_decisions_from_source(provider=provider, **SOURCE)

    error = excinfo.value
    assert error.source_id == "pr:urllib3/urllib3#3466"


def test_the_rejection_names_the_keys_received_but_never_their_values() -> None:
    provider = provider_replying(FLAT_REPLY)

    with pytest.raises(ExtractionSchemaRejected) as excinfo:
        extract_decisions_from_source(provider=provider, **SOURCE)

    error = excinfo.value
    assert set(error.received_keys) >= {"no_decision", "decision_type", "decision_summary"}
    # A summary is content, not a key name, and must not be echoed anywhere.
    rendered = f"{error.received_keys} {error}"
    assert "Revert of HTTP/2 TLS settings" not in rendered
    assert "we can't really use those new settings" not in rendered


def test_the_rejection_records_the_finish_reason() -> None:
    provider = provider_replying(FLAT_REPLY)
    provider.complete_structured.__self__  # keep the mock honest

    class WithFinish(MockLLMProvider):
        def complete(self, prompt, system=None, **kwargs):  # noqa: ANN001
            response = super().complete(prompt, system=system, **kwargs)
            from dataclasses import replace

            return replace(response, finish_reason="stop")

    with pytest.raises(ExtractionSchemaRejected) as excinfo:
        extract_decisions_from_source(provider=WithFinish(canned_response=json.dumps(FLAT_REPLY)), **SOURCE)

    assert excinfo.value.finish_reason == "stop"


def test_a_genuinely_empty_decision_list_is_not_a_rejection() -> None:
    """Correct shape, no decisions: that is the real 'no decision', not a failure."""
    provider = provider_replying({"decisions": []})

    assert extract_decisions_from_source(provider=provider, **SOURCE) == []


def test_a_missing_decisions_key_is_a_rejection() -> None:
    with pytest.raises(ExtractionSchemaRejected):
        extract_decisions_from_source(provider=provider_replying({}), **SOURCE)


def test_a_wrong_type_for_decisions_is_a_rejection() -> None:
    with pytest.raises(ExtractionSchemaRejected):
        extract_decisions_from_source(
            provider=provider_replying({"decisions": "not a list"}), **SOURCE
        )


def test_a_wrong_type_inside_a_decision_is_a_rejection() -> None:
    with pytest.raises(ExtractionSchemaRejected):
        extract_decisions_from_source(
            provider=provider_replying({"decisions": [{"summary": 12345}]}), **SOURCE
        )


def test_non_json_output_is_still_reported_as_a_schema_failure() -> None:
    """Prose is not a reply. It must not be mistaken for 'no decision'."""
    provider = MockLLMProvider(canned_response="I could not determine a decision.")

    with pytest.raises(ExtractionSchemaRejected):
        extract_decisions_from_source(provider=provider, **SOURCE)