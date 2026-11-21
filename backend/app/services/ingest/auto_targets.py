from __future__ import annotations

import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Optional

from app.services.config_keys import extract_python_constants
from app.services.ingest.git_collect import DEFAULT_DOC_DIRS
from app.services.ingest.git_probe import default_runner, parse_slug
from app.services.ingest.targets import IngestTargets, TargetConfigKey

# Non-code / config noise extensions skipped during primary hotspot ranking
SKIP_EXTENSIONS: frozenset[str] = frozenset({
    ".md", ".txt", ".rst", ".adoc", ".markdown",
    ".lock", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2",
})
SKIP_EXTENSIONS_SOFT: frozenset[str] = frozenset({".json"})

NON_SOURCE_DIRS: frozenset[str] = frozenset({
    "test", "tests", "testing", "__tests__", "spec",
    "doc", "docs", "documentation",
    "example", "examples", "sample", "samples",
    "benchmark", "benchmarks",
    ".github", ".circleci", ".gitlab",
    "node_modules", "vendor", "third_party", "dist", "build",
})

SKIP_FILENAMES: frozenset[str] = frozenset({
    "setup.py", "conftest.py", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
})


def is_candidate_source_file(path: str) -> bool:
    """Return True when a relative path looks like a real source file rather than test/doc/vendor noise."""
    clean = path.strip().replace("\\", "/")
    if not clean:
        return False
    p = Path(clean)
    if p.name in SKIP_FILENAMES:
        return False
    if p.suffix.lower() in SKIP_EXTENSIONS:
        return False
    parts_lower = {part.lower() for part in p.parts[:-1]}
    if parts_lower & NON_SOURCE_DIRS:
        return False
    if p.name.startswith("test_") or p.name.endswith("_test.py") or ".test." in p.name or ".spec." in p.name:
        return False
    return True


def rank_hotspot_files(
    clone_path: Path,
    top_n: int = 8,
    *,
    commit_window: int = 200,
) -> list[str]:
    """Discover the top N most frequently modified source files from recent git history."""
    cmd = ["git", "log", f"-n{commit_window}", "--name-only", "--format="]
    result = default_runner(cmd, clone_path)
    if result.returncode != 0:
        # Fallback without -n cap if needed
        result = default_runner(["git", "log", "--name-only", "--format="], clone_path)
        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)

    counter: Counter[str] = Counter()
    for line in (result.stdout or "").splitlines():
        path = line.strip()
        if not is_candidate_source_file(path):
            continue
        counter[path] += 1

    if not counter:
        # Relax non-source directory filter if repository is purely docs/scripts/tests
        for line in (result.stdout or "").splitlines():
            path = line.strip()
            if path and Path(path).suffix.lower() not in SKIP_EXTENSIONS:
                counter[path] += 1

    ranked = counter.most_common()
    primary = [p for p, _ in ranked if Path(p).suffix.lower() not in SKIP_EXTENSIONS_SOFT]
    if len(primary) >= top_n:
        return primary[:top_n]
    soft = [p for p, _ in ranked if Path(p).suffix.lower() in SKIP_EXTENSIONS_SOFT]
    return (primary + soft)[:top_n]


def discover_doc_dirs(clone_path: Path) -> list[str]:
    """Return existing documentation / ADR / RFC directories in the clone."""
    found: list[str] = []
    for candidate in DEFAULT_DOC_DIRS:
        if (clone_path / candidate).is_dir():
            found.append(candidate)
    return found


def discover_python_config_keys(
    clone_path: Path,
    files: list[str],
    repo: str,
    *,
    max_keys: int = 25,
) -> list[TargetConfigKey]:
    """Auto-scan target Python files with AST for module/class UPPER_CASE constants."""
    keys: list[TargetConfigKey] = []
    seen: set[tuple[str, str]] = set()
    for rel_path in files:
        if not rel_path.endswith(".py"):
            continue
        full_path = clone_path / rel_path
        if not full_path.is_file():
            continue
        try:
            source = full_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for entity in extract_python_constants(source, rel_path, repo):
            pair = (rel_path, entity.name)
            if pair in seen:
                continue
            seen.add(pair)
            keys.append(TargetConfigKey(file=rel_path, name=entity.name))
            if len(keys) >= max_keys:
                return keys
    return keys


def auto_discover_targets(
    repo: str,
    clone_path: Path,
    *,
    top_n: int = 8,
    commit_window: int = 200,
    save_path: Optional[Path] = None,
) -> IngestTargets:
    """Zero-config target discovery from a cloned repository.

    1. Ranks top hotspot source files via `git log -n <commit_window> --name-only`.
    2. Scans discovered `.py` files via Python `ast` for `UPPER_CASE` config constants.
    3. Auto-includes existing `docs/`, `adr/`, `rfcs/` directories.
    4. Optionally persists the generated `IngestTargets` JSON to `save_path`.
    """
    owner, name = parse_slug(repo)
    files = rank_hotspot_files(clone_path, top_n=top_n, commit_window=commit_window)
    if not files:
        raise RuntimeError(f"No source files found in git history for {owner}/{name}.")

    dirs = discover_doc_dirs(clone_path)
    config_keys = discover_python_config_keys(clone_path, files, repo)
    targets = IngestTargets(
        repo=f"{owner}/{name}",
        files=files,
        dirs=dirs,
        config_keys=config_keys,
    )

    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(
            json.dumps(targets.model_dump(), indent=2),
            encoding="utf-8",
        )

    return targets
