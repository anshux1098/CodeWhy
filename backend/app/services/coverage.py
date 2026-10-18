"""Coverage facts: what a repository's history was checked for.

These definitions are the contract the refusal wording reads at answer time. They
are computed once, at rebuild time, from the cache, and stored on the graph so the
API never has to read SQLite to say what was checked.

* touched: PRs (non-noise and noise) whose changed files include the entity path.
* analyzed: sources with a completed extraction run, whether or not a verified
  decision came out of it.
* noise-skipped: sources removed by the noise filter.
* not analyzed: touched PRs that were neither analyzed nor noise-skipped.
* verified decision: quote_verified=1.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

#: Extraction outcomes that mean the source was dealt with. A failed attempt is
#: not coverage: nothing was learned about that source.
COMPLETED_STATUSES: frozenset[str] = frozenset({"ok", "no_decision"})


def analyzed_source_ids(cache: Any, repo: str) -> set[str]:
    """Source ids with a completed extraction run, of any extraction version."""
    return {
        row["source_id"]
        for row in cache.extraction_sources(repo)
        if row["status"] in COMPLETED_STATUSES
    }


def _pr_files(payload: dict[str, Any]) -> list[str]:
    files = payload.get("files") or []
    return [str(path) for path in files if path]


@dataclass
class Coverage:
    """The coverage sets for one repository, before they are counted per entity."""

    touched: dict[str, set[str]] = field(default_factory=dict)
    pr_ids: set[str] = field(default_factory=set)
    analyzed: set[str] = field(default_factory=set)
    noise: set[str] = field(default_factory=set)
    verified_by_path: dict[str, int] = field(default_factory=dict)

    def counts_for(self, paths: Sequence[str]) -> dict[str, int]:
        """Count coverage for one entity, given the paths that identify it.

        A file entity passes one path; a module passes every file under it. The
        union is over PR ids, so a PR touching two files under one module is
        counted once.
        """
        touched: set[str] = set()
        for path in paths:
            touched |= self.touched.get(path, set())
        analyzed = touched & self.analyzed
        noise = touched & self.noise
        verified = sum(self.verified_by_path.get(path, 0) for path in paths)
        return {
            "prs_touching": len(touched),
            "prs_analyzed": len(analyzed),
            "prs_noise_skipped": len(noise),
            "prs_not_analyzed": len(touched - analyzed - noise),
            "verified_decisions": verified,
        }


def compute_coverage(cache: Any, repo: str) -> Coverage:
    """Read the cache and build the coverage sets for one repository."""
    covered = Coverage()
    for row in cache.fetch_raw_objects(repo, limit=10_000_000):
        if row["kind"] != "pr":
            continue
        pr_id = row["id"]
        covered.pr_ids.add(pr_id)
        try:
            payload = json.loads(row["payload"] or "{}")
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        for path in _pr_files(payload):
            covered.touched.setdefault(path, set()).add(pr_id)

    covered.analyzed = analyzed_source_ids(cache, repo)
    covered.noise = cache.noisy_record_ids(repo)

    for decision in cache.decisions_for_repo(repo):
        if not decision["quote_verified"]:
            continue
        for name in _loads(decision["affected_entities"]):
            if "/" in name:
                covered.verified_by_path[name] = covered.verified_by_path.get(name, 0) + 1
    return covered


def entity_counts(coverage: Coverage, path: str) -> dict[str, int]:
    """Stored on a file CodeEntity node."""
    return coverage.counts_for([path])


def module_counts(coverage: Coverage, module: str, file_paths: Sequence[str]) -> dict[str, int]:
    """Stored on a module CodeEntity node, aggregated over the files beneath it."""
    prefix = module.rstrip("/") + "/"
    under = [path for path in file_paths if path == module or path.startswith(prefix)]
    return coverage.counts_for(under)


def repository_counts(cache: Any, repo: str, coverage: Coverage) -> dict[str, Any]:
    """Stored on the Repository node: scope and repository-wide totals."""
    verified = sum(coverage.verified_by_path.values())
    return {
        "scope": scope_text(cache, repo),
        "prs_fetched": len(coverage.pr_ids),
        "sources_analyzed": len(coverage.analyzed),
        "prs_noise_skipped": len(coverage.noise & coverage.pr_ids),
        "verified_decisions": verified,
    }


def scope_text(cache: Any, repo: str) -> str:
    """What a rebuild analysed, from the cache's own provenance rows."""
    branch = "the ingested branch"
    caps: list[str] = []
    for run in cache.runs(repo):
        try:
            summary = json.loads(run["summary"] or "{}")
        except (TypeError, ValueError):
            summary = {}
        if not isinstance(summary, dict):
            summary = {}
        for note in summary.get("notes") or []:
            if str(note).startswith("clone branch "):
                branch = str(note)[len("clone branch "):]
        for skip in summary.get("skips") or []:
            if skip.get("bound") is not None:
                caps.append(f"{skip.get('reason')}={skip.get('bound')}")

    window = cache.commit_window(repo)
    oldest = (window.get("oldest") or "")[:10] or "unknown"
    newest = (window.get("newest") or "")[:10] or "unknown"
    paths = len(cache.iter_commit_files(repo))
    scope = (
        f"{repo} at branch {branch}, commits {oldest}..{newest}, "
        f"{paths} ingested file paths"
    )
    if caps:
        scope += "; ingest caps: " + ", ".join(sorted(set(caps)))
    return scope


def _loads(value: Any) -> list[str]:
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except (TypeError, ValueError):
        return []
    return [str(item) for item in loaded] if isinstance(loaded, list) else []
