from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.extraction import filter_affected_entities
from app.services.linking import extract_import_links, extract_pr_links
from app.stores.sqlite_cache import SqliteCache


def test_filter_affected_entities_is_repo_agnostic():
    files = [
        "alembic/operations/batch.py",
        "src/flask/app.py",
        "pkg/server/handler.go",
        "frontend/src/App.tsx",
        "tests/test_batch.py",
        "docs/index.md",
        "setup.py",
        "vendor/lib/foo.py",
        "node_modules/pkg/index.js",
        "src/flask/typing.pyi",
    ]
    assert filter_affected_entities(files) == [
        "alembic/operations/batch.py",
        "frontend/src/App.tsx",
        "pkg/server/handler.go",
        "src/flask/app.py",
    ]


def test_extract_pr_links_reverts_tickets_and_incidents():
    links = extract_pr_links(
        pr_number=210,
        title="Hotfix SEV-1: Revert #205 for INC-901",
        body="Fixes #199 and resolves ENG-1420.",
        repo="acme/api",
    )
    rel_types = {(l.rel_type, l.derivation_method, l.target_id) for l in links}
    assert ("REVERTS", "pr_revert_text", "pr:acme/api#205") in rel_types
    assert ("REFERENCES", "closing_keyword", "issue:acme/api#199") in rel_types
    assert ("REFERENCES", "external_ticket", "issue:acme/api#ENG-1420") in rel_types
    assert ("TRIGGERED_BY", "incident_marker", "incident:acme/api:INC-901") in rel_types


def test_extract_import_links_python_ast(tmp_path: Path):
    pkg = tmp_path / "src" / "mylib"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "retry.py").write_text("DEFAULT_RETRIES = 3\n", encoding="utf-8")
    (pkg / "client.py").write_text("from mylib import retry\nimport json\n", encoding="utf-8")

    links = extract_import_links(
        "acme/mylib",
        ["src/mylib/__init__.py", "src/mylib/retry.py", "src/mylib/client.py"],
        tmp_path,
    )
    assert len(links) == 1
    assert links[0].rel_type == "IMPORTS"
    assert links[0].source_id == "file:acme/mylib:src/mylib/client.py"
    assert links[0].target_id == "file:acme/mylib:src/mylib/retry.py"


def test_put_config_value_changes_batch():
    with TemporaryDirectory() as tmpdir:
        with SqliteCache(Path(tmpdir) / "c.sqlite3") as cache:
            count = cache.put_config_value_changes([
                {
                    "id": "vc1",
                    "config_id": "config:acme/lib:src/a.py#TIMEOUT",
                    "repo": "acme/lib",
                    "file_path": "src/a.py",
                    "name": "TIMEOUT",
                    "commit_sha": "abc123",
                    "old_value": "5",
                    "new_value": "10",
                }
            ])
            assert count == 1
            hist = cache.value_history_for("config:acme/lib:src/a.py#TIMEOUT")
            assert len(hist) == 1
            assert hist[0]["old_value"] == "5"
            assert hist[0]["new_value"] == "10"
