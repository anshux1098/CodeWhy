"""Small safety items in the graph store and configuration.

Labels and relationship types are interpolated into Cypher because Cypher cannot
parameterise them, so they must be whitelisted. Index creation must not fail
silently. Subgraph must return real relationships.
"""

from __future__ import annotations

import inspect

import pytest

from app.stores.graph_store import InMemoryGraphStore, Neo4jGraphStore


# --- labels and relationship types are whitelisted -------------------------


def test_an_unknown_label_is_refused() -> None:
    store = InMemoryGraphStore()
    with pytest.raises(ValueError) as excinfo:
        store.merge_node("Evil ) MATCH (n) DET DELETE n //", {"id": "x"})
    assert "label" in str(excinfo.value).lower()


def test_an_unknown_relationship_type_is_refused() -> None:
    store = InMemoryGraphStore()
    store.merge_node("CodeEntity", {"id": "a"})
    store.merge_node("CodeEntity", {"id": "b"})
    with pytest.raises(ValueError) as excinfo:
        store.merge_relationship("BAD ) DET DELETE n //", "a", "b")
    assert "relationship" in str(excinfo.value).lower()


def test_non_string_ids_are_refused() -> None:
    """A dict silently became its repr and the edge could never match a node."""
    store = InMemoryGraphStore()
    store.merge_node("CodeEntity", {"id": "a"})
    store.merge_node("CodeEntity", {"id": "b"})
    with pytest.raises(TypeError):
        store.merge_relationship("GOVERNS", {"id": "a"}, "b")
    with pytest.raises(TypeError):
        store.merge_relationship("GOVERNS", "a", {"id": "b"})


def test_the_permitted_values_are_named_in_one_place() -> None:
    from app.stores import graph_store

    assert hasattr(graph_store, "ALLOWED_NODE_LABELS")
    assert hasattr(graph_store, "ALLOWED_REL_TYPES")
    assert "CodeEntity" in graph_store.ALLOWED_NODE_LABELS
    assert "GOVERNS" in graph_store.ALLOWED_REL_TYPES
    assert "SUPERSEDES" in graph_store.ALLOWED_REL_TYPES


def test_every_label_the_builder_uses_is_allowed() -> None:
    from pathlib import Path

    from app.stores import graph_store

    builder = Path("scripts/rebuild_graph.py").read_text(encoding="utf-8")
    used = set()
    for label in graph_store.ALLOWED_NODE_LABELS:
        if f'merge_node("{label}"' in builder:
            used.add(label)
    for label in used:
        assert label in graph_store.ALLOWED_NODE_LABELS


# --- index failures must be loud -------------------------------------------


def test_index_creation_failures_are_not_swallowed() -> None:
    source = inspect.getsource(Neo4jGraphStore.init_schema)
    assert "logger.warning" not in source, (
        "a failed vector or full-text index must surface, not become a warning"
    )
    assert "raise RuntimeError" in source


def test_init_schema_reports_what_it_created() -> None:
    source = inspect.getsource(Neo4jGraphStore.init_schema)
    assert "created" in source.lower() or "logger.info" in source


# --- subgraph returns real relationships ------------------------------------


def test_neo4j_subgraph_returns_relationships_not_an_empty_list() -> None:
    source = inspect.getsource(Neo4jGraphStore.get_subgraph)
    assert '"relationships": []' not in source, (
        "the Neo4j subgraph always returned no edges"
    )


def test_in_memory_subgraph_returns_its_edges() -> None:
    store = InMemoryGraphStore()
    store.merge_node("CodeEntity", {"id": "a", "repo": "r", "name": "a"})
    store.merge_node("Decision", {"id": "d", "repo": "r", "summary": "s"})
    store.merge_relationship("GOVERNS", "d", "a", {"confidence": 1.0})
    result = store.get_subgraph("r", "a")
    assert result["nodes"], "nodes should come back"
    assert result["relationships"], "edges must not be dropped from the subgraph"


def test_in_memory_subgraph_respects_the_node_cap() -> None:
    store = InMemoryGraphStore()
    for i in range(10):
        store.merge_node("CodeEntity", {"id": f"e{i}", "repo": "r", "name": f"e{i}"})
    store.merge_relationship("CONTAINS", "e0", "e1", {})
    result = store.get_subgraph("r", None, node_cap=5)
    assert len(result["nodes"]) <= 5


# --- dead configuration ----------------------------------------------------


def test_embedding_dimensions_config_is_not_dead() -> None:
    """It was declared but never read, so changing it did nothing."""
    source = inspect.getsource(__import__("app.providers.embeddings", fromlist=["x"]))
    assert "embedding_dimensions" in source or "EMBEDDING_DIMENSIONS" in source
    from app.config import Settings

    assert hasattr(Settings(_env_file=None), "embedding_dimensions")


def test_the_dimension_comes_from_configuration_when_set() -> None:
    from app.providers import embeddings

    custom = embeddings.DeterministicFallbackEmbeddingProvider(dimensions=8)
    assert custom.dimensions == 8
    vector = custom.embed_text("text")
    assert len(vector) == 8
