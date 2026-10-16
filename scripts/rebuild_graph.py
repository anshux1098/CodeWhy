#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Optional

# Add backend to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import Settings, settings
from app.graph.ids import (
    entity_id_for,
    graph_id,
    source_label_for,
    source_number,
    source_text_from_payload,
    source_type_name,
    source_url,
    to_api_id,
)
from app.providers.embeddings import get_embedding_provider
from app.stores.graph_store import BaseGraphStore, get_graph_store
from app.stores.sqlite_cache import SqliteCache

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("codewhy.rebuild_graph")

# The Neo4j driver logs a notification for every MERGE at INFO — one per node and one
# per relationship, each of which is a multi-line block. That buries the run's own
# output and makes the log useless, so those notifications are raised to WARNING.
logging.getLogger("neo4j.notifications").setLevel(logging.WARNING)

#: Source kinds whose text is stored on the node so a quote can be re-verified later.
TEXT_BEARING_LABELS: frozenset[str] = frozenset({"PullRequest", "Issue", "Document"})


class RebuildGraphError(RuntimeError):
    """The graph could not be built faithfully from the cache."""


def graph_state(
    store: BaseGraphStore,
    *,
    excluded_placeholders: int = 0,
) -> dict[str, int]:
    """Count what is actually in the graph after a build.

    The count is read back from the store rather than accumulated from the rows that
    were iterated: a link whose endpoints were never created is dropped silently by
    MATCH, so a row count would overstate the result. `excluded_placeholders` is the
    number of decisions deliberately left out because no quote verified.
    """
    return {
        "nodes": int(store.node_count()),
        "relationships": int(store.relationship_count()),
        "excluded_placeholders": int(excluded_placeholders),
    }


def missing_endpoints(
    store: BaseGraphStore,
    link_rows: list,
    repo: str,
) -> list[tuple[str, list[str]]]:
    """Links whose endpoints do not exist, grouped by relationship type.

    Resolved through `get_node` rather than a duck-typed `nodes` mapping, so the check
    works against Neo4j too instead of silently returning nothing.
    """
    grouped: dict[str, list[str]] = {}
    for link in link_rows:
        present = (graph_id(link["source_id"], repo), graph_id(link["target_id"], repo))
        absent = [ident for ident in present if store.get_node(ident) is None]
        if absent:
            bucket = grouped.setdefault(link["rel_type"], [])
            for ident in absent:
                if ident not in bucket:
                    bucket.append(ident)
    return sorted(grouped.items())


def build_from_cache(
    cache_path: Path,
    repo: str,
    cfg: Optional[Settings] = None,
) -> "InMemoryBuildResult":
    """Build the graph into an in-memory store and report measured state.

    Used by tests and for a dry preview. Neo4j is not required.
    """
    from app.stores.graph_store import InMemoryGraphStore

    store = InMemoryGraphStore()
    counts = rebuild_graph(repo, cache_path, store, cfg=cfg)
    return InMemoryBuildResult(store, counts)


@dataclass
class InMemoryBuildResult:
    store: object
    counts: dict[str, int]

    @property
    def nodes(self) -> int:
        return self.counts["nodes"]

    @property
    def relationships(self) -> int:
        return self.counts["relationships"]


def ensure_endpoints(cache_path: Path, repo: str) -> tuple[str, list[str]] | None:
    """First group of link endpoints missing from the graph, for diagnostics."""
    from app.stores.graph_store import InMemoryGraphStore

    store = InMemoryGraphStore()
    try:
        rebuild_graph(repo, cache_path, store)
    except RebuildGraphError:
        with SqliteCache(cache_path) as cache:
            rows = cache.links_for(repo)
        groups = missing_endpoints(store, rows, repo)
        return groups[0] if groups else None
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recreate the Neo4j knowledge graph from SQLite cache."
    )
    parser.add_argument(
        "--repo",
        type=str,
        default="hynek/structlog",
        help="Repository identifier (owner/repo)",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=REPO_ROOT / "data" / "ingest.sqlite3",
        help="Path to SQLite cache file",
    )
    return parser.parse_args()


def _materialise_source_stub(
    store: BaseGraphStore,
    endpoint: str,
    repo: str,
    slug: str,
) -> bool:
    """Create a node for a source a link names but that was never ingested.

    Only a `pr`/`issue`/`doc`/`commit` endpoint is materialised, and only from its id:
    the node anchors the edge and records where it points. A `file` or `module` is not
    created here — those must be derived from real file history, so a missing one is
    reported rather than papered over.
    """
    label = source_label_for(endpoint)
    if label is None:
        return False
    properties: dict[str, Any] = {
        "id": endpoint,
        "repo": slug,
        "number": source_number(endpoint),
        "url": source_url(endpoint, repo),
        "created_at": "",
    }
    if label in TEXT_BEARING_LABELS:
        properties["text"] = ""
    store.merge_node(label, properties)
    return True


def rebuild_graph(
    repo: str,
    cache_path: Path,
    store: BaseGraphStore,
    cfg: Optional[Settings] = None,
) -> dict[str, int]:
    t0 = time.perf_counter()
    logger.info("Initializing graph schema (constraints and indexes)...")
    store.init_schema()

    if not cache_path.exists():
        logger.warning("Cache file %s does not exist. Created empty graph schema.", cache_path)
        return {"nodes": 0, "relationships": 0, "excluded_placeholders": 0}

    cache = SqliteCache(cache_path)
    # The caller's settings rather than the module-level one. `settings` is built
    # from `.env`, so relying on it here would make a test inherit whatever the
    # developer has configured, and make a run download model weights even when it
    # was told to stay offline. Passing `cfg` explicitly is what makes this
    # reproducible; a caller with no cfg gets the deterministic provider.
    embedder = get_embedding_provider(cfg=cfg or Settings(_env_file=None, offline=True))

    # The API route carries the repository id as one path segment, so the graph is
    # addressed by the slug while `full_name` keeps the raw `owner/name`.
    slug = to_api_id(repo)

    # 1. Repository node. Its id is the slug the API addresses it by; every other
    #    node carries the same slug as its `repo` property so a lookup matches.
    parts = repo.split("/")
    owner = parts[0] if len(parts) > 1 else ""
    name = parts[1] if len(parts) > 1 else parts[0]
    store.merge_node("Repository", {
        "id": slug,
        "repo": slug,
        "name": name,
        "full_name": repo,
        "owner": owner,
        "url": f"https://github.com/{repo}",
        "default_branch": "main",
        "created_at": "2026-01-01T00:00:00Z",
    })

    # 2. Source nodes. The links table names commits, pull requests, issues and
    #    documents as endpoints, so each has to exist as a node or the edge is
    #    dropped silently by MATCH. Text is stored on the text-bearing ones so a
    #    quote can be re-verified at answer time from the node alone.
    for row in cache.fetch_raw_objects(repo, limit=10_000_000):
        label = source_label_for(row["id"])
        if label is None:
            continue
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        properties = {
            "id": row["id"],
            "repo": slug,
            "number": source_number(row["id"]),
            "title": payload.get("title") or "",
            "url": payload.get("url") or source_url(row["id"], repo),
            "state": payload.get("state") or payload.get("status") or "",
            "created_at": payload.get("createdAt") or payload.get("created_at") or "",
        }
        if label in TEXT_BEARING_LABELS:
            properties["text"] = source_text_from_payload(payload)
        store.merge_node(label, properties)

    for commit in cache.iter_commits(repo):
        sha = commit.get("sha") or ""
        if not sha:
            continue
        store.merge_node("Commit", {
            "id": f"commit:{sha}",
            "repo": slug,
            "sha": sha,
            "subject": commit.get("subject") or "",
            "message": (commit.get("message") or "")[:2000],
            "url": f"https://github.com/{repo}/commit/{sha}",
            "created_at": "",
        })

    # 3. Code entities: configuration keys, files and their modules. A file node uses
    #    the same `file:<repo>:<path>` id the containment links name, so the same
    #    artefact is one node rather than one per referencing feature.
    for c in cache.config_keys_for(repo):
        store.merge_node("CodeEntity", {
            "id": c["id"],
            "repo": slug,
            "name": c["name"],
            "path": c["file_path"],
            "entity_type": "ConfigKey",
            "created_at": c["created_at"],
        })

    decisions = cache.decisions_for_repo(repo)
    verified = [d for d in decisions if d["quote_verified"]]
    excluded_placeholders = len(decisions) - len(verified)
    if excluded_placeholders:
        logger.info(
            "Skipping %d of %d decisions: no verified quote, so the record is a "
            "placeholder and does not belong in the graph.",
            excluded_placeholders, len(decisions),
        )

    file_paths: set[str] = set()
    for cf in cache.iter_commit_files(repo):
        path = cf.get("path")
        if path:
            file_paths.add(path)
    for d in verified:
        for ent_name in json.loads(d["affected_entities"] or "[]"):
            if "/" in ent_name:
                file_paths.add(ent_name)

    from app.services.linking import get_module_for_path

    module_names: set[str] = set()
    for path in sorted(file_paths):
        store.merge_node("CodeEntity", {
            "id": f"file:{repo}:{path}",
            "repo": slug,
            "name": path,
            "path": path,
            "entity_type": "File",
            "created_at": "",
        })
        module = get_module_for_path(path)
        if module:
            module_names.add(module)
    for module in sorted(module_names):
        store.merge_node("CodeEntity", {
            "id": f"module:{repo}:{module}",
            "repo": slug,
            "name": module,
            "path": module,
            "entity_type": "Module",
            "created_at": "",
        })

    # 4. Decisions & Evidence. Only a decision with a verified quote is graphed: a
    #    placeholder says something changed but carries no checkable citation.
    logger.info("Loading %d verified decisions into graph...", len(verified))
    for d in verified:
        dec_id = d["id"]
        source_id = d["source_id"]
        embedding = embedder.embed_text(d["summary"])
        store.merge_node("Decision", {
            "id": dec_id,
            "repo": slug,
            "summary": d["summary"],
            "decision_type": d["decision_type"],
            "rationale": d["rationale"],
            "state": d["state"],
            "recorded_at": d["created_at"],
            "effective_at": d["created_at"],
            "ended_at": None,
            "evaluated_at": d["created_at"],
            "quote_verified": bool(d["quote_verified"]),
            # Provenance, so a citation can be built without re-deriving it.
            "source_id": source_id,
            "source_type": source_type_name(source_id),
            "source_number": source_number(source_id),
            "source_url": source_url(source_id, repo),
            "embedding": embedding,
        })

        # A decision whose source row is gone from the cache would otherwise point at
        # a node that does not exist and lose its edge to MATCH.
        if store.get_node(source_id) is None:
            label = source_label_for(source_id) or "Document"
            store.merge_node(label, {
                "id": source_id, "repo": slug, "url": source_url(source_id, repo),
                "number": source_number(source_id), "created_at": "",
            })
        store.merge_relationship("DECIDED_IN", dec_id, source_id)

        for ent_name in json.loads(d["affected_entities"] or "[]"):
            ent_id = entity_id_for(ent_name, repo)
            store.merge_node("CodeEntity", {
                "id": ent_id,
                "repo": slug,
                "name": ent_name,
                "path": ent_name,
                "entity_type": "File" if "/" in ent_name else "ConfigKey",
                "created_at": d["created_at"],
            })
            store.merge_relationship("GOVERNS", dec_id, ent_id)

        for ev in cache.evidence_for_decision(dec_id):
            store.merge_node("Evidence", {
                "id": ev["id"],
                "repo": slug,
                "decision_id": dec_id,
                "source_id": ev["source_id"],
                "source_type": ev["source_type"],
                "source_url": ev["source_url"],
                "quote": ev["quote"],
                "author": ev["author"],
                "timestamp": ev["timestamp"],
                "classification": ev["classification"],
                "claim": ev["claim"],
                "quote_verified": bool(ev["quote_verified"]),
                "created_at": ev["created_at"],
            })
            store.merge_relationship("SUPPORTED_BY", dec_id, ev["id"])

    # 5. Links table (REVERTS, SUPERSEDES, PART_OF, REFERENCES, CONTAINS)
    link_rows = cache.links_for(repo)
    logger.info("Loading %d links into graph...", len(link_rows))

    # A commit can name a pull request that was never ingested, so the edge would
    # point at a node that does not exist and be dropped by MATCH. A source endpoint
    # is materialised as a node from the id alone; a file or module endpoint is not,
    # because those must come from the file history and a missing one is a real fault.
    for link in link_rows:
        for endpoint in (graph_id(link["source_id"], repo), graph_id(link["target_id"], repo)):
            if store.get_node(endpoint) is None:
                _materialise_source_stub(store, endpoint, repo, slug)

    dangling = missing_endpoints(store, link_rows, repo)
    if dangling:
        raise RebuildGraphError(
            f"{sum(len(ids) for _rel, ids in dangling)} link endpoints are not in the graph; "
            "the build would silently drop those edges. "
            f"examples: {[(rel, ids[:3]) for rel, ids in dangling[:3]]}"
        )
    for link in link_rows:
        store.merge_relationship(
            rel_type=link["rel_type"],
            from_id=graph_id(link["source_id"], repo),
            to_id=graph_id(link["target_id"], repo),
            properties={
                "confidence": link["confidence"],
                "derivation": link["derivation_method"],
            },
        )

    # Measured, not accumulated.
    counts = graph_state(store, excluded_placeholders=excluded_placeholders)

    dt = time.perf_counter() - t0
    logger.info(
        "Rebuild complete in %.2fs: %d nodes, %d relationships present in the graph "
        "(%d placeholder decisions excluded).",
        dt,
        counts["nodes"],
        counts["relationships"],
        counts["excluded_placeholders"],
    )
    logger.info("Nodes by label: %s", store.label_counts())
    logger.info("Relationships by type: %s", store.relationship_type_counts())
    return counts


def main() -> int:
    args = parse_args()
    store = get_graph_store(settings)
    try:
        rebuild_graph(args.repo, args.cache, store)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
