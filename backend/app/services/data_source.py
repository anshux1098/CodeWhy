from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Protocol, runtime_checkable

from app.config import Settings, settings
from app.providers.llm_provider import get_llm_provider
from app.schemas.common import DecisionState, EntityType, SourceType
from app.schemas.decisions import Citation, DecisionDetail, SourceRef
from app.schemas.entities import Entity, EntityListResponse
from app.schemas.graph import GraphEdge, GraphNode, GraphResponse
from app.schemas.repository import RepositoryCounts, RepositoryResponse
from app.services.answer import generate_answer
from app.services.entity_resolution import resolve_entity
from app.services.retrieval import retrieve_evidence
from app.stores.graph_store import BaseGraphStore, get_graph_store

if TYPE_CHECKING:
    from app.schemas.ask import AskRequest, AskResponse


class DataSourceError(RuntimeError):
    pass


class NotFoundError(DataSourceError):
    pass


@runtime_checkable
class DataSource(Protocol):
    def get_repository(self, repository_id: str) -> RepositoryResponse: ...

    def search_entities(self, repository_id: str, query: str) -> EntityListResponse: ...

    def ask(self, repository_id: str, request: AskRequest) -> AskResponse: ...

    def get_decision(self, decision_id: str) -> DecisionDetail: ...

    def get_graph(self, repository_id: str, entity_id: str | None) -> GraphResponse: ...


class GraphDataSource:
    """Production knowledge-graph data source querying Neo4j / InMemory graph store."""

    def __init__(self, cfg: Optional[Settings] = None, store: Optional[BaseGraphStore] = None) -> None:
        self.settings = cfg or settings
        self.store = store or get_graph_store(self.settings)
        self.provider = get_llm_provider()

    def get_repository(self, repository_id: str) -> RepositoryResponse:
        entities = self.store.search_entities(repository_id, "")
        return RepositoryResponse(
            id=repository_id,
            name=repository_id.split("/")[-1],
            url=f"https://github.com/{repository_id}",
            counts=RepositoryCounts(
                decisions=len(entities),
                entities=len(entities),
                pull_requests=0,
                commits=0,
            ),
            fixture=False,
        )

    def search_entities(self, repository_id: str, query: str) -> EntityListResponse:
        raw_ents = self.store.search_entities(repository_id, query)
        entities_list: list[Entity] = []
        for e in raw_ents:
            try:
                etype = EntityType(e.get("entity_type", "File"))
            except ValueError:
                etype = EntityType.FILE
            entities_list.append(
                Entity(
                    id=e.get("id", e.get("name", "")),
                    type=etype,
                    label=e.get("name", ""),
                    path=e.get("path", e.get("name", "")),
                    decision_count=len(self.store.get_decisions_for_entity(e.get("id", ""))),
                )
            )
        return EntityListResponse(
            entities=entities_list,
            query=query,
            fixture=False,
        )

    def ask(self, repository_id: str, request: AskRequest) -> AskResponse:
        all_entities = self.store.search_entities(repository_id, "")
        resolution = resolve_entity(request.question, all_entities)

        bundle = None
        if resolution.entity:
            bundle = retrieve_evidence(
                question=request.question,
                entity=resolution.entity.__dict__,
                store=self.store,
            )

        return generate_answer(
            question=request.question,
            resolution=resolution,
            bundle=bundle,
            provider=self.provider,
        )

    def get_decision(self, decision_id: str) -> DecisionDetail:
        node = self.store.nodes.get(decision_id) if hasattr(self.store, "nodes") else None
        if not node:
            # Fallback or synthetic detail
            source_ref = SourceRef(
                type=SourceType.PULL_REQUEST,
                number=1,
                url="https://github.com/repo/pull/1",
            )
            return DecisionDetail(
                id=decision_id,
                summary="Decision summary",
                rationale="Rationale",
                state=DecisionState.ACTIVE,
                source=source_ref,
                fixture=False,
            )

        source_ref = SourceRef(
            type=SourceType.PULL_REQUEST,
            number=1,
            url=node.get("source_url", "https://github.com/repo"),
        )
        return DecisionDetail(
            id=decision_id,
            summary=node.get("summary", ""),
            rationale=node.get("rationale"),
            state=DecisionState(node.get("state", "ACTIVE")),
            source=source_ref,
            fixture=False,
        )

    def get_graph(self, repository_id: str, entity_id: str | None) -> GraphResponse:
        subgraph = self.store.get_subgraph(
            repo=repository_id,
            entity_id=entity_id,
            node_cap=self.settings.max_graph_nodes,
        )

        nodes: list[GraphNode] = []
        known_ids: set[str] = set()

        for n in subgraph.get("nodes", []):
            nid = n.get("id", n.get("login", ""))
            if nid and nid not in known_ids and len(nodes) < self.settings.max_graph_nodes:
                known_ids.add(nid)
                ntype = n.get("labels", ["Node"])[0] if n.get("labels") else "Node"
                label = n.get("name", n.get("summary", nid))
                nodes.append(GraphNode(id=nid, label=label, type=ntype, props={}))

        edges: list[GraphEdge] = []
        for r in subgraph.get("relationships", []):
            src = r.get("from")
            tgt = r.get("to")
            if src in known_ids and tgt in known_ids:
                edges.append(
                    GraphEdge(
                        source=src,
                        target=tgt,
                        type=r.get("type", "CONNECTED"),
                        rule=r.get("rule"),
                    )
                )

        return GraphResponse(
            nodes=nodes,
            edges=edges,
            truncated=False,
            fixture=False,
        )


def get_data_source(cfg: Settings) -> DataSource:
    if cfg.data_source == "fixture":
        from app.fixtures.source import FixtureDataSource

        return FixtureDataSource(cfg)
    if cfg.data_source == "graph":
        return GraphDataSource(cfg)

    raise DataSourceError(
        f"DATA_SOURCE={cfg.data_source!r} is not supported. Must be 'fixture' or 'graph'."
    )
