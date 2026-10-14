"""The linking layer and the graph build must actually run, and report honestly.

The audit found the whole linking module unreachable from any script, a Rule 3b
id that could never match a real document, and rebuild_graph that reported rows
processed rather than what ended up in the graph.
"""

from __future__ import annotations

import inspect
import json
import sqlite3
from pathlib import Path

import pytest

from app.services import linking
from app.stores.sqlite_cache import SqliteCache, stable_id


# --- rule 3b document ids must be constructible ----------------------------


def test_a_path_form_adr_target_produces_the_real_document_id() -> None:
    """docs/adr/0003.md must not collapse to docsadr0003.md."""
    repo = "acme/netclient"
    content = "Status: Superseded by docs/adr/0003.md\n"
    links = linking.extract_document_supersession("docs/adr/0001.md", content, repo)
    assert links, "the status line should produce a supersession edge"
    # Direction is Newer -[SUPERSEDES]-> Older, so the referenced document is the source.
    referenced = stable_id("doc", repo, "docs/adr/0003.md")
    self_doc = stable_id("doc", repo, "docs/adr/0001.md")
    assert any(link.source_id == referenced for link in links), (
        "the referenced document must be stored under the id a document is loaded with"
    )
    assert any(link.target_id == self_doc for link in links)
    assert not any("/" not in link.source_id.split(":")[-1] for link in links)


def test_the_same_document_id_helper_is_used_for_both_ends() -> None:
    import re

    source = inspect.getsource(linking.extract_document_supersession)
    assert 're.sub(r"[^\\w.-]"' not in source, "the path-stripping expression is still present"
    assert "make_document_link_id" in source or "stable_id" in source
    assert re.search(r"def extract_document_supersession", source)


# --- linking must be reachable from a script -------------------------------


def test_extract_script_calls_the_linking_layer() -> None:
    source = Path("scripts/extract.py").read_text(encoding="utf-8")
    for name in ("extract_revert_links", "extract_commit_pr_links",
                 "extract_issue_links", "extract_document_supersession",
                 "extract_containment_links"):
        assert name in source, f"{name} is still unreachable from scripts/extract.py"
    assert "put_links" in source, "links are computed but never written"


def test_ingest_script_still_does_not_import_linking_directly() -> None:
    """Phase 1 ingestion stays free of Phase 2 linking concerns."""
    source = Path("scripts/ingest.py").read_text(encoding="utf-8")
    assert "linking" not in source


def test_links_are_persisted_and_readable_after_a_link_pass(tmp_path: Path) -> None:
    with SqliteCache(tmp_path / "c.sqlite3") as cache:
        rows = linking.extract_revert_links(
            "a1b2c3d4e5f6",
            "Revert 'Add connection pool retry logic'\n\n"
            "This reverts commit 7b1c43d8a901eef234567890abcdef1234567890.\n",
            "acme/netclient",
        )
        assert rows
        written = cache.put_links([row.as_row() for row in rows])
        assert written == len(rows)
        stored = cache.links_for("acme/netclient")
        assert len(stored) == len(rows)
        assert stored[0]["rel_type"] == "REVERTS"


# --- rebuild_graph must be honest -------------------------------------------


def test_rebuild_graph_counts_come_from_the_graph_not_from_rows(tmp_path: Path) -> None:
    source = Path("scripts/rebuild_graph.py").read_text(encoding="utf-8")
    assert "rows_processed" not in source and "rows processed" not in source.lower()
    assert "count_nodes" in source or "read back" in source.lower() or "node_count" in source


def test_rebuild_graph_fails_loudly_on_a_missing_edge_endpoint(tmp_path: Path) -> None:
    from scripts import rebuild_graph

    assert hasattr(rebuild_graph, "ensure_endpoints")
    cache_path = tmp_path / "c.sqlite3"
    with SqliteCache(cache_path) as cache:
        cache.put_link({
            "id": "l1", "repo": "acme/netclient",
            "source_id": "commit:abc", "source_type": "commit",
            "rel_type": "REVERTS", "target_id": "pr:acme/netclient#7",
            "target_type": "pull_request", "is_direct": 1,
            "derivation_method": "revert_subject", "confidence": 1.0,
            "metadata_json": "{}", "created_at": "2026-01-01T00:00:00Z",
        })
    missing = rebuild_graph.ensure_endpoints(cache_path, "acme/netclient")
    assert missing, "a link whose endpoints do not exist must be reported"
    rel, ids = missing
    assert rel == "REVERTS"
    assert "commit:abc" in ids


def test_rebuild_graph_reports_actual_graph_state(tmp_path: Path) -> None:
    from scripts.rebuild_graph import InMemoryBuildResult, build_from_cache

    cache_path = tmp_path / "c.sqlite3"
    with SqliteCache(cache_path) as cache:
        cache.put_raw("pr", "acme/netclient", "pr:acme/netclient#7",
                      {"number": 7, "body": "text", "title": "t"})
        cache.put_decision({
            "id": "d1", "repo": "acme/netclient", "source_id": "pr:acme/netclient#7",
            "summary": "s", "rationale": "r", "state": "ACTIVE",
            "decision_type": "Other", "affected_entities": json.dumps(["pkg/config.py"]),
            "quote_verified": True, "created_at": "2026-01-01T00:00:00Z",
            "evaluated_at": "2026-01-01T00:00:00Z", "alternatives_considered": [],
            "constraints": [], "explicit_reversal_language": False, "unknown_fields": [],
            "extraction_version": "v1", "content_hash": "abc",
        })
        cache.put_evidence({
            "id": "ev1", "decision_id": "d1", "source_id": "pr:acme/netclient#7",
            "source_type": "pull_request",
            "source_url": "https://github.com/acme/netclient/pull/7",
            "quote": "some quote", "author": "ann", "timestamp": "2025-01-01T00:00:00Z",
            "classification": "explicit", "claim": "c", "quote_verified": 1,
            "created_at": "2026-01-01T00:00:00Z",
        })

    result = build_from_cache(cache_path, "acme/netclient")
    assert isinstance(result, InMemoryBuildResult)
    # Counts must reflect the graph, not the rows we happened to iterate.
    assert result.nodes > 0
    assert result.relationships >= 0
    assert result.counts["nodes"] == result.nodes
    assert result.counts["relationships"] == result.relationships


def test_dead_query_constants_are_gone_or_imported() -> None:
    """Either wire a constant in or delete it; do not leave it unreachable."""
    from app.graph import queries

    used: set[str] = set()
    for path in Path("backend/app").rglob("*.py"):
        if path.name == "queries.py":
            continue
        used.add(path.read_text(encoding="utf-8"))
    scripts = "\n".join(p.read_text(encoding="utf-8") for p in Path("scripts").glob("*.py"))
    everything = "\n".join(used) + scripts

    dead = [
        name for name in dir(queries)
        if name.startswith(("MERGE_", "GET_SUPERSEDED")) and name not in everything
    ]
    assert not dead, f"unreachable Cypher constants remain: {dead}"


def test_readme_relationship_count_matches_the_constants_in_use() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "15 relationships" not in readme, (
        "the README claims a relationship count that no longer matches the code"
    )
