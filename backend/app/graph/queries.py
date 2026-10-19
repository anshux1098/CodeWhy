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

# Decisions whose own text mentions the question's words, ranked by how often the
# evidence quotes mention them. Used when a question names no entity.
SEARCH_DECISIONS_BY_TEXT: Final[str] = """
CALL db.index.fulltext.queryNodes('evidence_quote_fulltext', $q)
YIELD node AS ev, score
MATCH (d:Decision)-[:SUPPORTED_BY]->(ev)
WHERE d.repo = $repo
RETURN d AS decision, score
"""

SEARCH_DECISIONS_BY_SUMMARY: Final[str] = """
MATCH (d:Decision {repo: $repo})
WHERE any(t IN $tokens WHERE
  toLower(coalesce(d.summary, '')) CONTAINS toLower(t) OR
  toLower(coalesce(d.rationale, '')) CONTAINS toLower(t))
RETURN d AS decision
"""

# The entities a decision governs, used to turn matched decisions into an entity.
GET_ENTITIES_FOR_DECISION: Final[str] = """
MATCH (d:Decision {id: $decision_id})-[:GOVERNS]->(e:CodeEntity)
RETURN e
"""

# A page of a repository's decisions, newest first. Undated decisions sort last
# because the live database rejects a NULLS ordering clause, so the presence of a
# date is used as the leading sort term. `d.id` breaks ties so paging is stable.
LIST_DECISIONS_FOR_REPOSITORY: Final[str] = """
MATCH (d:Decision {repo: $repo})
WHERE $state IS NULL OR d.state = $state
OPTIONAL MATCH (d)-[:GOVERNS]->(e:CodeEntity)
WITH d, [x IN collect(DISTINCT e.id) WHERE x IS NOT NULL] AS entities
WHERE $entity_id IS NULL OR $entity_id IN entities
RETURN d, entities
ORDER BY (d.effective_at IS NULL), d.effective_at DESC, d.id
SKIP $offset LIMIT $limit
"""

# How many decisions match the same filters, before paging. Counted separately so
# `total` is the real number rather than the size of the returned page.
COUNT_DECISIONS_FOR_REPOSITORY: Final[str] = """
MATCH (d:Decision {repo: $repo})
WHERE $state IS NULL OR d.state = $state
OPTIONAL MATCH (d)-[:GOVERNS]->(e:CodeEntity)
WITH d, [x IN collect(DISTINCT e.id) WHERE x IS NOT NULL] AS entities
WHERE $entity_id IS NULL OR $entity_id IN entities
RETURN count(d) AS total
"""

# A repository's decision graph. Seeded from the Decision nodes so the result is the
# decisions and what they connect to, rather than an arbitrary page of nodes whose
# edges are almost all excluded by the sample.
GET_SUBGRAPH_FOR_REPOSITORY: Final[str] = """
MATCH (d:Decision {repo: $repo})
OPTIONAL MATCH (d)-[:GOVERNS]->(e:CodeEntity)
OPTIONAL MATCH (d)-[:DECIDED_IN]->(src)
OPTIONAL MATCH (d)-[:SUPPORTED_BY]->(ev:Evidence)
WITH collect(DISTINCT d) AS decisions, collect(DISTINCT e) AS entities,
     collect(DISTINCT src) AS sources, collect(DISTINCT ev) AS evidence
UNWIND (decisions + entities + sources + evidence) AS node
WITH DISTINCT node
LIMIT $node_cap
RETURN node, labels(node) AS labels
"""
