"""Tests for scripts/preflight.py live checks."""

from __future__ import annotations

import sys, types
if "neo4j" not in sys.modules:
    try:
        import neo4j  # noqa: F401
    except ImportError:
        sys.modules["neo4j"] = types.SimpleNamespace(GraphDatabase=types.SimpleNamespace(driver=None))

import httpx
import pytest

from app.config import Settings


def _make_settings(**overrides):
    base = dict(
        _env_file=None,
        llm_provider="google",
        llm_model="gemini-test",
        llm_api_key="test-key-12345678",
        data_source="fixture",
        offline=True,
    )
    base.update(overrides)
    return Settings(**base)


def _patch_httpx(monkeypatch, handler):
    import app.providers.llm_provider as llmmod

    real = httpx.Client

    def factory(*args, **kwargs):
        return real(transport=httpx.MockTransport(handler), timeout=kwargs.get("timeout", 10))

    monkeypatch.setattr(llmmod.httpx, "Client", factory)


def test_connect_llm_passes_when_usage_is_missing(capsys, monkeypatch):
    import scripts.preflight as preflight

    monkeypatch.setattr(preflight, "settings", _make_settings())

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    _patch_httpx(monkeypatch, handler)
    assert preflight.connect_llm() is True
    out = capsys.readouterr().out
    assert "status=200" in out
    assert "usage not reported" in out
    assert "reply_chars=" in out


def test_connect_llm_passes_and_reports_tokens_when_present(capsys, monkeypatch):
    import scripts.preflight as preflight

    monkeypatch.setattr(preflight, "settings", _make_settings())

    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3},
            },
        )

    _patch_httpx(monkeypatch, handler)
    assert preflight.connect_llm() is True
    out = capsys.readouterr().out
    assert "tokens=13" in out


def test_connect_llm_fails_on_non_200(capsys, monkeypatch):
    import scripts.preflight as preflight

    monkeypatch.setattr(preflight, "settings", _make_settings())

    def handler(request):
        return httpx.Response(404, json={"error": "not found"})

    _patch_httpx(monkeypatch, handler)
    assert preflight.connect_llm() is False
    out = capsys.readouterr().out
    assert "404" in out


def test_connect_llm_fails_on_empty_reply(capsys, monkeypatch):
    import scripts.preflight as preflight

    monkeypatch.setattr(preflight, "settings", _make_settings())

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})

    _patch_httpx(monkeypatch, handler)
    assert preflight.connect_llm() is False


def test_connect_neo4j_uses_first_record_without_user_warning(monkeypatch, recwarn):
    import neo4j
    import scripts.preflight as preflight

    monkeypatch.setattr(
        preflight,
        "settings",
        _make_settings(
            neo4j_uri="bolt://example",
            neo4j_username="neo4j",
            neo4j_password="secret",
            neo4j_database="neo4j",
        ),
    )

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def run(self, query, *args, **kwargs):
            if "RETURN 1" in query:
                return iter([{"ok": 1}])
            return iter([{"v": "5.21.0"}])

    class FakeDriver:
        def session(self, database=None):
            return FakeSession()

        def close(self):
            pass

    monkeypatch.setattr(neo4j.GraphDatabase, "driver", lambda *a, **k: FakeDriver())

    assert preflight.connect_neo4j() is True
    user_warnings = [w for w in recwarn if issubclass(w.category, UserWarning)]
    assert not user_warnings


def test_connect_embeddings_fails_in_graph_mode_with_hash_fallback(capsys, monkeypatch):
    import scripts.preflight as preflight

    import app.providers.embeddings as embmod

    monkeypatch.setattr(
        preflight,
        "settings",
        _make_settings(data_source="graph", offline=True),
    )
    monkeypatch.setattr(
        embmod, "get_embedding_provider",
        lambda cfg=None: embmod.DeterministicFallbackEmbeddingProvider(),
    )

    assert preflight.connect_embeddings() is False
    out = capsys.readouterr().out
    assert "hash" in out.lower()


def test_connect_embeddings_passes_in_fixture_mode(capsys, monkeypatch):
    import app.providers.embeddings as embmod
    import scripts.preflight as preflight

    monkeypatch.setattr(
        preflight,
        "settings",
        _make_settings(data_source="fixture", offline=True),
    )
    # The provider is stubbed because the real one loads a 100MB model from
    # huggingface.co on first use. A unit test has no business doing that, and the
    # suite's network guard now fails such a test outright.
    monkeypatch.setattr(
        embmod, "get_embedding_provider",
        lambda cfg=None: embmod.DeterministicFallbackEmbeddingProvider(),
    )

    assert preflight.connect_embeddings() is True
    out = capsys.readouterr().out
    assert "dim=384" in out
