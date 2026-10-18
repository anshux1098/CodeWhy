from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_source
from app.schemas.ask import AskRequest, AskResponse
from app.schemas.common import DecisionState
from app.schemas.decisions import DecisionListResponse
from app.schemas.entities import EntityListResponse
from app.schemas.errors import ErrorResponse
from app.schemas.graph import GraphResponse
from app.schemas.repository import RepositoryListResponse, RepositoryResponse
from app.services.data_source import DataSource

router = APIRouter(tags=["repositories"])

NOT_FOUND_RESPONSE: dict = {404: {"model": ErrorResponse}}


@router.get(
    "/repositories",
    response_model=RepositoryListResponse,
    summary="Every repository in the graph, with its ingestion status",
)
def list_repositories(source: DataSource = Depends(get_source)) -> RepositoryListResponse:
    return source.list_repositories()


@router.get(
    "/repositories/{repository_id}",
    response_model=RepositoryResponse,
    responses=NOT_FOUND_RESPONSE,
    summary="Repository identity and counts",
)
def get_repository(repository_id: str, source: DataSource = Depends(get_source)) -> RepositoryResponse:
    return source.get_repository(repository_id)


@router.get(
    "/repositories/{repository_id}/entities",
    response_model=EntityListResponse,
    responses=NOT_FOUND_RESPONSE,
    summary="Search files, modules and config keys",
)
def search_entities(
    repository_id: str,
    q: str = Query(min_length=1, description="Substring of the entity label"),
    source: DataSource = Depends(get_source),
) -> EntityListResponse:
    return source.search_entities(repository_id, q)


@router.get(
    "/repositories/{repository_id}/decisions",
    response_model=DecisionListResponse,
    responses=NOT_FOUND_RESPONSE,
    summary="List a repository's decisions, newest first",
)
def list_decisions(
    repository_id: str,
    entity_id: str | None = Query(default=None, description="Only decisions governing this entity"),
    state: DecisionState | None = Query(default=None, description="Only decisions in this state"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    source: DataSource = Depends(get_source),
) -> DecisionListResponse:
    return source.list_decisions(
        repository_id, entity_id=entity_id, state=state, limit=limit, offset=offset
    )


@router.post(
    "/repositories/{repository_id}/ask",
    response_model=AskResponse,
    responses=NOT_FOUND_RESPONSE,
    summary="Answer a why question, or refuse with a reason code",
)
def ask(
    repository_id: str,
    request: AskRequest,
    source: DataSource = Depends(get_source),
) -> AskResponse:
    return source.ask(repository_id, request)


@router.get(
    "/repositories/{repository_id}/graph",
    response_model=GraphResponse,
    responses=NOT_FOUND_RESPONSE,
    summary="Bounded subgraph, optionally rooted at one entity",
)
def get_graph(
    repository_id: str,
    entity_id: str | None = Query(default=None),
    source: DataSource = Depends(get_source),
) -> GraphResponse:
    return source.get_graph(repository_id, entity_id)
