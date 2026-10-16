"""The Cypher in `queries.py` must stay inside what the deployed database accepts.

Neo4j's `NULLS LAST` clause is not accepted by every server build (the live AuraDB
instance rejects it with `Invalid input 'NULLS'`). The fake driver used by the seam
tests never parses a query, so an unsupported clause passes every offline test and
only fails on the first real call. This pins the query text against the construct
that broke the live answer path.
"""

from __future__ import annotations

import re

import pytest

from app.graph import queries


def _query_constants() -> dict[str, str]:
    return {
        name: value
        for name, value in vars(queries).items()
        if name.isupper() and isinstance(value, str) and "MATCH" in value
    }


def test_there_is_at_least_one_query_to_check() -> None:
    assert _query_constants(), "queries.py defines no query constants"


def test_no_query_uses_a_nulls_ordering_clause() -> None:
    offenders = {name for name, text in _query_constants().items() if "NULLS" in text.upper()}
    assert not offenders, (
        f"these queries use a NULLS ordering clause the live database rejects: {offenders}"
    )


@pytest.mark.live
def test_live_database_explains_every_query() -> None:
    """Every query must be accepted by the deployed server, not just by a fake driver.

    Set RUN_LIVE=1 to run it. EXPLAIN parses and plans the statement without touching
    any data, so a syntax the offline tests cannot see fails here instead of on the
    first real request.
    """
    import os

    if os.environ.get("RUN_LIVE") != "1":
        pytest.skip("set RUN_LIVE=1 to EXPLAIN the queries against the live database")

    from app.config import settings as global_settings
    from app.stores.graph_store import Neo4jGraphStore, get_graph_store

    global_settings.require_neo4j()
    store = get_graph_store(global_settings)
    assert isinstance(store, Neo4jGraphStore), "EXPLAIN needs a real Neo4j store"
    try:
        for name, text in _query_constants().items():
            params = {
                param: (10 if param in {"node_cap", "cap", "limit"} else "x")
                for param in re.findall(r"\$(\w+)", text)
            }
            with store.driver.session(database=store.database) as session:
                session.run("EXPLAIN " + text, **params).consume()
    finally:
        store.close()
