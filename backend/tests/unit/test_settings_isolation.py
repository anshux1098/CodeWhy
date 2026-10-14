"""The test suite must not depend on the developer's .env.

A unit test that reads the operator's real credentials is not a unit test: it
breaks the moment someone configures a real provider, and it can leak a real
credential into a subprocess or an error message.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

CLEARED_PREFIXES = ("LLM_", "NEO4J_", "GITHUB_", "AURA_", "EMBEDDING_")
CLEARED_EXACT = ("DATA_SOURCE", "ALLOW_MOCK_PROVIDERS", "APP_ENV", "LOG_LEVEL")


def test_the_conftest_clears_provider_environment() -> None:
    """The autouse fixture must exist and cover every provider variable."""
    import conftest as root_conftest

    assert hasattr(root_conftest, "isolated_settings_environment"), (
        "the root conftest must define the environment isolation fixture"
    )
    assert set(root_conftest.CLEARED_PREFIXES) == set(CLEARED_PREFIXES)
    assert set(root_conftest.CLEARED_EXACT) == set(CLEARED_EXACT)


def test_no_environment_variable_survives_inside_the_test_session() -> None:
    for name in os.environ:
        assert not name.startswith(CLEARED_PREFIXES), f"{name} leaked into the test session"
        assert name not in CLEARED_EXACT, f"{name} leaked into the test session"


def test_the_provider_factory_takes_settings_from_its_caller() -> None:
    """GraphDataSource must pass its own Settings, never read the module global."""
    import inspect

    from app.providers import llm_provider

    signature = inspect.signature(llm_provider.get_llm_provider)
    assert "cfg" in signature.parameters, (
        "get_llm_provider must accept the caller's Settings so tests are isolated"
    )


def test_data_source_passes_its_own_settings_to_the_provider() -> None:
    import inspect

    from app.services import data_source

    source = inspect.getsource(data_source.GraphDataSource.__init__)
    assert "get_llm_provider(cfg=self.settings)" in source, (
        "GraphDataSource must hand its Settings to the provider factory"
    )


@pytest.mark.parametrize(
    "module",
    [
        "app/services/answer.py",
        "app/services/retrieval.py",
        "app/services/data_source.py",
        "app/services/gate.py",
        "app/services/extraction.py",
        "app/services/entity_resolution.py",
        "app/stores/graph_store.py",
        "app/providers/embeddings.py",
    ],
)
def test_no_module_level_global_settings_read_in_service_code(module: str) -> None:
    """A bare `settings.` read in service code means behaviour the caller cannot control."""
    import re

    text = (ROOT / "backend" / module).read_text(encoding="utf-8")
    offenders = []
    for match in re.finditer(r"(?<![\w.])settings\.[a-z_]+", text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        line = text[line_start : text.find("\n", match.start())]
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # Passing the global in as a default is still a global read.
        offenders.append(stripped)
    assert not offenders, f"{module} reads the global settings: {offenders}"


def test_a_google_provider_in_the_environment_does_not_break_the_suite() -> None:
    """End to end: a real-looking .env must not change a single test result."""
    env = dict(os.environ)
    env["LLM_PROVIDER"] = "google"
    env["LLM_MODEL"] = "gemini-3.6-flash"
    env["LLM_API_KEY"] = "placeholder-not-a-real-key"
    env["NEO4J_URI"] = "neo4j+s://placeholder.example.invalid"
    env["NEO4J_USERNAME"] = "placeholder"
    env["NEO4J_PASSWORD"] = "placeholder"
    env["DATA_SOURCE"] = "graph"

    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         "backend/tests/unit/test_mock_honesty.py",
         "backend/tests/unit/test_data_source_seam.py",
         "-p", "no:warnings", "--tb=no", "-q"],
        cwd=str(ROOT), env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        "a provider configured in the environment changed the outcome:\n"
        + result.stdout[-2000:]
    )
