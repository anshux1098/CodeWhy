from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from app.config import Settings

if TYPE_CHECKING:
    from app.schemas.ask import AskRequest, AskResponse
    from app.schemas.decisions import DecisionDetail
    from app.schemas.entities import EntityListResponse
    from app.schemas.graph import GraphResponse
    from app.schemas.repository import RepositoryResponse


class DataSourceError(RuntimeError):
    pass


class NotFoundError(DataSourceError):
    pass


@runtime_checkable
class DataSource(Protocol):
    def get_repository(self, repository_id: str) -> "RepositoryResponse": ...

    def search_entities(self, repository_id: str, query: str) -> "EntityListResponse": ...

    def ask(self, repository_id: str, request: "AskRequest") -> "AskResponse": ...

    def get_decision(self, decision_id: str) -> "DecisionDetail": ...

    def get_graph(self, repository_id: str, entity_id: str | None) -> "GraphResponse": ...


def get_data_source(settings: Settings) -> DataSource:
    if settings.data_source == "fixture":
        from app.fixtures.source import FixtureDataSource

        return FixtureDataSource(settings)
    raise DataSourceError(
        f"DATA_SOURCE={settings.data_source!r} is not available yet. Phase 0 ships only the "
        "'fixture' implementation; GraphDataSource arrives in Phase 3."
    )
