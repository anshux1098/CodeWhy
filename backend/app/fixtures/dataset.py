from __future__ import annotations

from app.schemas.decisions import Citation, Decision, SourceRef, WhoToAsk
from app.schemas.entities import Entity
from app.schemas.repository import RepositoryCounts, RepositoryResponse

REPOSITORY_ID = "acme-netclient"
REPOSITORY_NAME = "netclient"
REPOSITORY_URL = "https://github.invalid/acme/netclient"
REPOSITORY = RepositoryResponse(
    id=REPOSITORY_ID,
    name=REPOSITORY_NAME,
    url=REPOSITORY_URL,
    counts=RepositoryCounts(decisions=5, entities=6, pull_requests=5, commits=9),
    fixture=True,
)

ENTITIES: tuple[Entity, ...] = (
    Entity(id="module:netclient", type="Module", label="netclient", path="netclient/", decision_count=1),
    Entity(id="file:netclient/config.py", type="File", label="config.py", path="netclient/config.py", decision_count=3),
    Entity(id="file:netclient/retry.py", type="File", label="retry.py", path="netclient/retry.py", decision_count=1),
    Entity(id="key:MAX_RETRIES", type="ConfigKey", label="MAX_RETRIES", path="netclient/config.py", decision_count=3),
    Entity(id="key:_PAD_BYTES", type="ConfigKey", label="_PAD_BYTES", path="netclient/config.py", decision_count=0),
    Entity(id="key:RETRY_BACKOFF_MS", type="ConfigKey", label="RETRY_BACKOFF_MS", path="netclient/config.py", decision_count=1),
)
ENTITY_BY_ID = {entity.id: entity for entity in ENTITIES}


def _pr(number: int) -> SourceRef:
    return SourceRef(
        type="PullRequest",
        number=number,
        url=f"https://github.invalid/acme/netclient/pull/{number}",
    )


DECISIONS: tuple[Decision, ...] = (
    Decision(
        id="dec_41",
        summary="Cap MAX_RETRIES at 3 to match the mobile client retry budget",
        rationale="The mobile client gives up after three retries, so a longer library loop only wastes battery.",
        state="ACTIVE",
        recorded_at="2024-02-11T09:14:00Z",
        effective_at="2024-02-11T09:20:00Z",
        ended_at="2024-06-04T10:02:00Z",
        source=_pr(41),
        superseded_by=["dec_77"],
    ),
    Decision(
        id="dec_77",
        summary="Raise MAX_RETRIES to 6 to cut tail latency",
        rationale="Six retries removed most of the p95 on long-tail calls.",
        state="SUPERSEDED",
        recorded_at="2024-06-04T09:40:00Z",
        effective_at="2024-06-04T10:02:00Z",
        ended_at="2024-08-19T14:30:00Z",
        source=_pr(77),
        supersedes=["dec_41"],
        superseded_by=["dec_90"],
        rule="2_config_key_changed",
    ),
    Decision(
        id="dec_90",
        summary="Revert MAX_RETRIES to 3 after the latency fix regressed mobile battery",
        rationale="The battery regression outweighed the latency gain, so the original cap came back.",
        state="ACTIVE",
        recorded_at="2024-08-19T14:12:00Z",
        effective_at="2024-08-19T14:30:00Z",
        source=_pr(90),
        supersedes=["dec_77"],
        rule="1_revert_commit",
    ),
    Decision(
        id="dec_55",
        summary="Make the retry backoff delay configurable as RETRY_BACKOFF_MS",
        rationale="Operators wanted to tune the delay between attempts without waiting for a release.",
        state="REJECTED",
        recorded_at="2024-04-02T11:05:00Z",
        source=_pr(55),
    ),
    Decision(
        id="dec_104",
        summary="Move the retry backoff helper from config.py into netclient/retry.py",
        rationale=None,
        state="ACTIVE",
        recorded_at="2025-01-15T16:45:00Z",
        effective_at="2025-01-15T17:00:00Z",
        source=_pr(104),
    ),
)
DECISION_BY_ID = {decision.id: decision for decision in DECISIONS}

CITATIONS: tuple[Citation, ...] = (
    Citation(
        id="cit_41",
        decision_id="dec_41",
        kind="SOURCE",
        quote="The mobile client gives up after three retries, so capping the library at the same number keeps behaviour identical on both sides.",
        source_url=_pr(41).url,
        source_type="PullRequest",
        author="priya",
        timestamp="2024-02-11T09:14:00Z",
    ),
    Citation(
        id="cit_77",
        decision_id="dec_77",
        kind="SOURCE",
        quote="Raising MAX_RETRIES to six removes most of the p95 on our long-tail calls without changing any other default.",
        source_url=_pr(77).url,
        source_type="PullRequest",
        author="marco",
        timestamp="2024-06-04T09:40:00Z",
    ),
    Citation(
        id="cit_90",
        decision_id="dec_90",
        kind="SOURCE",
        quote='Revert "Raise MAX_RETRIES to 6"',
        source_url=_pr(90).url,
        source_type="PullRequest",
        author="lena",
        timestamp="2024-08-19T14:12:00Z",
    ),
    Citation(
        id="cit_55",
        decision_id="dec_55",
        kind="SOURCE",
        quote="Adds RETRY_BACKOFF_MS so operators can tune the delay between attempts without waiting for a release.",
        source_url=_pr(55).url,
        source_type="PullRequest",
        author="tom",
        timestamp="2024-04-02T11:05:00Z",
    ),
)
CITATIONS_BY_DECISION: dict[str, list[Citation]] = {}
for _citation in CITATIONS:
    CITATIONS_BY_DECISION.setdefault(_citation.decision_id, []).append(_citation)

WHO_TO_ASK: tuple[WhoToAsk, ...] = (
    WhoToAsk(login="priya", reason="author", active=True),
    WhoToAsk(login="lena", reason="reviewer", active=True),
    WhoToAsk(login="marco", reason="recent_contributor", active=False),
    WhoToAsk(login="tom", reason="recent_contributor", active=True),
)

GRAPH_NODES: tuple[dict[str, object], ...] = (
    {"id": REPOSITORY_ID, "label": REPOSITORY_NAME, "type": "Repository", "props": {"url": REPOSITORY_URL}},
    {"id": "module:netclient", "label": "netclient", "type": "CodeEntity", "props": {"entity_type": "Module", "path": "netclient/"}},
    {"id": "file:netclient/config.py", "label": "config.py", "type": "CodeEntity", "props": {"entity_type": "File", "path": "netclient/config.py"}},
    {"id": "file:netclient/retry.py", "label": "retry.py", "type": "CodeEntity", "props": {"entity_type": "File", "path": "netclient/retry.py"}},
    {"id": "key:MAX_RETRIES", "label": "MAX_RETRIES", "type": "CodeEntity", "props": {"entity_type": "ConfigKey", "path": "netclient/config.py"}},
    {"id": "key:_PAD_BYTES", "label": "_PAD_BYTES", "type": "CodeEntity", "props": {"entity_type": "ConfigKey", "path": "netclient/config.py"}},
    {"id": "key:RETRY_BACKOFF_MS", "label": "RETRY_BACKOFF_MS", "type": "CodeEntity", "props": {"entity_type": "ConfigKey", "path": "netclient/config.py"}},
    {"id": "dec_41", "label": "Cap MAX_RETRIES at 3", "type": "Decision", "props": {"state": "ACTIVE"}},
    {"id": "dec_77", "label": "Raise MAX_RETRIES to 6", "type": "Decision", "props": {"state": "SUPERSEDED", "rule": "2_config_key_changed"}},
    {"id": "dec_90", "label": "Revert MAX_RETRIES to 3", "type": "Decision", "props": {"state": "ACTIVE", "rule": "1_revert_commit"}},
    {"id": "dec_55", "label": "Make the retry backoff configurable", "type": "Decision", "props": {"state": "REJECTED"}},
    {"id": "dec_104", "label": "Move the retry backoff helper", "type": "Decision", "props": {"state": "ACTIVE"}},
    {"id": "pr:41", "label": "Pull request 41", "type": "PullRequest", "props": {"number": 41}},
    {"id": "pr:55", "label": "Pull request 55", "type": "PullRequest", "props": {"number": 55, "merged": False}},
    {"id": "pr:77", "label": "Pull request 77", "type": "PullRequest", "props": {"number": 77}},
    {"id": "pr:90", "label": "Pull request 90", "type": "PullRequest", "props": {"number": 90}},
    {"id": "pr:104", "label": "Pull request 104", "type": "PullRequest", "props": {"number": 104}},
    {"id": "person:priya", "label": "priya", "type": "Person", "props": {"login": "priya"}},
    {"id": "person:marco", "label": "marco", "type": "Person", "props": {"login": "marco"}},
    {"id": "person:lena", "label": "lena", "type": "Person", "props": {"login": "lena"}},
    {"id": "person:tom", "label": "tom", "type": "Person", "props": {"login": "tom"}},
    {"id": "ev:cit_41", "label": "Verified quote from 41", "type": "Evidence", "props": {"quote_verified": True}},
    {"id": "ev:cit_77", "label": "Verified quote from 77", "type": "Evidence", "props": {"quote_verified": True}},
    {"id": "ev:cit_90", "label": "Verified revert quote from 90", "type": "Evidence", "props": {"quote_verified": True}},
    {"id": "ev:cit_55", "label": "Verified quote from 55", "type": "Evidence", "props": {"quote_verified": True}},
)

GRAPH_EDGES: tuple[dict[str, object], ...] = (
    {"source": REPOSITORY_ID, "target": "module:netclient", "type": "CONTAINS", "rule": None},
    {"source": "module:netclient", "target": "file:netclient/config.py", "type": "CONTAINS", "rule": None},
    {"source": "module:netclient", "target": "file:netclient/retry.py", "type": "CONTAINS", "rule": None},
    {"source": "file:netclient/config.py", "target": "key:MAX_RETRIES", "type": "CONTAINS", "rule": None},
    {"source": "file:netclient/config.py", "target": "key:_PAD_BYTES", "type": "CONTAINS", "rule": None},
    {"source": "file:netclient/config.py", "target": "key:RETRY_BACKOFF_MS", "type": "CONTAINS", "rule": None},
    {"source": "dec_41", "target": "key:MAX_RETRIES", "type": "GOVERNS", "rule": None},
    {"source": "dec_77", "target": "key:MAX_RETRIES", "type": "GOVERNS", "rule": None},
    {"source": "dec_90", "target": "key:MAX_RETRIES", "type": "GOVERNS", "rule": None},
    {"source": "dec_55", "target": "key:RETRY_BACKOFF_MS", "type": "GOVERNS", "rule": None},
    {"source": "dec_104", "target": "file:netclient/retry.py", "type": "GOVERNS", "rule": None},
    {"source": "dec_90", "target": "dec_77", "type": "SUPERSEDES", "rule": "1_revert_commit"},
    {"source": "dec_77", "target": "dec_41", "type": "SUPERSEDES", "rule": "2_config_key_changed"},
    {"source": "dec_41", "target": "pr:41", "type": "DECIDED_IN", "rule": None},
    {"source": "dec_77", "target": "pr:77", "type": "DECIDED_IN", "rule": None},
    {"source": "dec_90", "target": "pr:90", "type": "DECIDED_IN", "rule": None},
    {"source": "dec_55", "target": "pr:55", "type": "DECIDED_IN", "rule": None},
    {"source": "dec_104", "target": "pr:104", "type": "DECIDED_IN", "rule": None},
    {"source": "dec_41", "target": "ev:cit_41", "type": "SUPPORTED_BY", "rule": None},
    {"source": "dec_77", "target": "ev:cit_77", "type": "SUPPORTED_BY", "rule": None},
    {"source": "dec_90", "target": "ev:cit_90", "type": "SUPPORTED_BY", "rule": None},
    {"source": "dec_55", "target": "ev:cit_55", "type": "SUPPORTED_BY", "rule": None},
    {"source": "person:priya", "target": "pr:41", "type": "AUTHORED", "rule": None},
    {"source": "person:marco", "target": "pr:77", "type": "AUTHORED", "rule": None},
    {"source": "person:lena", "target": "pr:90", "type": "AUTHORED", "rule": None},
    {"source": "person:tom", "target": "pr:55", "type": "AUTHORED", "rule": None},
    {"source": "person:tom", "target": "pr:104", "type": "AUTHORED", "rule": None},
    {"source": "person:lena", "target": "pr:77", "type": "REVIEWED", "rule": None},
)

EXAMPLE_QUESTIONS: dict[str, dict[str, object]] = {
    "full": {"question": "Why is MAX_RETRIES 3?", "outcome": "full", "reason_code": None},
    "superseded": {"question": "Is MAX_RETRIES still 6?", "outcome": "full", "reason_code": None},
    "file": {"question": "Why does config.py change so often?", "outcome": "full", "reason_code": None},
    "rejected": {"question": "Why is RETRY_BACKOFF_MS configurable?", "outcome": "partial", "reason_code": None},
    "no_decision_path": {"question": "Why is _PAD_BYTES 17?", "outcome": "refusal", "reason_code": "no_decision_path"},
    "no_verified_quote": {"question": "Why did the netclient package move that helper into its own module?", "outcome": "partial", "reason_code": "no_verified_quote"},
    "ambiguous": {"question": "Why is retry set this way?", "outcome": "refusal", "reason_code": "ambiguous_entity"},
    "entity_not_found": {"question": "Why is TIMEOUT_MS 500?", "outcome": "refusal", "reason_code": "entity_not_found"},
    "out_of_scope": {"question": "Why was the team late for the demo?", "outcome": "refusal", "reason_code": "out_of_scope"},
}
