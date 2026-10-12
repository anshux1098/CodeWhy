from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.decisions import Citation, Decision, DecisionDetail, SourceRef, WhoToAsk
from app.schemas.entities import Candidate, Entity, EntityListResponse
from app.schemas.errors import ErrorResponse
from app.schemas.repository import RepositoryCounts, RepositoryResponse

PULL_REQUEST = SourceRef(type="PullRequest", number=41, url="https://github.invalid/pulls/41")
CITATION = Citation(
    id="cit_41",
    decision_id="dec_41",
    kind="SOURCE",
    quote="Cap the library at three retries.",
    source_url="https://github.invalid/pulls/41",
    source_type="PullRequest",
    author="priya",
    timestamp="2024-02-11T09:14:00Z",
)


def a_decision(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "dec_41",
        "summary": "Cap MAX_RETRIES at 3",
        "rationale": "Mobile clients give up after three retries.",
        "state": "ACTIVE",
        "recorded_at": "2024-02-11T09:14:00Z",
        "effective_at": "2024-02-11T09:14:00Z",
        "ended_at": None,
        "source": PULL_REQUEST,
        "supersedes": [],
        "superseded_by": ["dec_77"],
        "rule": None,
    }
    payload.update(overrides)
    return payload


def test_decision_defaults_the_three_relationship_lists() -> None:
    decision = Decision(**a_decision())
    assert decision.probable_superseded_by == []
    assert decision.conflicts_with == []
    assert decision.reaffirms == []


def test_decision_rejects_an_unknown_state() -> None:
    with pytest.raises(ValidationError):
        Decision(**a_decision(state="MAYBE"))


def test_decision_detail_is_a_decision_plus_citations() -> None:
    detail = DecisionDetail(**a_decision(), citations=[CITATION], evidence_gaps=[], fixture=True)
    assert isinstance(detail, Decision)
    assert detail.citations[0].decision_id == detail.id
    assert detail.fixture is True


def test_entity_list_response_is_the_frozen_envelope() -> None:
    response = EntityListResponse(
        entities=[
            Entity(
                id="key:MAX_RETRIES",
                type="ConfigKey",
                label="MAX_RETRIES",
                path="netclient/config.py",
                decision_count=3,
            )
        ],
        query="MAX_RETRIES",
        fixture=True,
    )
    assert response.entities[0].type == "ConfigKey"
    assert response.fixture is True


def test_candidate_has_no_path() -> None:
    candidate = Candidate(id="file:netclient/retry.py", type="File", label="retry.py")
    assert "path" not in candidate.model_dump()


def test_repository_response_counts() -> None:
    response = RepositoryResponse(
        id="acme-netclient",
        name="netclient",
        url="https://github.invalid/acme/netclient",
        counts=RepositoryCounts(decisions=5, entities=6, pull_requests=5, commits=9),
        fixture=True,
    )
    assert response.counts.decisions == 5


def test_who_to_ask_reason_is_constrained() -> None:
    with pytest.raises(ValidationError):
        WhoToAsk(login="priya", reason="manager", active=True)


def test_citation_source_type_is_constrained() -> None:
    with pytest.raises(ValidationError):
        Citation(**{**CITATION.model_dump(), "source_type": "pull_request"})


def test_decision_rejects_an_unknown_field() -> None:
    with pytest.raises(ValidationError):
        Decision(**a_decision(notes="not a decision field"))


def test_candidate_rejects_a_path_field() -> None:
    with pytest.raises(ValidationError):
        Candidate(id="file:netclient/retry.py", type="File", label="retry.py", path="netclient/retry.py")


def test_error_response_shape() -> None:
    assert ErrorResponse(detail="repository not found").detail == "repository not found"
