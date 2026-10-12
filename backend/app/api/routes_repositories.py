from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_source
from app.schemas.ask import AskRequest, AskResponse
from app.schemas.entities import EntityListResponse
from app.schemas.errors import ErrorResponse
from app.schemas.graph import GraphResponse
from app.schemas.repository import RepositoryResponse
from app.services.data_source import DataSource

router = APIRouter(tags=["repositories"])

NOT_FOUND_RESPONSE: dict = {404: {"model": ErrorResponse}}


@router.get(
    "/repositories/{repository_id:path}/entities",
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


@router.post(
    "/repositories/{repository_id:path}/ask",
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
    "/repositories/{repository_id:path}/graph",
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


@router.get(
    "/repositories/{repository_id:path}",
    response_model=RepositoryResponse,
    responses=NOT_FOUND_RESPONSE,
    summary="Repository identity and counts",
)
def get_repository(repository_id: str, source: DataSource = Depends(get_source)) -> RepositoryResponse:
    return source.get_repository(repository_id)
