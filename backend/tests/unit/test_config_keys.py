from __future__ import annotations

from pathlib import Path

import pytest

from app.services.config_keys import (
    ConfigKeyEntity,
    ConfigValueChange,
    build_config_value_history,
    extract_config_keys_from_source,
    extract_env_keys,
    extract_json_keys,
    extract_python_constants,
    extract_toml_keys,
    extract_value_changes_from_diff,
    extract_yaml_keys,
    make_config_id,
    make_config_containment_link,
)
from app.stores.sqlite_cache import SqliteCache


REPO = "urllib3/urllib3"


# ---------------------------------------------------------------------------
# Python constant extraction via ast
# ---------------------------------------------------------------------------

PYTHON_SOURCE = '''\
"""Module docstring."""
from __future__ import annotations
from typing import Final

MAX_RETRIES: Final[int] = 3
DEFAULT_TIMEOUT = 30
_PRIVATE = "not a constant"
lower_case = 42

ALPN_PROTOCOLS = ("http/1.1",)
SSL_VERSION_TO_TLS_VERSION = {1: 2}

class PoolManager:
    DEFAULT_POOL_SIZE = 10
    max_connections = 5  # not upper
'''


def test_python_module_level_constants_extracted() -> None:
    results = extract_python_constants(PYTHON_SOURCE, "src/urllib3/poolmanager.py", REPO)
    names = {r.name for r in results}
    assert "MAX_RETRIES" in names
    assert "DEFAULT_TIMEOUT" in names
    assert "ALPN_PROTOCOLS" in names
    assert "SSL_VERSION_TO_TLS_VERSION" in names


def test_python_private_and_lower_case_excluded() -> None:
    results = extract_python_constants(PYTHON_SOURCE, "src/urllib3/poolmanager.py", REPO)
    names = {r.name for r in results}
    assert "_PRIVATE" not in names
    assert "lower_case" not in names


def test_python_class_attribute_constants_extracted() -> None:
    results = extract_python_constants(PYTHON_SOURCE, "src/urllib3/poolmanager.py", REPO)
    names = {r.name for r in results}
    assert "PoolManager.DEFAULT_POOL_SIZE" in names
    assert "PoolManager.max_connections" not in names


def test_python_constant_values_are_correct() -> None:
    results = extract_python_constants(PYTHON_SOURCE, "src/urllib3/poolmanager.py", REPO)
    by_name = {r.name: r for r in results}
    assert by_name["MAX_RETRIES"].current_value == "3"
    assert by_name["DEFAULT_TIMEOUT"].current_value == "30"


def test_python_constant_ids_are_stable() -> None:
    results = extract_python_constants(PYTHON_SOURCE, "src/urllib3/poolmanager.py", REPO)
    by_name = {r.name: r for r in results}
    assert by_name["MAX_RETRIES"].id == make_config_id(REPO, "src/urllib3/poolmanager.py", "MAX_RETRIES")


def test_python_source_with_syntax_error_returns_empty() -> None:
    results = extract_python_constants("def broken(:\n    pass", "bad.py", REPO)
    assert results == []


def test_python_constants_have_line_numbers() -> None:
    results = extract_python_constants(PYTHON_SOURCE, "src/urllib3/poolmanager.py", REPO)
    by_name = {r.name: r for r in results}
    assert by_name["MAX_RETRIES"].line_number is not None
    assert by_name["MAX_RETRIES"].line_number >= 1


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

JSON_SOURCE = """\
{
  "timeout": 30,
  "retry": {"max_attempts": 3, "backoff": 0.5},
  "tls": {"verify": true}
}
"""


def test_json_keys_extracted_flat() -> None:
    results = extract_json_keys(JSON_SOURCE, "config/settings.json", REPO)
    names = {r.name for r in results}
    assert "timeout" in names
    assert "retry.max_attempts" in names
    assert "retry.backoff" in names
    assert "tls.verify" in names


def test_json_file_type_is_json() -> None:
    results = extract_json_keys(JSON_SOURCE, "settings.json", REPO)
    assert all(r.file_type == "json" for r in results)


def test_invalid_json_returns_empty() -> None:
    results = extract_json_keys("not json {{{", "bad.json", REPO)
    assert results == []


# ---------------------------------------------------------------------------
# YAML extraction
# ---------------------------------------------------------------------------

YAML_SOURCE = """\
server:
  host: localhost
  port: 8080
database:
  pool_size: 5
  timeout: 30
"""


def test_yaml_keys_extracted_flat() -> None:
    results = extract_yaml_keys(YAML_SOURCE, "config.yaml", REPO)
    names = {r.name for r in results}
    assert "server.host" in names
    assert "server.port" in names
    assert "database.pool_size" in names
    assert "database.timeout" in names


def test_yaml_file_type_is_yaml() -> None:
    results = extract_yaml_keys(YAML_SOURCE, "config.yml", REPO)
    assert all(r.file_type == "yaml" for r in results)


# ---------------------------------------------------------------------------
# TOML extraction
# ---------------------------------------------------------------------------

TOML_SOURCE = """\
[tool.pytest]
timeout = 60
addopts = "-x --tb=short"

[project]
name = "urllib3"
version = "2.0.0"
"""


def test_toml_keys_extracted() -> None:
    results = extract_toml_keys(TOML_SOURCE, "pyproject.toml", REPO)
    names = {r.name for r in results}
    assert "tool.pytest.timeout" in names
    assert "project.name" in names
    assert "project.version" in names


def test_toml_file_type_is_toml() -> None:
    results = extract_toml_keys(TOML_SOURCE, "pyproject.toml", REPO)
    assert all(r.file_type == "toml" for r in results)


# ---------------------------------------------------------------------------
# .env extraction
# ---------------------------------------------------------------------------

ENV_SOURCE = """\
# Application config
GITHUB_TOKEN=ghp_secret_token
MAX_WORKERS=4
DATABASE_URL="postgresql://localhost/db"
export LOG_LEVEL='DEBUG'
ignored line without equals
"""


def test_env_keys_extracted() -> None:
    results = extract_env_keys(ENV_SOURCE, ".env", REPO)
    names = {r.name for r in results}
    assert "GITHUB_TOKEN" in names
    assert "MAX_WORKERS" in names
    assert "DATABASE_URL" in names
    assert "LOG_LEVEL" in names


def test_env_keys_strip_quotes() -> None:
    results = extract_env_keys(ENV_SOURCE, ".env", REPO)
    by_name = {r.name: r for r in results}
    assert by_name["DATABASE_URL"].current_value == "postgresql://localhost/db"
    assert by_name["LOG_LEVEL"].current_value == "DEBUG"


def test_env_comments_and_invalid_lines_ignored() -> None:
    results = extract_env_keys(ENV_SOURCE, ".env", REPO)
    names = {r.name for r in results}
    assert "ignored line without equals" not in names


def test_env_file_type_is_env() -> None:
    results = extract_env_keys(ENV_SOURCE, ".env", REPO)
    assert all(r.file_type == "env" for r in results)


# ---------------------------------------------------------------------------
# Dispatch by file extension
# ---------------------------------------------------------------------------

def test_dispatch_picks_python_for_py_extension() -> None:
    results = extract_config_keys_from_source("MAX_RETRIES = 3\n", "pkg/config.py", REPO)
    assert any(r.file_type == "python" for r in results)


def test_dispatch_picks_json_for_json_extension() -> None:
    results = extract_config_keys_from_source('{"timeout": 30}', "config.json", REPO)
    assert any(r.file_type == "json" for r in results)


def test_dispatch_picks_yaml_for_yml_extension() -> None:
    results = extract_config_keys_from_source("key: value\n", "config.yml", REPO)
    assert any(r.file_type == "yaml" for r in results)


def test_dispatch_picks_toml_for_toml_extension() -> None:
    results = extract_config_keys_from_source("[project]\nname = 'x'\n", "pyproject.toml", REPO)
    assert any(r.file_type == "toml" for r in results)


def test_dispatch_returns_empty_for_unknown_extension() -> None:
    results = extract_config_keys_from_source("anything", "binary.so", REPO)
    assert results == []


# ---------------------------------------------------------------------------
# Containment link
# ---------------------------------------------------------------------------

def test_config_containment_link_is_file_to_config() -> None:
    key = ConfigKeyEntity(
        id=make_config_id(REPO, "src/urllib3/util/ssl_.py", "ALPN_PROTOCOLS"),
        repo=REPO,
        file_path="src/urllib3/util/ssl_.py",
        name="ALPN_PROTOCOLS",
        current_value="('http/1.1',)",
        file_type="python",
        line_number=12,
    )
    link = make_config_containment_link(REPO, key)
    assert link.rel_type == "CONTAINS"
    assert link.source_id == f"file:{REPO}:src/urllib3/util/ssl_.py"
    assert link.target_id == key.id
    assert link.confidence == 1.0


# ---------------------------------------------------------------------------
# Value change extraction from diffs
# ---------------------------------------------------------------------------

DIFF_RAISES_RETRIES = """\
--- a/src/urllib3/util/retry.py
+++ b/src/urllib3/util/retry.py
@@ -10,7 +10,7 @@ from __future__ import annotations
 
 
-DEFAULT_RETRIES = 3
+DEFAULT_RETRIES = 5
"""

DIFF_NO_CHANGE = """\
--- a/src/urllib3/util/retry.py
+++ b/src/urllib3/util/retry.py
@@ -1,5 +1,6 @@
+import logging
 from __future__ import annotations
"""


def test_value_change_detected_from_diff() -> None:
    change = extract_value_changes_from_diff(
        diff=DIFF_RAISES_RETRIES,
        key_name="DEFAULT_RETRIES",
        file_path="src/urllib3/util/retry.py",
        repo=REPO,
        commit_sha="abc123",
        authored_at="2024-05-01T10:00:00Z",
        author_name="Dev",
    )
    assert change is not None
    assert change.old_value == "3"
    assert change.new_value == "5"
    assert change.commit_sha == "abc123"
    assert change.authored_at == "2024-05-01T10:00:00Z"
    assert "DEFAULT_RETRIES" in change.diff_snippet


def test_no_change_returns_none() -> None:
    change = extract_value_changes_from_diff(
        diff=DIFF_NO_CHANGE,
        key_name="DEFAULT_RETRIES",
        file_path="src/urllib3/util/retry.py",
        repo=REPO,
        commit_sha="def456",
    )
    assert change is None


def test_value_change_id_is_stable() -> None:
    change1 = extract_value_changes_from_diff(
        diff=DIFF_RAISES_RETRIES,
        key_name="DEFAULT_RETRIES",
        file_path="src/urllib3/util/retry.py",
        repo=REPO,
        commit_sha="abc123",
    )
    change2 = extract_value_changes_from_diff(
        diff=DIFF_RAISES_RETRIES,
        key_name="DEFAULT_RETRIES",
        file_path="src/urllib3/util/retry.py",
        repo=REPO,
        commit_sha="abc123",
    )
    assert change1 is not None and change2 is not None
    assert change1.id == change2.id


def test_build_value_history_ordered_by_authored_at() -> None:
    commit_files = [
        {
            "sha": "c001",
            "authored_at": "2024-01-01T00:00:00Z",
            "author_name": "Alice",
            "diff": "-DEFAULT_RETRIES = 3\n+DEFAULT_RETRIES = 5\n",
        },
        {
            "sha": "c002",
            "authored_at": "2024-06-15T00:00:00Z",
            "author_name": "Bob",
            "diff": "-DEFAULT_RETRIES = 5\n+DEFAULT_RETRIES = 10\n",
        },
        {
            "sha": "c003",
            "authored_at": "2024-08-01T00:00:00Z",
            "author_name": "Carol",
            "diff": "-some_other = 1\n+some_other = 2\n",  # irrelevant diff
        },
    ]
    history = build_config_value_history(REPO, "DEFAULT_RETRIES", "util/retry.py", commit_files)
    assert len(history) == 2
    assert history[0].new_value == "5"
    assert history[0].commit_sha == "c001"
    assert history[1].new_value == "10"
    assert history[1].commit_sha == "c002"


# ---------------------------------------------------------------------------
# SQLite persistence for config keys and value changes
# ---------------------------------------------------------------------------

def test_sqlite_stores_and_queries_config_keys(tmp_path: Path) -> None:
    db_path = tmp_path / "test_config.sqlite3"
    key = ConfigKeyEntity(
        id=make_config_id(REPO, "src/urllib3/util/ssl_.py", "ALPN_PROTOCOLS"),
        repo=REPO,
        file_path="src/urllib3/util/ssl_.py",
        name="ALPN_PROTOCOLS",
        current_value="('http/1.1',)",
        file_type="python",
        line_number=15,
    )
    with SqliteCache(db_path) as cache:
        assert cache.put_config_key(key.as_dict()) is True
        # Idempotent
        assert cache.put_config_key(key.as_dict()) is True

        rows = cache.config_keys_for(REPO)
        assert len(rows) == 1
        assert rows[0]["name"] == "ALPN_PROTOCOLS"

        rows_by_file = cache.config_keys_for(REPO, "src/urllib3/util/ssl_.py")
        assert len(rows_by_file) == 1

        empty = cache.config_keys_for(REPO, "other/file.py")
        assert empty == []


def test_sqlite_stores_and_queries_value_changes(tmp_path: Path) -> None:
    db_path = tmp_path / "test_changes.sqlite3"
    config_id = make_config_id(REPO, "util/retry.py", "DEFAULT_RETRIES")
    change = ConfigValueChange(
        id=f"valchange:{config_id}:abc123",
        config_id=config_id,
        repo=REPO,
        file_path="util/retry.py",
        name="DEFAULT_RETRIES",
        commit_sha="abc123",
        old_value="3",
        new_value="5",
        authored_at="2024-05-01T10:00:00Z",
        author_name="Alice",
        diff_snippet="-DEFAULT_RETRIES = 3\n+DEFAULT_RETRIES = 5",
    )
    with SqliteCache(db_path) as cache:
        assert cache.put_config_value_change(change.as_dict()) is True
        # Idempotent
        assert cache.put_config_value_change(change.as_dict()) is True

        history = cache.value_history_for(config_id)
        assert len(history) == 1
        assert history[0]["old_value"] == "3"
        assert history[0]["new_value"] == "5"
        assert history[0]["commit_sha"] == "abc123"
