from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Uniqueness Constraints
# ---------------------------------------------------------------------------

NODE_CONSTRAINTS: Final[tuple[str, ...]] = (
    "CREATE CONSTRAINT repo_id_unique IF NOT EXISTS FOR (r:Repository) REQUIRE r.id IS UNIQUE;",
    "CREATE CONSTRAINT code_entity_id_unique IF NOT EXISTS FOR (e:CodeEntity) REQUIRE e.id IS UNIQUE;",
    "CREATE CONSTRAINT decision_id_unique IF NOT EXISTS FOR (d:Decision) REQUIRE d.id IS UNIQUE;",
    "CREATE CONSTRAINT pr_id_unique IF NOT EXISTS FOR (p:PullRequest) REQUIRE p.id IS UNIQUE;",
    "CREATE CONSTRAINT commit_id_unique IF NOT EXISTS FOR (c:Commit) REQUIRE c.id IS UNIQUE;",
    "CREATE CONSTRAINT issue_id_unique IF NOT EXISTS FOR (i:Issue) REQUIRE i.id IS UNIQUE;",
    "CREATE CONSTRAINT discussion_id_unique IF NOT EXISTS FOR (disc:Discussion) REQUIRE disc.id IS UNIQUE;",
    "CREATE CONSTRAINT person_login_unique IF NOT EXISTS FOR (person:Person) REQUIRE person.login IS UNIQUE;",
    "CREATE CONSTRAINT evidence_id_unique IF NOT EXISTS FOR (ev:Evidence) REQUIRE ev.id IS UNIQUE;",
    "CREATE CONSTRAINT document_id_unique IF NOT EXISTS FOR (doc:Document) REQUIRE doc.id IS UNIQUE;",
    "CREATE CONSTRAINT incident_id_unique IF NOT EXISTS FOR (inc:Incident) REQUIRE inc.id IS UNIQUE;",
)

# ---------------------------------------------------------------------------
# Property & Performance Indexes
# ---------------------------------------------------------------------------

NODE_INDEXES: Final[tuple[str, ...]] = (
    "CREATE INDEX code_entity_lookup IF NOT EXISTS FOR (e:CodeEntity) ON (e.repo, e.name);",
    "CREATE INDEX code_entity_path IF NOT EXISTS FOR (e:CodeEntity) ON (e.repo, e.path);",
    "CREATE INDEX decision_repo_state IF NOT EXISTS FOR (d:Decision) ON (d.repo, d.state);",
    "CREATE INDEX commit_sha_lookup IF NOT EXISTS FOR (c:Commit) ON (c.sha);",
    "CREATE INDEX pr_number_lookup IF NOT EXISTS FOR (p:PullRequest) ON (p.repo, p.number);",
)

# ---------------------------------------------------------------------------
# Vector Index (384 dimensions, cosine) & Full-text Index
# ---------------------------------------------------------------------------

VECTOR_INDEX_QUERY: Final[str] = (
    "CREATE VECTOR INDEX decision_vector_index IF NOT EXISTS "
    "FOR (d:Decision) ON (d.embedding) "
    "OPTIONS { indexConfig: { `vector.dimensions`: 384, `vector.similarity_function`: 'cosine' } };"
)

FULLTEXT_INDEX_QUERY: Final[str] = (
    "CREATE FULLTEXT INDEX evidence_quote_fulltext IF NOT EXISTS "
    "FOR (ev:Evidence) ON EACH [ev.quote];"
)
