"""A broken provider is not an absent rationale.

The answer path used to catch every provider exception and return a partial with
reason_code=no_verified_quote, which reports "the team never wrote down why" when
the truth is "the model call failed". That is a false statement about the
repository's history.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.config import Settings
from app.providers.llm_provider import BaseLLMProvider
from app.schemas.ask import AskRequest
from app.services.answer import generate_answer
from app.services.data_source import DataSourceError, GraphDataSource
from app.services.entity_resolution import resolve_entity
from app.services.retrieval import EvidenceBundle, RetrievedEvidenceItem
from app.stores.graph_store import InMemoryGraphStore

REPO = "acme/netclient"
QUESTION = "Why is MAX_RETRIES 3?"
BODY = "mobile clients kept timing out on flaky networks"


class ExplodingProvider(BaseLLMProvider):
    """Fails the way a real outage would."""

    is_real = True

    def __init__(self, message: str = "upstream 503") -> None:
        super().__init__()
        self.message = message
        self.calls = 0

    def complete(self, prompt, system=None, **kwargs):  # noqa: ANN001
        self.calls += 1
        raise RuntimeError(self.message)

    def complete_structured(self, schema, prompt, system=None, **kwargs):  # noqa: ANN001
        self.calls += 1
        raise RuntimeError(self.message)


def bundle() -> EvidenceBundle:
    entities = [{"id": "e1", "name": "MAX_RETRIES", "path": "pkg/config.py",
                 "entity_type": "ConfigKey"}]
    resolution = resolve_entity(QUESTION, entities)
    return EvidenceBundle(
        question=QUESTION,
        resolved_entity=entities[0],
        decisions=[{"id": "d1", "repo": REPO, "summary": "Raised the cap",
                    "rationale": BODY, "state": "ACTIVE"}],
        evidence_items=[RetrievedEvidenceItem(
            id="ev1", decision_id="d1", source_id=f"pr:{REPO}#7",
            source_type="pull_request", source_url=f"https://github.com/{REPO}/pull/7",
            quote="mobile clients kept timing out", claim="cap raised",
            author="real-reviewer", timestamp="2025-01-01T00:00:00Z",
            quote_verified=True, similarity_score=0.95,
        )],
        best_similarity_score=0.95,
        source_texts={f"pr:{REPO}#7": BODY},
    )


def test_a_provider_failure_raises_rather_than_reporting_no_verified_quote() -> None:
    entities = [{"id": "e1", "name": "MAX_RETRIES", "path": "pkg/config.py",
                 "entity_type": "ConfigKey"}]
    resolution = resolve_entity(QUESTION, entities)
    provider = ExplodingProvider()

    with pytest.raises(DataSourceError) as excinfo:
        generate_answer(
            question=QUESTION,
            resolution=resolution,
            bundle=bundle(),
            provider=provider,
            is_real=True,
        )

    message = str(excinfo.value)
    assert "no_verified_quote" not in message
    assert provider.calls == 1


def test_the_error_does_not_leak_credentials_or_a_token() -> None:
    entities = [{"id": "e1", "name": "MAX_RETRIES", "path": "pkg/config.py",
                 "entity_type": "ConfigKey"}]
    resolution = resolve_entity(QUESTION, entities)
    provider = ExplodingProvider("boom ghp_ThisIsTheSecretTokenValue1234567890")
    with pytest.raises(DataSourceError) as excinfo:
        generate_answer(question=QUESTION, resolution=resolution, bundle=bundle(),
                        provider=provider, is_real=True)
    assert "ghp_" not in str(excinfo.value)


def test_schema_validation_failure_is_also_an_infrastructure_error() -> None:
    from app.providers.llm_provider import LLMSchemaValidationError

    class BadSchema(BaseLLMProvider):
        def complete(self, prompt, system=None, **kwargs):  # noqa: ANN001
            raise NotImplementedError

        def complete_structured(self, schema, prompt, system=None, **kwargs):  # noqa: ANN001
            raise LLMSchemaValidationError("model returned prose, not json")

    entities = [{"id": "e1", "name": "MAX_RETRIES", "path": "pkg/config.py",
                 "entity_type": "ConfigKey"}]
    resolution = resolve_entity(QUESTION, entities)
    with pytest.raises(DataSourceError):
        generate_answer(question=QUESTION, resolution=resolution, bundle=bundle(),
                        provider=BadSchema(), is_real=True)


def test_the_api_maps_the_failure_to_a_server_error_not_a_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end through the data source: a provider outage is an error."""
    # The threshold comes from the Settings handed to the source, so it is set there.
    del monkeypatch
    store = InMemoryGraphStore()
    store.merge_node("Repository", {"id": REPO, "name": "netclient", "repo": REPO})
    store.merge_node("CodeEntity", {"id": "e1", "repo": REPO, "name": "MAX_RETRIES",
                                    "path": "pkg/config.py", "entity_type": "ConfigKey"})
    store.merge_node("Decision", {"id": "d1", "repo": REPO, "summary": "Raised the cap",
                                  "rationale": BODY, "state": "ACTIVE"})
    store.merge_node("Evidence", {"id": "ev1", "source_id": f"pr:{REPO}#7",
                                  "source_type": "pull_request",
                                  "source_url": f"https://github.com/{REPO}/pull/7",
                                  "quote": "mobile clients kept timing out", "claim": "c",
                                  "author": "real-reviewer", "timestamp": "2025-01-01T00:00:00Z",
                                  "quote_verified": True})
    store.merge_relationship("GOVERNS", "d1", "e1", {})
    store.merge_relationship("SUPPORTED_BY", "d1", "ev1", {})
    store.source_texts[f"pr:{REPO}#7"] = BODY

    source = GraphDataSource(
        Settings(_env_file=None, allow_mock_providers=True, min_score=0.0), store=store
    )
    source.provider = ExplodingProvider()

    with pytest.raises(DataSourceError):
        source.ask(REPO, AskRequest(question=QUESTION))


def test_the_frozen_contract_has_no_new_reason_code() -> None:
    """R5 must not add a reason code; it must surface an error instead."""
    from app.schemas.common import ReasonCode

    names = [m.lower() for m in ReasonCode.__members__]
    assert "llm_unavailable" not in names
    assert "no_verified_quote" in names


def test_a_working_provider_is_unaffected() -> None:
    from app.providers.llm_provider import MockLLMProvider

    entities = [{"id": "e1", "name": "MAX_RETRIES", "path": "pkg/config.py",
                 "entity_type": "ConfigKey"}]
    resolution = resolve_entity(QUESTION, entities)
    provider = MockLLMProvider(canned_response=json.dumps({
        "answer": "raised to 3 for flaky networks", "cited_evidence_ids": ["ev1"],
    }))
    response = generate_answer(question=QUESTION, resolution=resolution,
                               bundle=bundle(), provider=provider, is_real=True)
    assert response.outcome.value == "full"


def test_error_response_body_shape_is_unchanged() -> None:
    from app.schemas.errors import ErrorResponse

    body = ErrorResponse(detail="provider failed")
    assert body.detail == "provider failed"
    payload: dict[str, Any] = body.model_dump()
    assert set(payload) == {"detail"}
