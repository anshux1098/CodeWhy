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
ORDER BY d.recorded_at DESC NULLS LAST
"""

GET_SUBGRAPH_FOR_ENTITY: Final[str] = """
MATCH (e:CodeEntity {id: $entity_id})
OPTIONAL MATCH (d:Decision)-[:GOVERNS]->(e)
OPTIONAL MATCH (d)-[:SUPPORTED_BY]->(ev:Evidence)
OPTIONAL MATCH (d)-[s:SUPERSEDES]->(older:Decision)
OPTIONAL MATCH (p:Person)-[:AUTHORED]->(d)
RETURN e, collect(DISTINCT d) AS decisions,
       collect(DISTINCT ev) AS evidence,
       collect(DISTINCT older) AS older_decisions,
       collect(DISTINCT p) AS authors
LIMIT $node_cap
"""
