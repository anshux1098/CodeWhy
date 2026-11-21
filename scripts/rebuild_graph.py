#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
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
from app.services.coverage import (
    compute_coverage,
    entity_counts,
    module_counts,
    repository_counts,
)
from app.services.noise import label_repository_noise
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
        default="urllib3/urllib3",
        help="Repository identifier (owner/repo)",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=REPO_ROOT / "data" / "ingest.sqlite3",
        help="Path to SQLite cache file",
    )
    return parser.parse_args()


def _author_login(value: Any) -> str:
    """The login a raw payload names as a source's author.

    GitHub's payload uses `{"login": "..."}`; a plain string is accepted too so a
    cache that stored only the name still yields an author. Anything else is empty
    rather than guessed.
    """
    if isinstance(value, dict):
        login = value.get("login") or value.get("username")
        return str(login).strip() if login else ""
    if isinstance(value, str):
        return value.strip()
    return ""


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

    with SqliteCache(cache_path) as cache:
        return _rebuild_graph_with_cache(repo, cache, store, cfg=cfg, t0=t0)


def _rebuild_graph_with_cache(
    repo: str,
    cache: SqliteCache,
    store: BaseGraphStore,
    *,
    cfg: Optional[Settings] = None,
    t0: float = 0.0,
) -> dict[str, int]:
    # The caller's settings rather than the module-level one. `settings` is built
    # from `.env`, so relying on it here would make a test inherit whatever the
    # developer has configured, and make a run download model weights even when it
    # was told to stay offline. Passing `cfg` explicitly is what makes this
    # reproducible; a caller with no cfg gets the deterministic provider.
    embedder = get_embedding_provider(cfg=cfg or Settings(_env_file=None, offline=True))

    # The API route carries the repository id as one path segment, so the graph is
    # addressed by the slug while `full_name` keeps the raw `owner/name`.
    slug = to_api_id(repo)

    # A rebuild replaces the repository, it does not merge into the old graph. Rows
    # from an earlier run survive a MERGE forever, including decisions whose quote no
    # longer verifies and source nodes from before the slug change. Clear both id
    # forms for this repository only; other repositories in the same database stay.
    store.delete_repository((slug, repo))

    # Noise labels are additive metadata on the source records. Every stored pull
    # request is assessed and its labels persisted, so a consumer can flag — never
    # drop — an automated or generated change. They must be recomputed before the
    # coverage counts so a rule change is reflected in `prs_noise_skipped`.
    noise = label_repository_noise(cache, repo)
    logger.info(
        "Labelled noise: %d of %d pull requests flagged (%s).",
        noise["noisy"],
        noise["assessed"],
        ", ".join(f"{reason}={count}" for reason, count in sorted(noise["reasons"].items())),
    )

    # Coverage is computed from the cache and stored on the graph, so the answer
    # path can say what was checked without reading SQLite. See
    # `app/services/coverage.py` for the touched/analyzed/noise-skipped definitions.
    coverage = compute_coverage(cache, repo)

    # Track every node id merged during this rebuild locally so endpoint
    # validation and stub creation require ZERO remote get_node() round-trips.
    known_node_ids: set[str] = set()
    node_batches: dict[str, dict[str, dict[str, Any]]] = {}
    rel_batches: dict[str, list[dict[str, Any]]] = {}

    def _queue_node(label: str, props: dict[str, Any]) -> None:
        nid = str(props.get("id") or props.get("login") or "")
        if not nid:
            return
        known_node_ids.add(nid)
        node_batches.setdefault(label, {})[nid] = props

    # 1. Repository node. Its id is the slug the API addresses it by; every other
    #    node carries the same slug as its `repo` property so a lookup matches.
    parts = repo.split("/")
    owner = parts[0] if len(parts) > 1 else ""
    name = parts[1] if len(parts) > 1 else parts[0]
    _queue_node("Repository", {
        "id": slug,
        "repo": slug,
        "name": name,
        "full_name": repo,
        "owner": owner,
        "url": f"https://github.com/{repo}",
        "default_branch": "main",
        "created_at": "2026-01-01T00:00:00Z",
        # When this build wrote the node, so a caller can tell how fresh the graph is.
        "last_rebuilt_at": datetime.now(timezone.utc).isoformat(),
        **repository_counts(cache, repo, coverage),
    })

    def _queue_rel(
        rel_type: str,
        from_id: str,
        to_id: str,
        properties: Optional[dict[str, Any]] = None,
    ) -> None:
        rel_batches.setdefault(rel_type, []).append({
            "from_id": from_id,
            "to_id": to_id,
            "props": properties or {},
        })

    # 2. Source nodes & Person authorship/review edges.
    merged_at_by_source: dict[str, str] = {}
    author_by_source: dict[str, str] = {}
    person_logins: set[str] = set()

    def _ensure_person(login: str) -> Optional[str]:
        clean = (login or "").strip()
        if not clean or "@" in clean or clean.endswith("[bot]"):
            return None
        pid = f"person:{clean}"
        if clean not in person_logins:
            person_logins.add(clean)
            _queue_node("Person", {"id": pid, "login": clean, "repo": slug})
        return pid

    pr_count = 0
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
        author = _author_login(payload.get("author"))
        if author:
            author_by_source[str(row["id"])] = author
            pid = _ensure_person(author)
            if pid and label in ("PullRequest", "Issue", "Discussion"):
                _queue_rel("AUTHORED", pid, str(row["id"]))
        if label == "PullRequest":
            pr_count += 1
            merged = payload.get("mergedAt") or payload.get("merged_at")
            if merged:
                merged_at_by_source[str(row["id"])] = str(merged)
            properties["author"] = author or ""
            for rev in payload.get("reviews") or []:
                if isinstance(rev, dict):
                    rev_login = _author_login(rev.get("author"))
                    rpid = _ensure_person(rev_login)
                    if rpid and rev_login != author:
                        _queue_rel("REVIEWED", rpid, str(row["id"]), {"state": rev.get("state") or ""})
        _queue_node(label, properties)

    commit_count = 0
    for commit in cache.iter_commits(repo):
        sha = commit.get("sha") or ""
        if not sha:
            continue
        commit_count += 1
        cid = f"commit:{sha}"
        _queue_node("Commit", {
            "id": cid,
            "repo": slug,
            "sha": sha,
            "subject": commit.get("subject") or "",
            "message": (commit.get("message") or "")[:2000],
            "url": f"https://github.com/{repo}/commit/{sha}",
            "created_at": commit.get("authored_at") or "",
        })
        c_author = (commit.get("author_name") or "").strip()
        if c_author and " " not in c_author:
            cpid = _ensure_person(c_author)
            if cpid:
                _queue_rel("AUTHORED", cpid, cid)

    # 3. Code entities: configuration keys, files and their modules.
    entity_ids_seen: set[str] = set()
    for c in cache.config_keys_for(repo):
        entity_ids_seen.add(c["id"])
        cfg_cov = entity_counts(coverage, c["file_path"])
        _queue_node("CodeEntity", {
            "id": c["id"],
            "repo": slug,
            "name": c["name"],
            "path": c["file_path"],
            "entity_type": "ConfigKey",
            "created_at": c["created_at"],
            "decision_count": cfg_cov.get("verified_decisions", 0),
            **cfg_cov,
        })

    decisions = [dict(d) for d in cache.decisions_for_repo(repo)]
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
        fid = f"file:{repo}:{path}"
        entity_ids_seen.add(fid)
        f_cov = entity_counts(coverage, path)
        _queue_node("CodeEntity", {
            "id": fid,
            "repo": slug,
            "name": path,
            "path": path,
            "entity_type": "File",
            "created_at": "",
            "decision_count": f_cov.get("verified_decisions", 0),
            **f_cov,
        })
        module = get_module_for_path(path)
        if module:
            module_names.add(module)
    ordered_paths = sorted(file_paths)
    for module in sorted(module_names):
        mid = f"module:{repo}:{module}"
        entity_ids_seen.add(mid)
        m_cov = module_counts(coverage, module, ordered_paths)
        _queue_node("CodeEntity", {
            "id": mid,
            "repo": slug,
            "name": module,
            "path": module,
            "entity_type": "Module",
            "created_at": "",
            "decision_count": m_cov.get("verified_decisions", 0),
            **m_cov,
        })

    # 4. Links & Supersession Analysis (Phase 4)
    link_rows = [dict(row) for row in cache.links_for(repo)]
    from app.services.supersession import compute_supersession_edges
    from app.services.state import compute_decision_states

    super_edges = compute_supersession_edges(verified, links=link_rows)
    state_analysis = compute_decision_states(verified, edges=super_edges)

    # 6C: Batch-embed full decision text (entities + summary + rationale)
    logger.info("Loading %d verified decisions into graph...", len(verified))
    embed_inputs = []
    parsed_entities_by_dec: list[list[str]] = []
    for d in verified:
        ents = json.loads(d["affected_entities"] or "[]")
        parsed_entities_by_dec.append(ents)
        ents_str = " ".join(str(e) for e in ents)
        embed_inputs.append(f"{ents_str} {d['summary']} {d.get('rationale') or ''}".strip())
    embeddings = embedder.embed_batch(embed_inputs) if embed_inputs else []

    for idx, d in enumerate(verified):
        dec_id = d["id"]
        source_id = d["source_id"]
        embedding = embeddings[idx]
        st_res = state_analysis.states.get(dec_id)
        computed_state = st_res.state.value if st_res else d["state"]
        supersedes_list = st_res.supersedes if st_res else []
        superseded_by_list = st_res.superseded_by if st_res else []
        rule_val = st_res.rule if st_res else None

        _queue_node("Decision", {
            "id": dec_id,
            "repo": slug,
            "summary": d["summary"],
            "decision_type": d["decision_type"],
            "rationale": d["rationale"],
            "state": computed_state,
            "supersedes": supersedes_list,
            "superseded_by": superseded_by_list,
            "rule": rule_val,
            "recorded_at": None,
            "effective_at": merged_at_by_source.get(source_id),
            "ended_at": None,
            "evaluated_at": d["created_at"],
            "author": author_by_source.get(source_id) or "",
            "quote_verified": bool(d["quote_verified"]),
            "source_id": source_id,
            "source_type": source_type_name(source_id),
            "source_number": source_number(source_id),
            "source_url": source_url(source_id, repo),
            "embedding": embedding,
        })

        if source_id not in known_node_ids:
            label = source_label_for(source_id) or "Document"
            _queue_node(label, {
                "id": source_id, "repo": slug, "url": source_url(source_id, repo),
                "number": source_number(source_id), "created_at": "",
            })
        _queue_rel("DECIDED_IN", dec_id, source_id)

        for ent_name in parsed_entities_by_dec[idx]:
            ent_id = entity_id_for(ent_name, repo)
            if ent_id not in known_node_ids:
                entity_ids_seen.add(ent_id)
                e_cov = entity_counts(coverage, ent_name)
                _queue_node("CodeEntity", {
                    "id": ent_id,
                    "repo": slug,
                    "name": ent_name,
                    "path": ent_name,
                    "entity_type": "File" if "/" in ent_name else "ConfigKey",
                    "created_at": d["created_at"],
                    "decision_count": e_cov.get("verified_decisions", 0),
                    **e_cov,
                })
            _queue_rel("GOVERNS", dec_id, ent_id)

        for ev in cache.evidence_for_decision(dec_id):
            _queue_node("Evidence", {
                "id": ev["id"],
                "repo": slug,
                "decision_id": dec_id,
                "source_id": ev["source_id"],
                "source_type": ev["source_type"],
                "source_url": ev["source_url"],
                "quote": ev["quote"],
                "author": ev["author"] or author_by_source.get(ev["source_id"]) or "",
                "timestamp": ev["timestamp"],
                "classification": ev["classification"],
                "claim": ev["claim"],
                "quote_verified": bool(ev["quote_verified"]),
                "created_at": ev["created_at"],
            })
            _queue_rel("SUPPORTED_BY", dec_id, ev["id"])

    # 6D: Update Repository node with exact pre-stored counts
    repo_props = node_batches.get("Repository", {}).get(slug)
    if repo_props is not None:
        repo_props["decisions_count"] = len(verified)
        repo_props["entities_count"] = len(entity_ids_seen)
        repo_props["pull_requests_count"] = pr_count
        repo_props["commits_count"] = commit_count

    # 5. Links table (REVERTS, SUPERSEDES, PART_OF, REFERENCES, CONTAINS, IMPORTS, TRIGGERED_BY)
    logger.info("Loading %d links into graph...", len(link_rows))
    dangling_grouped: dict[str, list[str]] = {}
    for link in link_rows:
        for endpoint in (graph_id(link["source_id"], repo), graph_id(link["target_id"], repo)):
            if endpoint not in known_node_ids:
                lbl = source_label_for(endpoint)
                if lbl is not None:
                    stub_props: dict[str, Any] = {
                        "id": endpoint,
                        "repo": slug,
                        "number": source_number(endpoint),
                        "url": source_url(endpoint, repo),
                        "created_at": "",
                    }
                    if lbl in TEXT_BEARING_LABELS:
                        stub_props["text"] = ""
                    _queue_node(lbl, stub_props)
                else:
                    bucket = dangling_grouped.setdefault(link["rel_type"], [])
                    if endpoint not in bucket:
                        bucket.append(endpoint)

    if dangling_grouped:
        dangling = sorted(dangling_grouped.items())
        raise RebuildGraphError(
            f"{sum(len(ids) for _rel, ids in dangling)} link endpoints are not in the graph; "
            "the build would silently drop those edges. "
            f"examples: {[(rel, ids[:3]) for rel, ids in dangling[:3]]}"
        )

    for link in link_rows:
        _queue_rel(
            link["rel_type"],
            graph_id(link["source_id"], repo),
            graph_id(link["target_id"], repo),
            {
                "confidence": link["confidence"],
                "derivation": link["derivation_method"],
            },
        )

    for s_edge in super_edges:
        if s_edge.source_decision_id in known_node_ids and s_edge.target_decision_id in known_node_ids:
            _queue_rel(
                "SUPERSEDES",
                s_edge.source_decision_id,
                s_edge.target_decision_id,
                {
                    "rule": s_edge.rule,
                    "method": s_edge.method,
                    "confidence": s_edge.confidence,
                    "source_evidence_id": s_edge.source_evidence_id,
                    "review_state": s_edge.review_state,
                    "evaluated_at": s_edge.evaluated_at,
                },
            )

    # Flush all node batches first, then all relationship batches (via Cypher UNWIND on Neo4j)
    for lbl, rows_map in node_batches.items():
        store.merge_nodes_batch(lbl, list(rows_map.values()))
    for rtype, rel_rows in rel_batches.items():
        store.merge_relationships_batch(rtype, rel_rows)

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
