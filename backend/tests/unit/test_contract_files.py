from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.fixtures.dataset import REPOSITORY_ID
from app.schemas.ask import AskResponse
from app.schemas.decisions import DecisionDetail
from app.schemas.entities import EntityListResponse
from app.schemas.graph import GraphResponse
from app.schemas.repository import RepositoryResponse

CONTRACT_DIR = Path(__file__).resolve().parents[3] / "contract"

EXPECTED_FILES = {
    "ask_full.json": AskResponse,
    "ask_partial.json": AskResponse,
    "ask_refusal.json": AskResponse,
    "ask_ambiguous.json": AskResponse,
    "ask_entity_not_found.json": AskResponse,
    "ask_out_of_scope.json": AskResponse,
    "graph.json": GraphResponse,
    "decision.json": DecisionDetail,
    "entities.json": EntityListResponse,
    "repository.json": RepositoryResponse,
}

EXPECTED_PATHS = {
    "/api/v1/health",
    "/api/v1/health/dependencies",
    "/api/v1/repositories/{repository_id}",
    "/api/v1/repositories/{repository_id}/entities",
    "/api/v1/repositories/{repository_id}/ask",
    "/api/v1/repositories/{repository_id}/graph",
    "/api/v1/decisions/{decision_id}",
}


def test_contract_directory_contains_exactly_the_expected_files() -> None:
    assert {path.name for path in CONTRACT_DIR.glob("*.json")} == set(EXPECTED_FILES) | {"openapi.json"}


@pytest.mark.parametrize(("name", "model"), sorted(EXPECTED_FILES.items()))
def test_every_contract_file_validates(name: str, model: type[BaseModel]) -> None:
    payload = json.loads((CONTRACT_DIR / name).read_text(encoding="utf-8"))
    validated = model.model_validate(payload)
    assert validated.model_dump(mode="json") == payload


@pytest.mark.parametrize("name", sorted(EXPECTED_FILES))
def test_every_ask_contract_file_is_flagged_as_a_fixture(name: str) -> None:
    if not name.startswith("ask_"):
        pytest.skip("only ask responses carry a fixture flag")
    payload = json.loads((CONTRACT_DIR / name).read_text(encoding="utf-8"))
    assert payload["fixture"] is True


def test_openapi_contract_file_is_a_valid_document() -> None:
    document = json.loads((CONTRACT_DIR / "openapi.json").read_text(encoding="utf-8"))
    assert document["openapi"].startswith("3.")
    assert set(document["paths"]) == EXPECTED_PATHS
    assert "AskResponse" in document["components"]["schemas"]
    assert "confidence is null" in document["info"]["description"]


def test_contract_covers_every_fixture_outcome() -> None:
    outcomes = {
        json.loads((CONTRACT_DIR / name).read_text(encoding="utf-8"))["outcome"]
        for name in EXPECTED_FILES
        if name.startswith("ask_")
    }
    assert outcomes == {"full", "partial", "refusal"}


def test_repository_contract_file_names_the_fixture_repository() -> None:
    payload = json.loads((CONTRACT_DIR / "repository.json").read_text(encoding="utf-8"))
    assert payload["id"] == REPOSITORY_ID