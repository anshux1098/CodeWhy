"""Environment isolation for the whole test suite.

A developer running this project has real credentials in `.env`. Unit tests must
not read them: a test that depends on the operator's configuration is not
reproducible, breaks the moment a real provider is configured, and can leak a
credential into a subprocess or an error message.

The fixture below runs before every test, clears the provider variables and stops
`.env` from being loaded at all. Tests that need a specific value pass a
`Settings(_env_file=None, ...)` explicitly, so what they depend on is visible in
the test itself.
"""

from __future__ import annotations

import os
from typing import Iterator

import pytest

#: Any variable with one of these prefixes is cleared.
CLEARED_PREFIXES: tuple[str, ...] = ("LLM_", "NEO4J_", "GITHUB_", "AURA_", "EMBEDDING_")

#: Variables that would change which data source or provider is selected.
CLEARED_EXACT: tuple[str, ...] = (
    "DATA_SOURCE",
    "ALLOW_MOCK_PROVIDERS",
    "APP_ENV",
    "LOG_LEVEL",
)


@pytest.fixture(autouse=True)
def isolated_settings_environment() -> Iterator[None]:
    """Remove provider configuration from the environment for the duration of a test.

    ``.env`` is neutralised by removing ``DOTENV`` related indirection and by
    clearing the variables pydantic-settings would read from the file. Tests
    construct their own ``Settings(_env_file=None)``.
    """
    cleared: list[tuple[str, str | None]] = []
    for name in list(os.environ):
        if name.startswith(CLEARED_PREFIXES) or name in CLEARED_EXACT:
            cleared.append((name, os.environ.pop(name)))
    # pydantic-settings consults this to locate the env file.
    previous_env_file = os.environ.get("ENV_FILE")
    os.environ["ENV_FILE"] = ""
    try:
        yield
    finally:
        for name, value in cleared:
            if value is not None:
                os.environ[name] = value
        if previous_env_file is None:
            os.environ.pop("ENV_FILE", None)
        else:
            os.environ["ENV_FILE"] = previous_env_file
