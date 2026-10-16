"""The Cypher in `queries.py` must stay inside what the deployed database accepts.

Neo4j's `NULLS LAST` clause is not accepted by every server build (the live AuraDB
instance rejects it with `Invalid input 'NULLS'`). The fake driver used by the seam
tests never parses a query, so an unsupported clause passes every offline test and
only fails on the first real call. This pins the query text against the construct
that broke the live answer path.
"""

from __future__ import annotations

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
