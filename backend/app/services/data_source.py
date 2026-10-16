from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Optional, Protocol, runtime_checkable

from app.config import Settings, settings
from app.services.errors import DataSourceError
from app.providers.llm_provider import get_llm_provider
from app.schemas.common import DecisionState, EntityType, SourceType
from app.schemas.decisions import DecisionDetail, SourceRef
from app.schemas.entities import Entity, EntityListResponse
from app.schemas.graph import GraphEdge, GraphNode, GraphResponse
from app.schemas.repository import RepositoryCounts, RepositoryResponse
from app.services.answer import generate_answer
from app.services.entity_resolution import (
    EntityCandidate,
    ResolutionOutcome,
    ResolutionResult,
    names_an_explicit_path_or_quote,
    resolve_entity,
    resolve_entity_from_decisions,
)
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

    # Derived unconditionally: the branch below reads derived_type even when the
    # node already carried a url and number, so binding it only inside the `if`
    # raised UnboundLocalError for any decision that did have a source.
    derived_url, derived_number, derived_type = from_source_id(node.get("source_id"))
    if not source_url or number is None:
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

    def _require_repository(self, repository_id: str) -> list[dict[str, Any]]:
        """Refuse a repository the graph has never seen.

        A repository with nothing in it is a different statement from a repository
        that cannot be reached. Only the latter is an infrastructure failure and
        only that one is allowed to surface as a 503.
        """
        entities = self.store.search_entities(repository_id, "")
        if not entities and not self._has_repository_node(repository_id):
            raise NotFoundError(f"repository {repository_id!r} not found")
        return entities

    def _has_repository_node(self, repository_id: str) -> bool:
        """Whether the graph holds a Repository node for this id.

        Resolved through `get_node` rather than a duck-typed `nodes` mapping, so the
        check works against Neo4j instead of silently reporting "no repository" and
        turning a real hit into a 404.
        """
        node = self._find_node(repository_id)
        return bool(node) and node.get("repo") == repository_id

    def _find_node(self, node_id: str) -> Optional[dict[str, Any]]:
        """Look a node up by id in whichever store is in use."""
        getter = getattr(self.store, "get_node", None)
        if callable(getter):
            return getter(node_id)
        nodes = getattr(self.store, "nodes", None)
        if isinstance(nodes, dict):
            return nodes.get(node_id)
        return None

    def _resolve_explicit_entity(self, repository_id: str, entity_id: str) -> ResolutionResult:
        """Resolve an entity a caller named, or refuse plainly.

        A caller who names an entity must get that entity or a clear refusal; falling
        back to text resolution would answer about a different entity than the one
        they named. An unknown id is `entity_not_found`, the same contract the fixture
        source follows.
        """
        node = self.store.get_entity(repository_id, entity_id)
        if node is None:
            return ResolutionResult(
                outcome=ResolutionOutcome.REFUSAL,
                reason_code="entity_not_found",
                error_message=f"entity {entity_id!r} is not in the graph",
            )
        return ResolutionResult(
            outcome=ResolutionOutcome.SUCCESS,
            entity=EntityCandidate(
                id=node.get("id", entity_id),
                name=node.get("name", ""),
                path=node.get("path", node.get("name", "")),
                entity_type=node.get("entity_type", "File"),
                score=1.0,
            ),
        )

    def get_repository(self, repository_id: str) -> RepositoryResponse:
        entities = self._require_repository(repository_id)
        # Name and url come from the Repository node the build wrote, not from the id
        # string: the id is the slug the API addresses, and the real address lives on
        # the node as `url` with the raw `owner/name` in `full_name`.
        node = self._find_node(repository_id) or {}
        raw_name = node.get("full_name") or repository_id
        return RepositoryResponse(
            id=repository_id,
            name=node.get("name") or repository_id.rsplit("/", 1)[-1],
            url=node.get("url") or f"https://github.com/{raw_name}",
            counts=RepositoryCounts(
                decisions=self.store.count_nodes(repository_id, "Decision"),
                entities=len(entities),
                pull_requests=self.store.count_nodes(repository_id, "PullRequest"),
                commits=self.store.count_nodes(repository_id, "Commit"),
            ),
            fixture=not self.is_real,
        )

    def search_entities(self, repository_id: str, query: str) -> EntityListResponse:
        raw_ents = self._require_repository(repository_id)
        if query.strip():
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
        all_entities = self._require_repository(repository_id)
        if request.entity_id is not None:
            resolution = self._resolve_explicit_entity(repository_id, request.entity_id)
        else:
            resolution = resolve_entity(request.question, all_entities, repository_id)
            # The question named no entity, so try to find the decisions from their
            # own text and take the entity from them. An out-of-scope question, a
            # genuine tie, and a named path that is simply absent are all left as
            # they are.
            if (
                resolution.outcome == ResolutionOutcome.REFUSAL
                and resolution.reason_code != "out_of_scope"
                and not names_an_explicit_path_or_quote(request.question)
            ):
                from_decisions = resolve_entity_from_decisions(
                    request.question, self.store, repository_id
                )
                if from_decisions is not None:
                    resolution = from_decisions

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
        pull/1 URL, which presented invented content as real history. A second one
        raised a plain DataSourceError, which the API reports as 503 and so claimed
        the database was broken when in fact the id simply does not exist.
        """
        node = self._find_node(decision_id)
        if not node:
            raise NotFoundError(f"decision {decision_id!r} not found")

        return DecisionDetail(
            id=decision_id,
            summary=node.get("summary", ""),
            rationale=node.get("rationale"),
            state=DecisionState(node.get("state", "ACTIVE")),
            source=source_ref_for(node),
            fixture=not self.is_real,
        )

    def get_graph(self, repository_id: str, entity_id: str | None) -> GraphResponse:
        self._require_repository(repository_id)
        if entity_id is not None and self.store.get_entity(repository_id, entity_id) is None:
            # An unknown entity is a 404. Returning an empty graph with 200 would
            # tell the caller the entity has no history when it is not in the graph.
            raise NotFoundError(f"entity {entity_id!r} not found")

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
