#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# Add backend to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import settings
from app.providers.embeddings import get_embedding_provider
from app.stores.graph_store import BaseGraphStore, get_graph_store
from app.stores.sqlite_cache import SqliteCache

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("codewhy.rebuild_graph")


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


def rebuild_graph(repo: str, cache_path: Path, store: BaseGraphStore) -> dict[str, int]:
    t0 = time.perf_counter()
    logger.info("Initializing graph schema (constraints and indexes)...")
    store.init_schema()

    if not cache_path.exists():
        logger.warning("Cache file %s does not exist. Created empty graph schema.", cache_path)
        return {"nodes": 0, "relationships": 0}

    cache = SqliteCache(cache_path)
    embedder = get_embedding_provider()

    counts = {"nodes": 0, "relationships": 0}

    # 1. Repository node
    parts = repo.split("/")
    owner = parts[0] if len(parts) > 1 else ""
    name = parts[1] if len(parts) > 1 else parts[0]
    store.merge_node("Repository", {
        "id": repo,
        "owner": owner,
        "name": name,
        "default_branch": "main",
        "created_at": "2026-01-01T00:00:00Z",
    })
    counts["nodes"] += 1

    # 2. Config Keys
    config_rows = cache.config_keys_for(repo)
    for c in config_rows:
        key_id = c["id"]
        store.merge_node("CodeEntity", {
            "id": key_id,
            "repo": repo,
            "name": c["name"],
            "path": c["file_path"],
            "entity_type": "ConfigKey",
            "created_at": c["created_at"],
        })
        counts["nodes"] += 1

    # 3. Decisions & Evidence
    decisions = cache.decisions_for_repo(repo)
    logger.info("Loading %d decisions into graph...", len(decisions))
    for d in decisions:
        dec_id = d["id"]
        embedding = embedder.embed_text(d["summary"])
        store.merge_node("Decision", {
            "id": dec_id,
            "repo": repo,
            "summary": d["summary"],
            "decision_type": d["decision_type"],
            "rationale": d["rationale"],
            "state": d["state"],
            "recorded_at": d["created_at"],
            "effective_at": d["created_at"],
            "ended_at": None,
            "evaluated_at": d["created_at"],
            "quote_verified": bool(d["quote_verified"]),
            "embedding": embedding,
        })
        counts["nodes"] += 1

        # Link DECIDED_IN
        store.merge_relationship("DECIDED_IN", dec_id, d["source_id"])
        counts["relationships"] += 1

        # Link GOVERNS to affected entities
        affected = json.loads(d["affected_entities"] or "[]")
        for ent_name in affected:
            # find or merge entity
            ent_id = f"entity:{repo}:{ent_name}"
            store.merge_node("CodeEntity", {
                "id": ent_id,
                "repo": repo,
                "name": ent_name,
                "path": ent_name,
                "entity_type": "File" if "/" in ent_name else "ConfigKey",
                "created_at": d["created_at"],
            })
            store.merge_relationship("GOVERNS", dec_id, ent_id)
            counts["relationships"] += 1

        # Evidence
        ev_rows = cache.evidence_for_decision(dec_id)
        for ev in ev_rows:
            ev_id = ev["id"]
            store.merge_node("Evidence", {
                "id": ev_id,
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
            counts["nodes"] += 1
            store.merge_relationship("SUPPORTED_BY", dec_id, ev_id)
            counts["relationships"] += 1

    # 4. Links table (REVERTS, SUPERSEDES, PART_OF, REFERENCES)
    link_rows = cache.links_for(repo)
    logger.info("Loading %d links into graph...", len(link_rows))
    for link in link_rows:
        store.merge_relationship(
            rel_type=link["rel_type"],
            from_id=link["source_id"],
            to_id=link["target_id"],
            properties={
                "confidence": link["confidence"],
                "derivation": link["derivation"],
            },
        )
        counts["relationships"] += 1

    dt = time.perf_counter() - t0
    logger.info(
        "Rebuild complete in %.2fs: %d nodes, %d relationships loaded.",
        dt,
        counts["nodes"],
        counts["relationships"],
    )
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
