from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Optional, Sequence

from app.config import Settings, settings
from app.graph.queries import (
    GET_DECISIONS_GOVERNING_ENTITY,
    GET_SUBGRAPH_FOR_ENTITY,
)
from app.graph.schema import (
    FULLTEXT_INDEX_QUERY,
    NODE_CONSTRAINTS,
    NODE_INDEXES,
    VECTOR_INDEX_QUERY,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base Graph Store Interface
# ---------------------------------------------------------------------------

class BaseGraphStore(ABC):
    """Abstract interface for knowledge graph operations."""

    @abstractmethod
    def init_schema(self) -> None:
        """Create constraints and indexes."""
        ...

    @abstractmethod
    def merge_node(self, label: str, properties: dict[str, Any]) -> None:
        """Idempotently MERGE a node with the given label and properties."""
        ...

    @abstractmethod
    def merge_relationship(
        self,
        rel_type: str,
        from_id: str,
        to_id: str,
        properties: Optional[dict[str, Any]] = None,
    ) -> None:
        """Idempotently MERGE a relationship between two nodes."""
        ...

    @abstractmethod
    def get_entity(self, repo: str, identifier: str) -> Optional[dict[str, Any]]:
        """Find a code entity by ID, path, or name."""
        ...

    @abstractmethod
    def search_entities(self, repo: str, query: str) -> list[dict[str, Any]]:
        """Search code entities matching a substring or pattern."""
        ...

    @abstractmethod
    def get_decisions_for_entity(self, entity_id: str) -> list[dict[str, Any]]:
        """Fetch decisions governing an entity, including connected evidence."""
        ...

    @abstractmethod
    def get_subgraph(
        self,
        repo: str,
        entity_id: Optional[str] = None,
        node_cap: int = 80,
    ) -> dict[str, Any]:
        """Fetch a bounded subgraph containing nodes and edges for the UI."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Release underlying connections."""
        ...


# ---------------------------------------------------------------------------
# In-Memory Graph Store (For tests and local mode without live AuraDB)
# ---------------------------------------------------------------------------

class InMemoryGraphStore(BaseGraphStore):
    """Thread-safe in-memory graph store for testing and local development."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.labels: dict[str, set[str]] = {}  # id -> set of labels
        # (from_id, rel_type, to_id) -> properties dict
        self.edges: dict[tuple[str, str, str], dict[str, Any]] = {}

    def init_schema(self) -> None:
        # In-memory stores have implicit constraints
        pass

    def merge_node(self, label: str, properties: dict[str, Any]) -> None:
        node_id = properties.get("id") or properties.get("login")
        if not node_id:
            raise ValueError(f"Node must have an 'id' or 'login' property: {properties}")
        node_id = str(node_id)
        if node_id not in self.nodes:
            self.nodes[node_id] = {}
            self.labels[node_id] = set()
        self.nodes[node_id].update(properties)
        self.labels[node_id].add(label)

    def merge_relationship(
        self,
        rel_type: str,
        from_id: str,
        to_id: str,
        properties: Optional[dict[str, Any]] = None,
    ) -> None:
        key = (str(from_id), str(rel_type), str(to_id))
        if key not in self.edges:
            self.edges[key] = {}
        if properties:
            self.edges[key].update(properties)

    def get_entity(self, repo: str, identifier: str) -> Optional[dict[str, Any]]:
        clean_ident = identifier.strip().lower()
        for node_id, props in self.nodes.items():
            if "CodeEntity" not in self.labels.get(node_id, set()):
                continue
            if props.get("repo") != repo:
                continue
            if (
                node_id.lower() == clean_ident
                or props.get("name", "").lower() == clean_ident
                or props.get("path", "").lower() == clean_ident
            ):
                return props
        return None

    def search_entities(self, repo: str, query: str) -> list[dict[str, Any]]:
        clean_q = query.strip().lower()
        results: list[dict[str, Any]] = []
        for node_id, props in self.nodes.items():
            if "CodeEntity" not in self.labels.get(node_id, set()):
                continue
            if props.get("repo") != repo:
                continue
            if (
                not clean_q
                or clean_q in props.get("name", "").lower()
                or clean_q in props.get("path", "").lower()
            ):
                results.append(props)
        return results

    def get_decisions_for_entity(self, entity_id: str) -> list[dict[str, Any]]:
        decisions: list[dict[str, Any]] = []
        for (f_id, r_type, t_id) in self.edges:
            if r_type == "GOVERNS" and t_id == str(entity_id):
                dec_props = dict(self.nodes.get(f_id, {}))
                # Gather evidence
                ev_list: list[dict[str, Any]] = []
                for (d_id, ev_rel, ev_id) in self.edges:
                    if d_id == f_id and ev_rel == "SUPPORTED_BY":
                        ev_props = self.nodes.get(ev_id)
                        if ev_props:
                            ev_list.append(ev_props)
                dec_props["evidence"] = ev_list
                decisions.append(dec_props)
        return decisions

    def get_subgraph(
        self,
        repo: str,
        entity_id: Optional[str] = None,
        node_cap: int = 80,
    ) -> dict[str, Any]:
        node_ids: set[str] = set()
        if entity_id and entity_id in self.nodes:
            node_ids.add(entity_id)
            # Add 1-hop and 2-hop neighbors
            for (f, r, t) in self.edges:
                if f == entity_id or t == entity_id:
                    node_ids.add(f)
                    node_ids.add(t)
        else:
            for n_id, props in self.nodes.items():
                if props.get("repo") == repo:
                    node_ids.add(n_id)
                if len(node_ids) >= node_cap:
                    break

        selected_nodes = [
            {**self.nodes[n_id], "labels": list(self.labels.get(n_id, []))}
            for n_id in list(node_ids)[:node_cap]
            if n_id in self.nodes
        ]
        active_ids = {n["id"] for n in selected_nodes if "id" in n}

        selected_edges = [
            {"from": f, "to": t, "type": r, **props}
            for (f, r, t), props in self.edges.items()
            if f in active_ids and t in active_ids
        ]

        return {"nodes": selected_nodes, "relationships": selected_edges}

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Real Neo4j Graph Store (AuraDB / Self-Hosted)
# ---------------------------------------------------------------------------

class Neo4jGraphStore(BaseGraphStore):
    """Production graph store backed by Neo4j driver and parameterized Cypher."""

    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j") -> None:
        try:
            import neo4j
        except ImportError as exc:
            raise RuntimeError("neo4j package is required to connect to Neo4j AuraDB") from exc

        self.driver = neo4j.GraphDatabase.driver(uri, auth=(user, password))
        self.database = database

    def init_schema(self) -> None:
        """Applies uniqueness constraints, indexes, vector index, and full-text index."""
        with self.driver.session(database=self.database) as session:
            for constraint_q in NODE_CONSTRAINTS:
                session.run(constraint_q)
            for index_q in NODE_INDEXES:
                session.run(index_q)
            try:
                session.run(VECTOR_INDEX_QUERY)
            except Exception as exc:
                logger.warning("Vector index creation skipped or unsupported: %s", exc)
            try:
                session.run(FULLTEXT_INDEX_QUERY)
            except Exception as exc:
                logger.warning("Full-text index creation skipped or unsupported: %s", exc)

    def merge_node(self, label: str, properties: dict[str, Any]) -> None:
        node_id_field = "login" if label == "Person" else "id"
        query = (
            f"MERGE (n:{label} {{{node_id_field}: $props.{node_id_field}}}) "
            f"SET n += $props"
        )
        with self.driver.session(database=self.database) as session:
            session.run(query, props=properties)

    def merge_relationship(
        self,
        rel_type: str,
        from_id: str,
        to_id: str,
        properties: Optional[dict[str, Any]] = None,
    ) -> None:
        query = (
            f"MATCH (a {{id: $from_id}}), (b {{id: $to_id}}) "
            f"MERGE (a)-[r:{rel_type}]->(b) "
            f"SET r += $props"
        )
        props = properties or {}
        with self.driver.session(database=self.database) as session:
            session.run(query, from_id=from_id, to_id=to_id, props=props)

    def get_entity(self, repo: str, identifier: str) -> Optional[dict[str, Any]]:
        query = (
            "MATCH (e:CodeEntity {repo: $repo}) "
            "WHERE e.id = $ident OR toLower(e.name) = toLower($ident) OR toLower(e.path) = toLower($ident) "
            "RETURN e LIMIT 1"
        )
        with self.driver.session(database=self.database) as session:
            result = session.run(query, repo=repo, ident=identifier.strip())
            record = result.single()
            return dict(record["e"]) if record else None

    def search_entities(self, repo: str, query: str) -> list[dict[str, Any]]:
        cql = (
            "MATCH (e:CodeEntity {repo: $repo}) "
            "WHERE toLower(e.name) CONTAINS toLower($q) OR toLower(e.path) CONTAINS toLower($q) "
            "RETURN e LIMIT 20"
        )
        with self.driver.session(database=self.database) as session:
            result = session.run(cql, repo=repo, q=query.strip())
            return [dict(record["e"]) for record in result]

    def get_decisions_for_entity(self, entity_id: str) -> list[dict[str, Any]]:
        with self.driver.session(database=self.database) as session:
            result = session.run(GET_DECISIONS_GOVERNING_ENTITY, entity_id=entity_id)
            items: list[dict[str, Any]] = []
            for record in result:
                d = dict(record["d"])
                d["evidence"] = [dict(ev) for ev in record.get("evidence", [])]
                d["sources"] = [dict(s) for s in record.get("sources", [])]
                items.append(d)
            return items

    def get_subgraph(
        self,
        repo: str,
        entity_id: Optional[str] = None,
        node_cap: int = 80,
    ) -> dict[str, Any]:
        with self.driver.session(database=self.database) as session:
            if entity_id:
                result = session.run(
                    GET_SUBGRAPH_FOR_ENTITY,
                    entity_id=entity_id,
                    node_cap=node_cap,
                )
            else:
                result = session.run(
                    "MATCH (n {repo: $repo}) RETURN n LIMIT $cap",
                    repo=repo,
                    cap=node_cap,
                )
            nodes = [dict(r["n"]) for r in result]
            return {"nodes": nodes, "relationships": []}

    def close(self) -> None:
        self.driver.close()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_graph_store(cfg: Optional[Settings] = None) -> BaseGraphStore:
    """Returns Neo4jGraphStore if credentials exist, otherwise InMemoryGraphStore."""
    config = cfg or settings
    if config.neo4j_uri and config.neo4j_username and config.neo4j_password:
        return Neo4jGraphStore(
            uri=config.neo4j_uri,
            user=config.neo4j_username,
            password=config.neo4j_password,
            database=config.neo4j_database,
        )
    return InMemoryGraphStore()
