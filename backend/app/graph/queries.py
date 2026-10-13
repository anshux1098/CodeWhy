from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Node MERGE Statements (Parameterized)
# ---------------------------------------------------------------------------

MERGE_REPOSITORY: Final[str] = """
MERGE (r:Repository {id: $id})
ON CREATE SET r.owner = $owner, r.name = $name, r.default_branch = $default_branch, r.created_at = $created_at
ON MATCH SET r.default_branch = $default_branch
"""

MERGE_CODE_ENTITY: Final[str] = """
MERGE (e:CodeEntity {id: $id})
ON CREATE SET e.repo = $repo, e.name = $name, e.path = $path, e.entity_type = $entity_type, e.created_at = $created_at
ON MATCH SET e.path = $path, e.entity_type = $entity_type
"""

MERGE_DECISION: Final[str] = """
MERGE (d:Decision {id: $id})
ON CREATE SET d.repo = $repo, d.summary = $summary, d.decision_type = $decision_type,
              d.rationale = $rationale, d.state = $state, d.recorded_at = $recorded_at,
              d.effective_at = $effective_at, d.ended_at = $ended_at, d.evaluated_at = $evaluated_at,
              d.quote_verified = $quote_verified, d.embedding = $embedding
ON MATCH SET d.summary = $summary, d.rationale = $rationale, d.state = $state,
             d.evaluated_at = $evaluated_at, d.quote_verified = $quote_verified,
             d.embedding = $embedding
"""

MERGE_PULL_REQUEST: Final[str] = """
MERGE (p:PullRequest {id: $id})
ON CREATE SET p.repo = $repo, p.number = $number, p.title = $title, p.url = $url,
              p.merged_at = $merged_at, p.author = $author, p.created_at = $created_at
ON MATCH SET p.title = $title, p.merged_at = $merged_at
"""

MERGE_COMMIT: Final[str] = """
MERGE (c:Commit {id: $id})
ON CREATE SET c.repo = $repo, c.sha = $sha, c.message = $message, c.author = $author,
              c.authored_at = $authored_at, c.created_at = $created_at
ON MATCH SET c.message = $message
"""

MERGE_ISSUE: Final[str] = """
MERGE (i:Issue {id: $id})
ON CREATE SET i.repo = $repo, i.number = $number, i.title = $title, i.url = $url,
              i.author = $author, i.created_at = $created_at
ON MATCH SET i.title = $title
"""

MERGE_DISCUSSION: Final[str] = """
MERGE (disc:Discussion {id: $id})
ON CREATE SET disc.repo = $repo, disc.author = $author, disc.body = $body, disc.created_at = $created_at
ON MATCH SET disc.body = $body
"""

MERGE_PERSON: Final[str] = """
MERGE (person:Person {login: $login})
ON CREATE SET person.active = $active, person.last_seen_at = $last_seen_at
ON MATCH SET person.active = $active, person.last_seen_at = $last_seen_at
"""

MERGE_EVIDENCE: Final[str] = """
MERGE (ev:Evidence {id: $id})
ON CREATE SET ev.decision_id = $decision_id, ev.source_id = $source_id,
              ev.source_type = $source_type, ev.source_url = $source_url,
              ev.quote = $quote, ev.author = $author, ev.timestamp = $timestamp,
              ev.classification = $classification, ev.claim = $claim,
              ev.quote_verified = $quote_verified, ev.created_at = $created_at
ON MATCH SET ev.quote = $quote, ev.quote_verified = $quote_verified
"""

MERGE_DOCUMENT: Final[str] = """
MERGE (doc:Document {id: $id})
ON CREATE SET doc.repo = $repo, doc.path = $path, doc.title = $title,
              doc.status = $status, doc.created_at = $created_at
ON MATCH SET doc.status = $status
"""

MERGE_INCIDENT: Final[str] = """
MERGE (inc:Incident {id: $id})
ON CREATE SET inc.repo = $repo, inc.title = $title, inc.source_id = $source_id,
              inc.severity = $severity, inc.created_at = $created_at
ON MATCH SET inc.title = $title
"""

# ---------------------------------------------------------------------------
# Relationship MERGE Statements
# ---------------------------------------------------------------------------

MERGE_REL_CONTAINS: Final[str] = """
MATCH (parent {id: $parent_id}), (child {id: $child_id})
MERGE (parent)-[r:CONTAINS]->(child)
"""

MERGE_REL_MODIFIED_IN: Final[str] = """
MATCH (e:CodeEntity {id: $entity_id}), (c:Commit {id: $commit_id})
MERGE (e)-[r:MODIFIED_IN]->(c)
"""

MERGE_REL_PART_OF: Final[str] = """
MATCH (c:Commit {id: $commit_id}), (p:PullRequest {id: $pr_id})
MERGE (c)-[r:PART_OF]->(p)
"""

MERGE_REL_REFERENCES: Final[str] = """
MATCH (source {id: $source_id}), (target {id: $target_id})
MERGE (source)-[r:REFERENCES]->(target)
"""

MERGE_REL_REVERTS: Final[str] = """
MATCH (reverting:Commit {id: $reverting_id}), (reverted:Commit {id: $reverted_id})
MERGE (reverting)-[r:REVERTS]->(reverted)
"""

MERGE_REL_HAS_DISCUSSION: Final[str] = """
MATCH (source {id: $source_id}), (disc:Discussion {id: $discussion_id})
MERGE (source)-[r:HAS_DISCUSSION]->(disc)
"""

MERGE_REL_AUTHORED: Final[str] = """
MATCH (person:Person {login: $login}), (target {id: $target_id})
MERGE (person)-[r:AUTHORED]->(target)
"""

MERGE_REL_REVIEWED: Final[str] = """
MATCH (person:Person {login: $login}), (pr:PullRequest {id: $pr_id})
MERGE (person)-[r:REVIEWED]->(pr)
"""

MERGE_REL_DECIDED_IN: Final[str] = """
MATCH (d:Decision {id: $decision_id}), (source {id: $source_id})
MERGE (d)-[r:DECIDED_IN]->(source)
"""

MERGE_REL_GOVERNS: Final[str] = """
MATCH (d:Decision {id: $decision_id}), (e:CodeEntity {id: $entity_id})
MERGE (d)-[r:GOVERNS]->(e)
"""

MERGE_REL_SUPPORTED_BY: Final[str] = """
MATCH (d:Decision {id: $decision_id}), (ev:Evidence {id: $evidence_id})
MERGE (d)-[r:SUPPORTED_BY]->(ev)
"""

MERGE_REL_OPPOSES: Final[str] = """
MATCH (ev:Evidence {id: $evidence_id}), (d:Decision {id: $decision_id})
MERGE (ev)-[r:OPPOSES]->(d)
"""

MERGE_REL_MOTIVATED_BY: Final[str] = """
MATCH (d:Decision {id: $decision_id}), (target {id: $target_id})
MERGE (d)-[r:MOTIVATED_BY]->(target)
"""

MERGE_REL_SUPERSEDES: Final[str] = """
MATCH (newer:Decision {id: $newer_id}), (older:Decision {id: $older_id})
MERGE (newer)-[r:SUPERSEDES]->(older)
ON CREATE SET r.rule = $rule, r.confidence = $confidence, r.review_state = $review_state
ON MATCH SET r.rule = $rule, r.confidence = $confidence, r.review_state = $review_state
"""

MERGE_REL_REAFFIRMS: Final[str] = """
MATCH (newer:Decision {id: $newer_id}), (older:Decision {id: $older_id})
MERGE (newer)-[r:REAFFIRMS]->(older)
"""

MERGE_REL_CONFLICTS_WITH: Final[str] = """
MATCH (d1:Decision {id: $d1_id}), (d2:Decision {id: $d2_id})
MERGE (d1)-[r:CONFLICTS_WITH]->(d2)
"""

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

GET_SUPERSEDED_CHAIN: Final[str] = """
MATCH path = (d:Decision {id: $decision_id})-[:SUPERSEDES*1..6]->(older:Decision)
RETURN nodes(path) AS chain_nodes, relationships(path) AS chain_rels
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
