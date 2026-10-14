from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Optional, Protocol, runtime_checkable

from app.config import Settings, settings
from app.services.errors import DataSourceError
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





class NotFoundError(DataSourceError):
    pass


@runtime_checkable
class DataSource(Protocol):
    def get_repository(self, repository_id: str) -> RepositoryResponse: ...

    def search_entities(self, repository_id: str, query: str) -> EntityListResponse: ...

    def ask(self, repository_id: str, request: AskRequest) -> AskResponse: ...

    def get_decision(self, decision_id: str) -> DecisionDetail: ...
    def get_graph(self, repository_id: str, entity_id: str | None) -> GraphResponse: ...


def node_repo_hint(store: object) -> str:
    nodes = getattr(store, "nodes", None)
    if isinstance(nodes, dict):
        for props in nodes.values():
            repo = (props or {}).get("repo")
            if repo:
                return str(repo)
    return "unknown"


def source_ref_for(node: dict) -> SourceRef:
    """Build a SourceRef from the stored node.

    Values that are genuinely absent stay absent; a placeholder would misattribute
    the decision, so a decision with no usable source is refused instead.
    """
    source_url = node.get("source_url") or ""
    raw_number = node.get("source_number")
    number = raw_number if isinstance(raw_number, int) and raw_number >= 0 else None

    if not source_url or number is None:
        derived_url, derived_number, derived_type = from_source_id(node.get("source_id"))
        source_url = source_url or derived_url
        if number is None:
            number = derived_number

    raw_type = (node.get("source_type") or "").strip().lower()
    try:
        source_type = SourceType(raw_type)
    except ValueError:
        source_type = derived_type or SourceType.PULL_REQUEST

    if number is None or not source_url:
        raise DataSourceError(
            "decision carries no usable source reference; refusing to invent one"
        )
    return SourceRef(type=source_type, number=number, url=source_url)


def from_source_id(source_id: Any) -> tuple[str, Optional[int], SourceType]:
    """Derive provenance from a stable source id such as ``pr:owner/repo#123``.

    Returns empty values when the id does not carry enough information, so the
    caller refuses rather than guessing.
    """
    text = str(source_id or "")
    match = re.match(r"^(pr|pull_request|issue):(?P<owner>[^/]+)/(?P<repo>[^#]+)#(?P<number>\d+)$", text)
    if not match:
        return "", None, SourceType.PULL_REQUEST
    number = int(match.group("number"))
    kind = SourceType.ISSUE if text.startswith("issue") else SourceType.PULL_REQUEST
    segment = "issues" if kind is SourceType.ISSUE else "pull"
    url = f"https://github.com/{match.group('owner')}/{match.group('repo')}/{segment}/{number}"
    return url, number, kind


class GraphDataSource:
    """Production knowledge-graph data source querying Neo4j / InMemory graph store."""

    def __init__(self, cfg: Optional[Settings] = None, store: Optional[BaseGraphStore] = None) -> None:
        self.settings = cfg or settings
        self.store = store or get_graph_store(self.settings)
        self.provider = get_llm_provider(cfg=self.settings)

    @property
    def is_real(self) -> bool:
        """True only when both the store and the provider are real.

        Derived rather than declared, so swapping in a mock for a test or a
        misconfigured deployment can never leave the flag claiming otherwise.
        """
        return bool(getattr(self.store, "is_real", False)) and bool(
            getattr(self.provider, "is_real", False)
        )

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
            fixture=not self.is_real,
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
            fixture=not self.is_real,
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
                cfg=self.settings,
            )

        return generate_answer(
            question=request.question,
            resolution=resolution,
            bundle=bundle,
            provider=self.provider,
            is_real=self.is_real,
            min_score=self.settings.min_score,
            cfg=self.settings,
        )

    def get_decision(self, decision_id: str) -> DecisionDetail:
        """Return one decision, or refuse. Nothing is invented for a missing id.

        An earlier implementation returned placeholder text with a synthetic
        pull/1 URL, which presented invented content as real history.
        """
        node = self.store.nodes.get(decision_id) if hasattr(self.store, "nodes") else None
        if not node:
            raise DataSourceError(
                f"decision {decision_id!r} not found in the graph for "
                f"repository {node_repo_hint(self.store)!r}"
            )

        return DecisionDetail(
            id=decision_id,
            summary=node.get("summary", ""),
            rationale=node.get("rationale"),
            state=DecisionState(node.get("state", "ACTIVE")),
            source=source_ref_for(node),
            fixture=not self.is_real,
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
            fixture=not self.is_real,
        )


def get_data_source(cfg: Settings) -> DataSource:
    if cfg.data_source == "fixture":
        from app.fixtures.source import FixtureDataSource

        return FixtureDataSource(cfg)
    if cfg.data_source == "graph":
        source = GraphDataSource(cfg)
        # Without a real store and a real provider this source can only invent
        # answers, so refuse rather than serve fabricated history. Mock mode is
        # available deliberately, and still reports fixture=true on every response.
        if not source.is_real and not cfg.allow_mock_providers:
            missing = []
            if not getattr(source.store, "is_real", False):
                missing.append("a real Neo4j store (NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD)")
            if not getattr(source.provider, "is_real", False):
                missing.append("a real LLM provider (LLM_PROVIDER with credentials)")
            raise DataSourceError(
                "DATA_SOURCE=graph needs "
                + " and ".join(missing)
                + ". Set ALLOW_MOCK_PROVIDERS=true to run against the in-memory store "
                "and a mock LLM; every response then carries \"fixture\": true."
            )
        return source

    raise DataSourceError(
        f"DATA_SOURCE={cfg.data_source!r} is not supported. Must be 'fixture' or 'graph'."
    )
