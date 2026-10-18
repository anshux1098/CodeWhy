"""Who proposed a change must be visible, from the data already in the cache.

The audit found no authorship at all: zero Person nodes, no author on a pull
request or decision, and a null citation author, even though the raw pull request
payload carries the author for every verified decision. The fix reads the author
from `raw_objects` at rebuild. It does not invent a Person node or AUTHORED edge;
that is a different feature and is out of scope.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings
from app.services.data_source import GraphDataSource
from app.stores.sqlite_cache import SqliteCache
from scripts.rebuild_graph import build_from_cache

REPO = "acme/netclient"


def _seed(cache_path: Path, *, pr_author: object, evidence_author: str = "") -> None:
    with SqliteCache(cache_path) as cache:
        payload = {
            "number": 7, "title": "Cap retries", "body": "because",
            "files": ["pkg/config.py"], "mergedAt": "2024-08-22T17:36:35Z",
        }
        if pr_author is not None:
            payload["author"] = pr_author
        cache.put_raw("pr", REPO, "7", payload)
        cache.put_decision({
            "id": "d1", "repo": REPO, "source_id": "pr:acme/netclient#7",
            "summary": "s", "rationale": "r", "state": "ACTIVE",
            "decision_type": "Other", "affected_entities": json.dumps(["pkg/config.py"]),
            "quote_verified": True, "created_at": "", "evaluated_at": "",
            "alternatives_considered": [], "constraints": [],
            "explicit_reversal_language": False, "unknown_fields": [],
            "extraction_version": "v1", "content_hash": "abc",
        })
        cache.put_evidence({
            "id": "ev1", "decision_id": "d1", "source_id": "pr:acme/netclient#7",
            "source_type": "pull_request", "source_url": "https://github.com/acme/netclient/pull/7",
            "quote": "because", "author": evidence_author, "timestamp": "",
            "classification": "SOURCE", "claim": "cap", "quote_verified": True,
            "created_at": "",
        })


def _store(tmp_path: Path, **seed_kwargs: object):
    cache_path = tmp_path / "c.sqlite3"
    _seed(cache_path, **seed_kwargs)
    return build_from_cache(cache_path, REPO).store


def test_the_pull_request_node_carries_its_author(tmp_path: Path) -> None:
    node = _store(tmp_path, pr_author="sethmlarson").get_node("pr:acme/netclient#7")
    assert node["author"] == "sethmlarson"


def test_the_decision_node_carries_its_author(tmp_path: Path) -> None:
    node = _store(tmp_path, pr_author="sethmlarson").get_node("d1")
    assert node["author"] == "sethmlarson"


def test_a_missing_evidence_author_falls_back_to_the_pull_request_author(tmp_path: Path) -> None:
    store = _store(tmp_path, pr_author="sethmlarson")
    assert store.get_node("ev1")["author"] == "sethmlarson"


def test_an_evidence_author_that_is_present_is_kept(tmp_path: Path) -> None:
    store = _store(tmp_path, pr_author="sethmlarson", evidence_author="real-reviewer")
    assert store.get_node("ev1")["author"] == "real-reviewer"


def test_the_citation_carries_the_author(tmp_path: Path) -> None:
    store = _store(tmp_path, pr_author="sethmlarson")
    cfg = Settings(_env_file=None, data_source="graph", allow_mock_providers=True)
    detail = GraphDataSource(cfg, store=store).get_decision("d1")
    assert detail.citations[0].author == "sethmlarson"


def test_a_plain_login_string_is_read_as_the_author(tmp_path: Path) -> None:
    store = _store(tmp_path, pr_author="pquentin")
    assert store.get_node("d1")["author"] == "pquentin"


def test_a_missing_author_stays_empty_rather_than_being_invented(tmp_path: Path) -> None:
    store = _store(tmp_path, pr_author=None)
    assert store.get_node("d1")["author"] in (None, "")
    cfg = Settings(_env_file=None, data_source="graph", allow_mock_providers=True)
    assert GraphDataSource(cfg, store=store).get_decision("d1").citations[0].author in (None, "")


def test_no_person_node_or_authored_edge_is_created(tmp_path: Path) -> None:
    store = _store(tmp_path, pr_author="sethmlarson")
    assert "Person" not in store.label_counts()
    assert "AUTHORED" not in store.relationship_type_counts()
    assert "REVIEWED" not in store.relationship_type_counts()

