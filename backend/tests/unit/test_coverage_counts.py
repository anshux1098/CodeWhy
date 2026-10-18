"""Rebuild stores, on every CodeEntity and on the Repository, what was covered.

The definitions below are the contract the refusal wording reads at answer time:

* touched: PRs (non-noise and noise) whose changed files include the entity path.
* analyzed: sources with a completed extraction run, whether or not a verified
  decision came out of it.
* noise-skipped: sources removed by the noise filter.
* not analyzed: touched PRs that were neither analyzed nor noise-skipped.
* verified decision: quote_verified=1.

Counts are computed from the cache at rebuild time and stored in the graph, so the
API never has to read SQLite to say what was checked.
"""

from __future__ import annotations

from pathlib import Path

from app.stores.graph_store import InMemoryGraphStore, Neo4jGraphStore
from app.stores.sqlite_cache import SqliteCache
from scripts.rebuild_graph import build_from_cache, rebuild_graph

REPO = "urllib3/urllib3"
SLUG = "urllib3-urllib3"
CONFIG = "pkg/config.py"
SSL = "pkg/ssl.py"
NET = "pkg/net.py"
EMPTY = "pkg/empty.py"


def _seed_cache(path: Path) -> None:
    with SqliteCache(path) as cache:
        for number, title, files, author in (
            (1, "Add TLS settings for HTTP/2", [CONFIG, SSL], "ann"),
            (2, "Bump requests from 2 to 3", [CONFIG], "bot"),
            (3, "Fix typo in docs", [SSL], "ann"),
            (4, "Add connection pooling", [NET], "bob"),
            (5, "Update docs wording", [NET], "carol"),
        ):
            cache.put_raw("pr", REPO, str(number), {
                "number": number, "title": title, "body": "body",
                "author": author, "files": files,
            })
        cache.put_commit(REPO, {
            "sha": "c1", "authored_at": "2024-01-01T00:00:00Z",
            "committed_at": "2024-01-01T00:00:00Z", "author_name": "ann",
            "subject": "Change files", "message": "Change files",
        })
        for path in (CONFIG, SSL, NET, EMPTY):
            cache.put_commit_file("c1", {"path": path, "status": "M", "diff": ""})
        cache.record_extraction_source(REPO, "pr:urllib3/urllib3#1", "v1", "ok", "run1", decisions=1)
        cache.record_extraction_source(REPO, "pr:urllib3/urllib3#2", "v1", "no_decision", "run1")
        cache.record_extraction_source(REPO, "pr:urllib3/urllib3#3", "v1", "failed", "run1")
        cache.put_decision({
            "id": "dec_config", "source_id": "pr:urllib3/urllib3#1", "repo": REPO,
            "summary": "Add TLS settings", "decision_type": "design",
            "rationale": "TLS settings were added.", "state": "ACTIVE",
            "affected_entities": [CONFIG], "created_at": "2024-01-01T00:00:00Z",
            "extraction_version": "v1", "content_hash": "h1", "quote_verified": True,
        })
        # One verified decision that governs two paths. It must be counted once in the
        # repository and module totals, not once per path it affects.
        cache.put_decision({
            "id": "dec_both", "source_id": "pr:urllib3/urllib3#4", "repo": REPO,
            "summary": "Add pooling and TLS", "decision_type": "design",
            "rationale": "Both were added together.", "state": "ACTIVE",
            "affected_entities": [CONFIG, SSL], "created_at": "2024-01-01T00:00:00Z",
            "extraction_version": "v1", "content_hash": "h2", "quote_verified": True,
        })
        # A verified decision that governs a configuration key, not a file. It still
        # counts in the repository total even though it maps to no file path.
        cache.put_decision({
            "id": "dec_key", "source_id": "pr:urllib3/urllib3#5", "repo": REPO,
            "summary": "Cap the retries", "decision_type": "design",
            "rationale": "Retries were capped.", "state": "ACTIVE",
            "affected_entities": ["MAX_RETRIES"], "created_at": "2024-01-01T00:00:00Z",
            "extraction_version": "v1", "content_hash": "h3", "quote_verified": True,
        })
        cache.put_evidence({
            "id": "ev_config", "decision_id": "dec_config",
            "source_id": "pr:urllib3/urllib3#1", "source_type": "pull_request",
            "source_url": "https://github.com/urllib3/urllib3/pull/1",
            "quote": "TLS settings were added.", "quote_verified": 1,
            "classification": "explicit", "claim": "c",
            "created_at": "2024-01-01T00:00:00Z",
        })


def _coverage(store, path: str) -> dict:
    node = store.get_node(f"file:{REPO}:{path}")
    assert node is not None, f"no CodeEntity node for {path}"
    return node


def test_rebuild_stores_entity_coverage_counts(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.sqlite3"
    _seed_cache(cache_path)

    store = build_from_cache(cache_path, REPO).store

    config = _coverage(store, CONFIG)
    assert config["prs_touching"] == 2
    assert config["prs_analyzed"] == 2
    assert config["prs_noise_skipped"] == 1
    assert config["prs_not_analyzed"] == 0
    assert config["verified_decisions"] == 2

    ssl_node = _coverage(store, SSL)
    assert ssl_node["prs_touching"] == 2
    assert ssl_node["prs_analyzed"] == 1
    assert ssl_node["prs_noise_skipped"] == 1
    assert ssl_node["prs_not_analyzed"] == 0
    assert ssl_node["verified_decisions"] == 1

    net = _coverage(store, NET)
    assert net["prs_touching"] == 2
    assert net["prs_analyzed"] == 0
    assert net["prs_noise_skipped"] == 0
    assert net["prs_not_analyzed"] == 2
    assert net["verified_decisions"] == 0

    empty = _coverage(store, EMPTY)
    assert empty["prs_touching"] == 0
    assert empty["prs_not_analyzed"] == 0


def test_rebuild_stores_repository_coverage(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.sqlite3"
    _seed_cache(cache_path)

    store = build_from_cache(cache_path, REPO).store

    repo = store.get_node(SLUG)
    assert repo is not None
    assert repo["prs_fetched"] == 5
    assert repo["sources_analyzed"] == 2
    assert repo["prs_noise_skipped"] == 2
    # dec_config, dec_both (two paths) and dec_key (a config key, no path): three.
    assert repo["verified_decisions"] == 3
    assert "pkg/" in repo["scope"] or "file paths" in repo["scope"]


def test_the_verified_total_counts_decisions_not_paths(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.sqlite3"
    _seed_cache(cache_path)

    store = build_from_cache(cache_path, REPO).store

    # Three verified decisions: dec_config (CONFIG), dec_both (CONFIG, SSL) and
    # dec_key (a config key). Counting the paths they touch would give 3 as well here,
    # but dec_both's two paths must not be counted twice, so the module total is what
    # distinguishes the two rules.
    repo = store.get_node(SLUG)
    assert repo["verified_decisions"] == 3

    module = store.get_node(f"module:{REPO}:pkg")
    assert module is not None
    # dec_config and dec_both govern files under pkg; counting paths would give 3
    # (CONFIG twice). The distinct decisions are 2.
    assert module["verified_decisions"] == 2


def test_sources_analyzed_counts_distinct_completed_sources(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.sqlite3"
    with SqliteCache(cache_path) as cache:
        for number in (1, 2):
            cache.put_raw("pr", REPO, str(number), {
                "number": number, "title": "t", "body": "b", "files": [CONFIG],
            })
        cache.record_extraction_source(REPO, "pr:urllib3/urllib3#1", "v1", "ok", "run1", decisions=1)
        # The same source recorded again in a later run must not be counted twice.
        cache.record_extraction_source(REPO, "pr:urllib3/urllib3#1", "v1", "ok", "run2", decisions=1)
        cache.record_extraction_source(REPO, "pr:urllib3/urllib3#2", "v1", "no_decision", "run1")
        cache.record_extraction_source(REPO, "pr:urllib3/urllib3#3", "v1", "failed", "run1")

    store = build_from_cache(cache_path, REPO).store

    repo = store.get_node(SLUG)
    assert repo["sources_analyzed"] == 2


def test_coverage_counts_are_identical_across_two_rebuilds(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.sqlite3"
    _seed_cache(cache_path)
    store = InMemoryGraphStore()

    rebuild_graph(REPO, cache_path, store)
    first_entity = dict(_coverage(store, CONFIG))
    first_repo = dict(store.get_node(SLUG))

    rebuild_graph(REPO, cache_path, store)
    second_entity = dict(_coverage(store, CONFIG))
    second_repo = dict(store.get_node(SLUG))

    assert first_entity == second_entity
    # The rebuild timestamp legitimately differs between the two runs; every count
    # must not. Compare the node with that one volatile key removed.
    first_repo.pop("last_rebuilt_at", None)
    second_repo.pop("last_rebuilt_at", None)
    assert first_repo == second_repo


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def __iter__(self):
        return iter(self._rows)

    def single(self):
        return self._rows[0] if self._rows else None


class _CoverageRecordingDriver:
    """A fake driver that captures the properties sent to MERGE."""

    def __init__(self) -> None:
        self.node_writes: list[dict] = []

    def session(self, database=None):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query, **params):
        if "RETURN count(n) AS c" in query or "RETURN count(r) AS c" in query:
            return _Result([{"c": 0}])
        if "MERGE (n:" in query and "SET n +=" in query:
            self.node_writes.append(params.get("props", {}))
        return _Result([])

    def close(self) -> None:
        pass


def test_the_fake_driver_receives_coverage_properties(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.sqlite3"
    _seed_cache(cache_path)
    driver = _CoverageRecordingDriver()
    store = Neo4jGraphStore(driver=driver, database="db")

    rebuild_graph(REPO, cache_path, store)

    by_id = {props.get("id"): props for props in driver.node_writes}
    entity = by_id[f"file:{REPO}:{NET}"]
    assert entity["prs_touching"] == 2
    assert entity["prs_not_analyzed"] == 2

    repo = by_id[SLUG]
    assert repo["prs_fetched"] == 5
    assert repo["scope"]
