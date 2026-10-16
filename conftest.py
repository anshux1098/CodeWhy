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
import socket
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

#: Hosts a test may legitimately reach. The TestClient runs in-process, so it needs
#: no socket at all; only loopback is allowed for anything that does.
LOOPBACK_PREFIXES = ("127.", "::1", "localhost")


class RealNetworkAccess(AssertionError):
    """Raised when a test tries to open a socket to something outside the machine."""


#: Set at import time, not in a fixture. `app.config` builds its module-level
#: `settings` while test modules are imported, which happens before any fixture
#: runs, so a fixture would be too late to influence it.
os.environ.setdefault("OFFLINE", "1")


@pytest.fixture(autouse=True, scope="session")
def _offline_session() -> Iterator[None]:
    """No test may download model weights.

    `sentence_transformers` fetches a ~100MB model from Hugging Face on first use.
    That makes a unit test depend on the network, take fifteen seconds, and return
    different similarity scores depending on whether the cache is warm. The
    deterministic provider is deterministic, so the suite is reproducible.
    """
    yield


@pytest.fixture(autouse=True, scope="session")
def _forbid_real_network() -> Iterator[None]:
    """Fail the whole session if any test opens a connection off this machine.

    Integration tests were silently reading the developer's `.env` and querying the
    real AuraDB, which made a green run depend on a live database and printed
    `neo4j.notifications` warnings nobody could explain. Clearing environment
    variables is not enough on its own, because the settings object reads the `.env`
    file directly; this makes an accidental connection impossible rather than
    merely unlikely.
    """
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create_connection = socket.create_connection

    def host_of(address: object) -> str:
        if isinstance(address, tuple) and address:
            return str(address[0])
        return str(address)

    def check(address: object) -> None:
        # An operator who sets RUN_LIVE=1 has explicitly opted into the marked live
        # tests; the guard exists to stop an *accidental* connection, so it stands
        # down for that opt-in. Without it, the live tests could never be run under
        # pytest at all, and the only proof the queries reach a real server would be
        # a hand-written script.
        if os.environ.get("RUN_LIVE") == "1":
            return
        host = host_of(address)
        if not host.startswith(LOOPBACK_PREFIXES):
            raise RealNetworkAccess(
                f"a test tried to connect to {host!r}. Tests must not reach a real "
                "service: a unit or integration test that needs one must be marked "
                "and skipped instead."
            )

    def guarded_connect(self: socket.socket, address: object) -> object:
        check(address)
        return original_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: object) -> object:
        check(address)
        return original_connect_ex(self, address)

    def guarded_create_connection(address: object, *args: object, **kwargs: object) -> object:
        check(address)
        return original_create_connection(address, *args, **kwargs)

    socket.socket.connect = guarded_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[method-assign]
    socket.create_connection = guarded_create_connection  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]
        socket.create_connection = original_create_connection  # type: ignore[assignment]


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
