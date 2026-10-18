from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings
from app.fixtures.dataset import EXAMPLE_QUESTIONS, REPOSITORY_ID
from app.fixtures.source import FixtureDataSource
from app.main import create_app
from app.schemas.ask import AskResponse
from app.schemas.decisions import DecisionDetail, DecisionListResponse
from app.schemas.entities import EntityListResponse
from app.schemas.graph import GraphResponse
from app.schemas.repository import RepositoryListResponse, RepositoryResponse

CONTRACT_DIR = ROOT / "contract"

CONTRACT_SPECS: dict[str, tuple[type[BaseModel], Optional[str]]] = {
    "ask_full.json": (AskResponse, EXAMPLE_QUESTIONS["full"]["question"]),
    "ask_partial.json": (AskResponse, EXAMPLE_QUESTIONS["no_verified_quote"]["question"]),
    "ask_refusal.json": (AskResponse, EXAMPLE_QUESTIONS["no_decision_path"]["question"]),
    "ask_ambiguous.json": (AskResponse, EXAMPLE_QUESTIONS["ambiguous"]["question"]),
    "ask_entity_not_found.json": (AskResponse, EXAMPLE_QUESTIONS["entity_not_found"]["question"]),
    "ask_out_of_scope.json": (AskResponse, EXAMPLE_QUESTIONS["out_of_scope"]["question"]),
    "graph.json": (GraphResponse, None),
    "decision.json": (DecisionDetail, None),
    "decisions.json": (DecisionListResponse, None),
    "entities.json": (EntityListResponse, None),
    "repository.json": (RepositoryResponse, None),
    "repositories.json": (RepositoryListResponse, None),
}


def build_payload(name: str, model: type[BaseModel], question: Optional[str], source: FixtureDataSource) -> dict:
    if question is not None:
        response = source.ask(REPOSITORY_ID, question)
    elif name == "graph.json":
        response = source.get_graph(REPOSITORY_ID, None)
    elif name == "decision.json":
        response = source.get_decision("dec_77")
    elif name == "decisions.json":
        response = source.list_decisions(REPOSITORY_ID)
    elif name == "entities.json":
        response = source.search_entities(REPOSITORY_ID, "retry")
    elif name == "repositories.json":
        response = source.list_repositories()
    else:
        response = source.get_repository(REPOSITORY_ID)
    validated = model.model_validate(response.model_dump(mode="json"))
    return validated.model_dump(mode="json")


def main() -> int:
    source = FixtureDataSource(Settings(_env_file=None))
    CONTRACT_DIR.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name, (model, question) in CONTRACT_SPECS.items():
        payload = build_payload(name, model, question, source)
        target = CONTRACT_DIR / name
        target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(name)
    document = json.loads(json.dumps(create_app().openapi(), sort_keys=True))
    (CONTRACT_DIR / "openapi.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    written.append("openapi.json")
    for name in sorted(written):
        print(f"wrote contract/{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
