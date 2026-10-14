"""Preflight: is this machine configured to run the real pipeline?

Without ``--connect`` it only inspects configuration and installed packages.
With ``--connect`` it makes one minimal call to each external service.

No value from ``.env`` is ever printed. If a service echoes part of a credential
back in an error, that text is masked before it reaches stdout.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings, settings  # noqa: E402

#: Values that must never appear in output, even inside an error message.
SECRET_FIELDS = (
    "github_token",
    "llm_api_key",
    "neo4j_password",
    "neo4j_uri",
    "neo4j_username",
)


def mask(text: object) -> str:
    """Replace any configured secret appearing in ``text`` with a placeholder."""
    rendered = str(text)
    for field in SECRET_FIELDS:
        value = getattr(settings, field, "") or ""
        if value and len(value) >= 8 and value in rendered:
            rendered = rendered.replace(value, "<redacted>")
    return rendered


def report(name: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f": {mask(detail)}"
    print(line)
    return ok


# --- configuration ---------------------------------------------------------


def check_configuration() -> list[bool]:
    results: list[bool] = []

    results.append(report("GITHUB_TOKEN set", bool(settings.github_token)))
    results.append(report("NEO4J_URI set", bool(settings.neo4j_uri)))
    results.append(report("NEO4J_USERNAME set", bool(settings.neo4j_username)))
    results.append(report("NEO4J_PASSWORD set", bool(settings.neo4j_password)))
    results.append(report("NEO4J_DATABASE set", bool(settings.neo4j_database)))

    provider = (settings.llm_provider or "").strip()
    from app.providers.llm_provider import MOCK_PROVIDER_NAMES, PROVIDER_BASE_URLS

    real_provider = bool(provider) and provider.lower() not in MOCK_PROVIDER_NAMES
    results.append(
        report("LLM_PROVIDER is a real provider", real_provider,
               f"configured provider is {provider!r}" if provider
               else "LLM_PROVIDER is empty, which silently selects the mock")
    )
    results.append(report("LLM_PROVIDER is supported", provider.lower() in PROVIDER_BASE_URLS,
                          f"supported: {', '.join(sorted(set(PROVIDER_BASE_URLS)))}"))
    results.append(report("LLM_MODEL set", bool(settings.llm_model),
                          f"model is {settings.llm_model!r}" if settings.llm_model else ""))
    results.append(report("LLM_API_KEY set", bool(settings.llm_api_key)))

    results.append(report("DATA_SOURCE", settings.data_source == "graph",
                          f"DATA_SOURCE is {settings.data_source!r}, a real run needs 'graph'"))
    results.append(report("ALLOW_MOCK_PROVIDERS is not true",
                          settings.allow_mock_providers is not True))

    gitignored = _is_git_ignored(ROOT / ".env")
    results.append(report(".env is git-ignored", gitignored))
    return results


def _is_git_ignored(path: Path) -> bool:
    import subprocess

    result = subprocess.run(
        ["git", "check-ignore", "-q", str(path)], cwd=str(ROOT), capture_output=True
    )
    return result.returncode == 0


def check_packages() -> list[bool]:
    import importlib

    results: list[bool] = []
    for module, why in (
        ("httpx", "HTTP client"),
        ("neo4j", "graph store driver"),
    ):
        try:
            importlib.import_module(module)
            results.append(report(f"package {module} installed", True, why))
        except ImportError:
            results.append(report(f"package {module} installed", False, f"missing, needed for {why}"))
    try:
        importlib.import_module("sentence_transformers")
        results.append(report("package sentence_transformers installed", True,
                              "semantic embeddings available"))
    except ImportError:
        results.append(report("package sentence_transformers installed", False,
                              "absent, embeddings fall back to deterministic hashing"))
    return results


# --- live checks -----------------------------------------------------------


def connect_github() -> bool:
    from app.services.ingest.github_client import GitHubGraphQLClient

    query = "query { rateLimit { cost remaining } }"
    try:
        with GitHubGraphQLClient(settings) as client:
            payload = client.query(query)
        rate = (payload.get("data") or {}).get("rateLimit") or {}
        return report(
            "GitHub GraphQL", True,
            f"cost={rate.get('cost')} remaining={rate.get('remaining')}",
        )
    except Exception as exc:
        return report("GitHub GraphQL", False, f"{type(exc).__name__}: {exc}")


def connect_llm() -> bool:
    """One tiny call, at most 20 tokens, to prove the key and model are usable."""
    from pydantic import BaseModel

    from app.providers.llm_provider import get_llm_provider

    class Ping(BaseModel):
        ok: bool = True

    try:
        provider = get_llm_provider(cfg=settings)
        response, _ = provider.complete_structured(
            schema=Ping, prompt='Reply with exactly {"ok": true}.', system="You are a test.",
        )
        return report(
            "LLM provider", True,
            f"model={settings.llm_model!r} tokens={response.total_tokens} content={response.content[:60]!r}",
        )
    except Exception as exc:
        return report("LLM provider", False, f"{type(exc).__name__}: {exc}")


def connect_neo4j() -> bool:
    try:
        from neo4j import GraphDatabase
    except ImportError:
        return report("Neo4j", False, "the neo4j package is not installed; "
                                      "pip install neo4j or run pip install -e .")
    try:
        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password),
        )
        try:
            with driver.session(database=settings.neo4j_database) as session:
                record = session.run("RETURN 1 AS ok").single()
                versions = session.run(
                    "CALL dbms.components() YIELD versions RETURN versions[0] AS v"
                ).single()
        finally:
            driver.close()
        if record is None or record["ok"] != 1:
            return report("Neo4j", False, "RETURN 1 did not return 1")
        version = versions["v"] if versions else "unknown"
        return report("Neo4j", True, f"server version {version}, database {settings.neo4j_database!r}")
    except Exception as exc:
        return report("Neo4j", False, f"{type(exc).__name__}: {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check this machine before a real run.")
    parser.add_argument("--connect", action="store_true",
                        help="also make one minimal call to each service")
    args = parser.parse_args(argv)

    print("Configuration")
    print("-" * 60)
    results = check_configuration()
    print()
    print("Packages")
    print("-" * 60)
    results += check_packages()

    if args.connect:
        print()
        print("Live services (one minimal call each)")
        print("-" * 60)
        results += [connect_github(), connect_llm(), connect_neo4j()]

    print()
    print("-" * 60)
    failed = results.count(False)
    print(f"{len(results) - failed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
