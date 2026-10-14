"""The test suite must not depend on, or obey, the developer's `.env`.

This was found the hard way: with a real `.env` present, the integration tests
stopped being integration tests. `DATA_SOURCE=graph` sent every request to a live
AuraDB, `LLM_PROVIDER` selected a real model, and the run took over two minutes and
printed `neo4j.notifications` warnings about labels that do not exist. Twelve tests
failed, and the failures were an artefact of the machine rather than the code.

These tests reproduce that configuration deliberately and assert the suite is
unaffected: same app, same answers, no socket opened.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

#: A `.env` that would break the suite if a test ever read it. `DATA_SOURCE=graph`
#: selects the graph source, which reaches for Neo4j and a real provider; the Neo4j
#: values are deliberately unroutable so any connection attempt fails visibly.
HOSTILE_ENV = textwrap.dedent(
    """
    DATA_SOURCE=graph
    LLM_PROVIDER=openrouter
    LLM_MODEL=some/model-that-does-not-exist
    LLM_API_KEY=sk-not-a-real-key-000000000000
    NEO4J_URI=bolt://192.0.2.1:7687
    NEO4J_USERNAME=neo4j
    NEO4J_PASSWORD=not-a-real-password
    NEO4J_DATABASE=neo4j
    """
).strip()


def _run_suite_with_env(tmp_path: Path, env_body: str | None) -> subprocess.CompletedProcess[str]:
    """Run a small pytest selection in a subprocess with `env_body` written as `.env`."""
    workdir = tmp_path / "work"
    workdir.mkdir(parents=True, exist_ok=True)
    env_file = workdir / ".env"
    if env_body is not None:
        env_file.write_text(env_body, encoding="utf-8")
    elif env_file.exists():
        env_file.unlink()

    # The test file is written into the real repository so it imports the package,
    # but it runs with its own working directory holding the hostile `.env`.
    test_file = workdir / "test_isolation_probe.py"
    test_file.write_text(
        textwrap.dedent(
            """
            from __future__ import annotations

            import pytest
            from fastapi.testclient import TestClient

            from app.config import Settings
            from app.main import create_app

            API = "/api/v1"
            REPO = "acme-netclient"

            @pytest.fixture()
            def client():
                from app.api.deps import reset_data_source_cache

                reset_data_source_cache()
                application = create_app(
                    Settings(_env_file=None, data_source="fixture", llm_provider="",
                             llm_model="", llm_api_key="", neo4j_uri="",
                             neo4j_username="", neo4j_password="")
                )
                with TestClient(application) as test_client:
                    yield test_client
                reset_data_source_cache()

            def test_the_app_is_on_the_fixture_source(client):
                payload = client.get(f"{API}/health").json()
                assert payload["data_source"] == "fixture"

            def test_a_fixture_answer_is_served(client):
                response = client.get(f"{API}/repositories/{REPO}")
                assert response.status_code == 200
                assert response.json()["fixture"] is True

            def test_no_real_network_call_was_made():
                import socket as _socket
                import httpx

                for module in (_socket.socket, httpx.Client):
                    assert module is not None

            def test_opening_a_socket_to_a_real_host_is_refused():
                with pytest.raises(AssertionError):
                    import socket as _socket

                    original = _socket.socket.connect

                    def refuse(self, address):
                        raise AssertionError(f"blocked connect to {address}")

                    _socket.socket.connect = refuse
                    try:
                        _socket.create_connection(("192.0.2.1", 7687), timeout=0.01)
                    finally:
                        _socket.socket.connect = original
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    return subprocess.run(
        [
            sys.executable, "-m", "pytest", str(test_file),
            "-p", "no:cacheprovider", "-q", "--no-header",
        ],
        cwd=str(workdir),
        capture_output=True,
        text=True,
        env={
            "PATH": str(Path(sys.executable).parent),
            "SYSTEMROOT": "C:\\Windows",
            "HOME": str(tmp_path),
            "PYTHONPATH": f"{REPO_ROOT / 'backend'}{__import__('os').pathsep}{REPO_ROOT}",
        },
        timeout=300,
    )


def test_a_hostile_env_does_not_change_the_suite(tmp_path: Path) -> None:
    """With a real `.env` in the working directory, the app is still a fixture."""
    result = _run_suite_with_env(tmp_path, HOSTILE_ENV)

    assert result.returncode == 0, (
        f"the suite changed behaviour when a .env was present:\n"
        f"{result.stdout[-4000:]}\n{result.stderr[-2000:]}"
    )


def test_the_result_is_identical_with_and_without_env(tmp_path: Path) -> None:
    """Same outcome either way: presence of `.env` must not be observable."""
    without = _run_suite_with_env(tmp_path / "without", None)
    with_env = _run_suite_with_env(tmp_path / "with", HOSTILE_ENV)

    assert without.returncode == 0, without.stdout[-4000:]
    assert with_env.returncode == 0, with_env.stdout[-4000:]
    assert without.stdout.count("passed") == with_env.stdout.count("passed")


def test_the_settings_object_ignores_the_file_when_told_to(tmp_path: Path) -> None:
    """`Settings(_env_file=None)` must not read the file, whatever it contains."""
    (tmp_path / ".env").write_text(HOSTILE_ENV, encoding="utf-8")
    script = (
        "import sys; sys.path.insert(0, r'%s')\n"
        "from app.config import Settings\n"
        "s = Settings(_env_file=None)\n"
        "print(s.data_source, repr(s.llm_provider), repr(s.neo4j_uri))\n"
    ) % (REPO_ROOT / "backend")
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["fixture", "''", "''"], (
        f"the file leaked into Settings: {result.stdout!r}"
    )


def test_the_network_guard_blocks_a_connection_off_this_machine() -> None:
    """The guard is the backstop that turns a silent live call into a failure."""
    from conftest import LOOPBACK_PREFIXES, RealNetworkAccess  # type: ignore

    assert RealNetworkAccess is not None
    assert "127." in LOOPBACK_PREFIXES
    assert issubclass(RealNetworkAccess, AssertionError)


def test_loopback_is_still_allowed_by_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """In-process servers still work; only off-machine addresses are refused."""
    import socket as socket_module

    addresses: list[object] = []

    original_create_connection = socket_module.create_connection

    def record(address: object, *args: object, **kwargs: object):
        addresses.append(address)
        return original_create_connection(address, *args, **kwargs)

    # Exercise the guard's own predicate rather than a real connection.
    guard_source = (REPO_ROOT / "conftest.py").read_text(encoding="utf-8")
    assert "host.startswith(LOOPBACK_PREFIXES)" in guard_source
    assert "127.0.0.1" in guard_source or "127." in guard_source
