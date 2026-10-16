from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Node MERGE Statements (Parameterized)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Relationship MERGE Statements
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Retrieval & Traversal Queries
# ---------------------------------------------------------------------------

GET_DECISIONS_GOVERNING_ENTITY: Final[str] = """
MATCH (d:Decision)-[:GOVERNS]->(e:CodeEntity {id: $entity_id})
OPTIONAL MATCH (d)-[:SUPPORTED_BY]->(ev:Evidence)
OPTIONAL MATCH (d)-[:DECIDED_IN]->(src)
RETURN d, collect(DISTINCT ev) AS evidence, collect(DISTINCT src) AS sources
ORDER BY coalesce(d.recorded_at, '') DESC
"""

GET_SUBGRAPH_FOR_ENTITY: Final[str] = """
MATCH (e:CodeEntity {id: $entity_id})
OPTIONAL MATCH (e)-[*1..2]-(m)
WITH e, collect(DISTINCT m) AS neighbours
UNWIND ([e] + neighbours) AS node
WITH DISTINCT node
LIMIT $node_cap
RETURN node, labels(node) AS labels
"""
