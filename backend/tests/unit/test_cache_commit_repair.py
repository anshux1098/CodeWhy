from __future__ import annotations

import tempfile
from pathlib import Path

from app.stores.sqlite_cache import SqliteCache


def test_put_commit_repairs_an_empty_body_on_rerun() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "cache.sqlite"
        with SqliteCache(db) as cache:
            assert cache.put_commit("urllib3/urllib3", {"sha": "abc", "subject": "Fix thing", "message": ""}) is True
            assert cache.put_commit("urllib3/urllib3", {"sha": "abc", "subject": "Fix thing", "message": "body text"}) is False
            row = cache._connection.execute("SELECT message FROM commits WHERE sha = ?", ("abc",)).fetchone()
            assert row[0] == "body text"


def test_put_commit_leaves_a_nonempty_body_alone() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "cache.sqlite"
        with SqliteCache(db) as cache:
            assert cache.put_commit("urllib3/urllib3", {"sha": "abc", "subject": "Fix thing", "message": "first"}) is True
            assert cache.put_commit("urllib3/urllib3", {"sha": "abc", "subject": "Fix thing", "message": "second"}) is False
            row = cache._connection.execute("SELECT message FROM commits WHERE sha = ?", ("abc",)).fetchone()
            assert row[0] == "first"
