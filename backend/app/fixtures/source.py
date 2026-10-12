from __future__ import annotations

import re

from app.config import Settings
from app.fixtures.dataset import (
    CITATIONS_BY_DECISION,
    DECISION_BY_ID,
    ENTITIES,
    ENTITY_BY_ID,
    GRAPH_EDGES,
    GRAPH_NODES,
    REPOSITORY,
    REPOSITORY_ID,
    WHO_TO_ASK,
)
from app.schemas.ask import AskRequest, AskResponse
from app.schemas.common import GRAPH_NODE_CAP, Outcome, ReasonCode
from app.schemas.decisions import DecisionDetail
from app.schemas.entities import Candidate, Entity, EntityListResponse
from app.schemas.graph import GraphEdge, GraphNode, GraphResponse
from app.schemas.repository import RepositoryResponse
from app.services.data_source import NotFoundError

TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")
SEGMENT_PATTERN = re.compile(r"[a-z0-9]+")
MIN_SEGMENT_LENGTH = 3

HIGH_SIGNALS = {
    "directness": 1.0,
    "provenance": 0.8,
    "agreement": 0.4,
    "relevance": 0.9,
    "temporal_consistency": 1.0,
    "contradiction": 0.0,
}
FILE_SIGNALS = {**HIGH_SIGNALS, "agreement": 0.7}
REJECTED_SIGNALS = {
    "directness": 0.5,
    "provenance": 0.8,
    "agreement": 0.4,
    "relevance": 0.85,
    "temporal_consistency": 0.5,
    "contradiction": 0.0,
}
NO_EVIDENCE_SIGNALS = {
    "directness": 0.0,
    "provenance": 0.6,
    "agreement": 0.0,
    "relevance": 0.5,
    "temporal_consistency": 1.0,
    "contradiction": 0.0,
}
NO_PATH_SIGNALS = {
    "directness": 0.0,
    "provenance": 0.0,
    "agreement": 0.0,
    "relevance": 0.3,
    "temporal_consistency": 0.3,
    "contradiction": 0.0,
}

MAX_RETRIES_HISTORY = ("dec_41", "dec_77", "dec_90")


def _segments(label: str) -> list[str]:
    return [
        segment
        for segment in SEGMENT_PATTERN.findall(label.lower())
        if len(segment) >= MIN_SEGMENT_LENGTH
    ]


def matching_entities(question: str) -> list[tuple[str, int]]:
    tokens = set(TOKEN_PATTERN.findall(question.lower()))
    scored: list[tuple[str, int]] = []
    for entity in ENTITIES:
        score = sum(1 for segment in _segments(entity.label) if segment in tokens)
        if score:
            scored.append((entity.id, score))
    best = max((score for _, score in scored), default=0)
    return sorted((pair for pair in scored if pair[1] == best))


def has_entity_signal(question: str) -> bool:
    tokens = set(TOKEN_PATTERN.findall(question.lower()))
    if any("_" in token or token.isupper() for token in tokens):
        return True
    return any(entity for entity, _ in matching_entities(question))


class FixtureDataSource:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def get_repository(self, repository_id: str) -> RepositoryResponse:
        self._require_repository(repository_id)
        return REPOSITORY

    def search_entities(self, repository_id: str, query: str) -> EntityListResponse:
        self._require_repository(repository_id)
        needle = query.strip().lower()
        matches = [entity for entity in ENTITIES if needle in entity.label.lower()]
        return EntityListResponse(entities=matches, query=query, fixture=True)

    def get_decision(self, decision_id: str) -> DecisionDetail:
        decision = DECISION_BY_ID.get(decision_id)
        if decision is None:
            raise NotFoundError(f"decision {decision_id!r} not found")
        gaps: list[str] = []
        if not CITATIONS_BY_DECISION.get(decision_id):
            gaps.append("No verified quote was extracted for this change.")
        return DecisionDetail(
            **decision.model_dump(),
            citations=CITATIONS_BY_DECISION.get(decision_id, []),
            evidence_gaps=gaps,
            fixture=True,
        )

    def get_graph(self, repository_id: str, entity_id: str | None) -> GraphResponse:
        self._require_repository(repository_id)
        nodes = [GraphNode(**node) for node in GRAPH_NODES]
        edges = [GraphEdge(**edge) for edge in GRAPH_EDGES]
        if entity_id is not None:
            if entity_id not in ENTITY_BY_ID:
                raise NotFoundError(f"entity {entity_id!r} not found")
            nodes, edges = self._neighbourhood(entity_id, nodes, edges)
        return self._cap(nodes, edges)

    def ask(self, repository_id: str, request: AskRequest | str) -> AskResponse:
        self._require_repository(repository_id)
        question = request if isinstance(request, str) else request.question
        entity_id = None if isinstance(request, str) else request.entity_id

        if entity_id is not None:
            if entity_id not in ENTITY_BY_ID:
                return self._entity_not_found(question)
            matched = [entity_id]
        else:
            matched = [entity_id for entity_id, _ in matching_entities(question)]
            if not matched:
                if has_entity_signal(question):
                    return self._entity_not_found(question)
                return self._out_of_scope(question)
            if len(matched) > 1:
                return self._ambiguous(question, matched)

        entity = ENTITY_BY_ID[matched[0]]
        builder = {
            "key:MAX_RETRIES": self._max_retries,
            "file:netclient/config.py": self._config_file,
            "key:RETRY_BACKOFF_MS": self._rejected_backoff,
            "key:_PAD_BYTES": self._no_decision_path,
            "file:netclient/retry.py": self._no_verified_quote,
            "module:netclient": self._no_verified_quote,
        }[entity.id]
        return builder(entity, question)

    def _require_repository(self, repository_id: str) -> None:
        if repository_id != REPOSITORY_ID:
            raise NotFoundError(f"repository {repository_id!r} not found")

    def _neighbourhood(
        self,
        entity_id: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        seed = {entity_id, REPOSITORY_ID}
        frontier = {entity_id}
        connected = {
            edge.target for edge in edges if edge.source in frontier and edge.target not in seed
        } | {
            edge.source for edge in edges if edge.target in frontier and edge.source not in seed
        }
        seed |= connected
        kept = [node for node in nodes if node.id in seed]
        kept_ids = {node.id for node in kept}
        return kept, [edge for edge in edges if edge.source in kept_ids and edge.target in kept_ids]

    def _cap(self, nodes: list[GraphNode], edges: list[GraphEdge]) -> GraphResponse:
        limit = min(self._settings.max_graph_nodes, GRAPH_NODE_CAP)
        if len(nodes) <= limit:
            return GraphResponse(nodes=nodes, edges=edges, truncated=False, fixture=True)
        kept = nodes[:limit]
        kept_ids = {node.id for node in kept}
        return GraphResponse(
            nodes=kept,
            edges=[edge for edge in edges if edge.source in kept_ids and edge.target in kept_ids],
            truncated=True,
            fixture=True,
        )

    def _out_of_scope(self, question: str) -> AskResponse:
        return AskResponse(
            outcome=Outcome.REFUSAL,
            reason_code=ReasonCode.OUT_OF_SCOPE,
            answer="CodeWhy answers questions about files, modules and config keys. Rephrase the question around the code.",
            entity=None,
            confidence=None,
            evidence_gaps=[
                "The question does not name a file, a module or a config key.",
                "A question naming one code entity would let CodeWhy traverse to its decisions.",
            ],
            fixture=True,
        )

    def _entity_not_found(self, question: str) -> AskResponse:
        return AskResponse(
            outcome=Outcome.REFUSAL,
            reason_code=ReasonCode.ENTITY_NOT_FOUND,
            answer="No file, module or config key in this repository matches that name.",
            entity=None,
            confidence=None,
            evidence_gaps=[
                f"No entity in acme/netclient matches the name used in the question about {question!r}.",
                "The name may belong to a different repository, or the entity may have been deleted.",
            ],
            fixture=True,
        )

    def _ambiguous(self, question: str, matched: list[str]) -> AskResponse:
        return AskResponse(
            outcome=Outcome.REFUSAL,
            reason_code=ReasonCode.AMBIGUOUS_ENTITY,
            answer=None,
            entity=None,
            candidates=[
                Candidate(id=entity_id, type=ENTITY_BY_ID[entity_id].type, label=ENTITY_BY_ID[entity_id].label)
                for entity_id in matched
            ],
            confidence=None,
            evidence_gaps=[
                "The question matches more than one entity, so no decision path was chosen.",
                "Repeat the question naming one file, module or config key.",
            ],
            fixture=True,
        )

    def _no_decision_path(self, entity: Entity, question: str) -> AskResponse:
        return AskResponse(
            outcome=Outcome.REFUSAL,
            reason_code=ReasonCode.NO_DECISION_PATH,
            answer=f"No recorded decision explains {entity.label}. The constant exists, but nothing in the history says why.",
            entity=entity,
            confidence={"score": 0.09, "signals": NO_PATH_SIGNALS},
            evidence_gaps=[
                f"No pull request, issue or design doc in acme/netclient governs {entity.label}.",
                "A commit message, review comment or design doc mentioning this constant would settle the question.",
            ],
            fixture=True,
        )

    def _no_verified_quote(self, entity: Entity, question: str) -> AskResponse:
        return AskResponse(
            outcome=Outcome.PARTIAL,
            reason_code=ReasonCode.NO_VERIFIED_QUOTE,
            answer=f"Change recorded, rationale unknown. {entity.label} was touched by PR #104, whose description states no reason.",
            entity=entity,
            confidence={"score": 0.35, "signals": NO_EVIDENCE_SIGNALS},
            decisions=[DECISION_BY_ID["dec_104"]],
            citations=[],
            evidence_gaps=[
                "PR #104 has no quoted rationale that survived the quote check.",
                "A review comment or a design doc on the move would settle the question.",
            ],
            who_to_ask=[person for person in WHO_TO_ASK if person.login == "tom"],
            fixture=True,
        )

    def _rejected_backoff(self, entity: Entity, question: str) -> AskResponse:
        return AskResponse(
            outcome=Outcome.PARTIAL,
            answer="proposed in PR #55, closed without merging",
            entity=entity,
            confidence={"score": 0.59, "signals": REJECTED_SIGNALS},
            decisions=[DECISION_BY_ID["dec_55"]],
            citations=CITATIONS_BY_DECISION["dec_55"],
            evidence_gaps=[
                "The change was closed unmerged, so it never set a default.",
                "The later move to netclient/retry.py left no recorded reason.",
            ],
            who_to_ask=[person for person in WHO_TO_ASK if person.login == "tom"],
            code_differs_from_latest=True,
            fixture=True,
        )

    def _max_retries(self, entity: Entity, question: str) -> AskResponse:
        decisions = [DECISION_BY_ID[decision_id] for decision_id in MAX_RETRIES_HISTORY]
        citations = list(CITATIONS_BY_DECISION["dec_41"]) + list(CITATIONS_BY_DECISION["dec_90"])
        asking_about_six = any(token in question.lower() for token in ("still", "six"))
        answer = (
            "No. MAX_RETRIES is 3 today. PR #77 raised it to 6, and PR #90 reverted that change, "
            "so the cap from PR #41 is active again."
            if asking_about_six
            else "MAX_RETRIES is 3 because PR #41 capped it at three to match the mobile client, "
            "which gives up after three retries. PR #77 raised it to 6 and PR #90 reverted that."
        )
        return AskResponse(
            outcome=Outcome.FULL,
            answer=answer,
            entity=entity,
            confidence={"score": 0.83, "signals": HIGH_SIGNALS},
            decisions=decisions,
            citations=citations,
            who_to_ask=list(WHO_TO_ASK[:3]),
            code_differs_from_latest=asking_about_six,
            fixture=True,
        )

    def _config_file(self, entity: Entity, question: str) -> AskResponse:
        decisions = [DECISION_BY_ID[decision_id] for decision_id in MAX_RETRIES_HISTORY]
        return AskResponse(
            outcome=Outcome.FULL,
            answer=(
                "config.py holds MAX_RETRIES, capped at 3 by PR #41, raised to 6 by PR #77 and "
                "reverted to 3 by PR #90. RETRY_BACKOFF_MS was proposed in PR #55 and never merged."
            ),
            entity=entity,
            confidence={"score": 0.89, "signals": FILE_SIGNALS},
            decisions=decisions,
            citations=list(CITATIONS_BY_DECISION["dec_41"]) + list(CITATIONS_BY_DECISION["dec_90"]),
            who_to_ask=list(WHO_TO_ASK[:3]),
            code_differs_from_latest=False,
            fixture=True,
        )
