from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.fixtures.dataset import CITATIONS, DECISIONS, ENTITIES, EXAMPLE_QUESTIONS, REPOSITORY_ID
from app.fixtures.source import FixtureDataSource
from app.services.data_source import NotFoundError

FICTION_MARKERS = ("acme", "priya", "marco", "lena", "tom")
REAL_HOST_MARKERS = ("github.com", "gitlab.com", "bitbucket")


def source(**overrides: object) -> FixtureDataSource:
    return FixtureDataSource(Settings(_env_file=None, **overrides))


def test_every_example_question_validates_and_is_flagged() -> None:
    data_source = source()
    for name, spec in EXAMPLE_QUESTIONS.items():
        response = data_source.ask(REPOSITORY_ID, spec["question"])
        assert response.fixture is True, name
        assert response.outcome == spec["outcome"], name
        assert response.reason_code == spec["reason_code"], name


def test_no_real_repository_or_login_leaks_into_the_dataset() -> None:
    blob = json.dumps(
        [entity.model_dump() for entity in ENTITIES]
        + [decision.model_dump() for decision in DECISIONS]
        + [citation.model_dump() for citation in CITATIONS]
    )
    for host in REAL_HOST_MARKERS:
        assert host not in blob
    for marker in FICTION_MARKERS:
        assert marker in blob or marker in REPOSITORY_ID


def test_supersession_states_follow_the_section_six_rules() -> None:
    states = {decision.id: decision.state for decision in DECISIONS}
    assert states["dec_41"] == "ACTIVE"
    assert states["dec_77"] == "SUPERSEDED"
    assert states["dec_90"] == "ACTIVE"
    assert states["dec_55"] == "REJECTED"


def test_rejected_decision_supersedes_nothing() -> None:
    rejected = next(decision for decision in DECISIONS if decision.state == "REJECTED")
    assert rejected.supersedes == []
    assert rejected.superseded_by == []
    assert rejected.probable_superseded_by == []
    assert rejected.conflicts_with == []
    assert rejected.reaffirms == []


def test_revert_reactivates_the_original_decision() -> None:
    by_id = {decision.id: decision for decision in DECISIONS}
    assert by_id["dec_90"].supersedes == ["dec_77"]
    assert by_id["dec_41"].superseded_by == ["dec_77"]
    assert by_id["dec_41"].state == "ACTIVE"


def test_ambiguous_question_returns_both_candidates() -> None:
    response = source().ask(REPOSITORY_ID, EXAMPLE_QUESTIONS["ambiguous"]["question"])
    assert {candidate.label for candidate in response.candidates} == {"retry.py", "RETRY_BACKOFF_MS"}
    assert response.answer is None
    assert response.confidence is None


def test_rejected_answer_is_partial_medium_and_names_the_pull_request() -> None:
    response = source().ask(REPOSITORY_ID, EXAMPLE_QUESTIONS["rejected"]["question"])
    assert response.outcome == "partial"
    assert response.confidence.label == "MEDIUM"
    assert response.answer == "proposed in PR #55, closed without merging"
    assert response.decisions[0].state == "REJECTED"
    assert response.decisions[0].supersedes == []
    assert response.decisions[0].superseded_by == []
    assert response.citations[0].decision_id == response.decisions[0].id


def test_full_answer_carries_a_source_citation_naming_a_returned_decision() -> None:
    response = source().ask(REPOSITORY_ID, EXAMPLE_QUESTIONS["full"]["question"])
    decision_ids = {decision.id for decision in response.decisions}
    assert response.confidence.label == "HIGH"
    assert any(citation.kind == "SOURCE" for citation in response.citations)
    assert all(citation.decision_id in decision_ids for citation in response.citations)


def test_superseded_answer_explains_the_revert() -> None:
    response = source().ask(REPOSITORY_ID, EXAMPLE_QUESTIONS["superseded"]["question"])
    assert response.outcome == "full"
    assert "revert" in response.answer.lower()
    assert response.code_differs_from_latest is True
    assert [decision.id for decision in response.decisions] == ["dec_41", "dec_77", "dec_90"]


def test_no_decision_path_refusal_carries_a_low_score_and_gaps() -> None:
    response = source().ask(REPOSITORY_ID, EXAMPLE_QUESTIONS["no_decision_path"]["question"])
    assert response.outcome == "refusal"
    assert response.confidence.label == "LOW"
    assert response.evidence_gaps
    assert response.decisions == []


def test_no_verified_quote_partial_has_no_citations() -> None:
    response = source().ask(REPOSITORY_ID, EXAMPLE_QUESTIONS["no_verified_quote"]["question"])
    assert response.outcome == "partial"
    assert response.reason_code == "no_verified_quote"
    assert response.citations == []
    assert response.decisions[0].rationale is None


def test_unknown_repository_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        source().get_repository("acme/other")


def test_unknown_decision_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        source().get_decision("dec_missing")


def test_entity_search_is_case_insensitive() -> None:
    response = source().search_entities(REPOSITORY_ID, "max_re")
    assert [entity.id for entity in response.entities] == ["key:MAX_RETRIES"]


def test_entity_search_with_no_match_is_empty_not_an_error() -> None:
    assert source().search_entities(REPOSITORY_ID, "zzzz").entities == []


def test_graph_is_not_truncated_for_the_fixture_repository() -> None:
    graph = source().get_graph(REPOSITORY_ID, None)
    assert graph.truncated is False
    assert 0 < len(graph.nodes) <= 80


def test_graph_filtered_by_entity_keeps_every_edge_internal() -> None:
    scoped = source().get_graph(REPOSITORY_ID, "key:MAX_RETRIES")
    ids = {node.id for node in scoped.nodes}
    assert all(edge.source in ids and edge.target in ids for edge in scoped.edges)


def test_graph_filtered_by_entity_is_a_subset_of_the_whole_graph() -> None:
    whole = {node.id for node in source().get_graph(REPOSITORY_ID, None).nodes}
    scoped = {node.id for node in source().get_graph(REPOSITORY_ID, "key:MAX_RETRIES").nodes}
    assert scoped <= whole
    assert REPOSITORY_ID in scoped


def test_graph_traversal_depth_bounds_the_neighbourhood() -> None:
    shallow = {node.id for node in source(max_graph_traversal_depth=1).get_graph(REPOSITORY_ID, "key:MAX_RETRIES").nodes}
    deep = {node.id for node in source().get_graph(REPOSITORY_ID, "key:MAX_RETRIES").nodes}
    assert shallow < deep


def test_graph_truncation_sets_the_flag_and_drops_dangling_edges() -> None:
    graph = source(max_graph_nodes=3).get_graph(REPOSITORY_ID, None)
    assert graph.truncated is True
    assert len(graph.nodes) == 3
    ids = {node.id for node in graph.nodes}
    assert all(edge.source in ids and edge.target in ids for edge in graph.edges)


def test_every_fixture_response_is_flagged() -> None:
    data_source = source()
    assert data_source.get_repository(REPOSITORY_ID).fixture is True
    assert data_source.search_entities(REPOSITORY_ID, "MAX_RETRIES").fixture is True
    assert data_source.get_graph(REPOSITORY_ID, None).fixture is True
    assert data_source.get_decision("dec_41").fixture is True
    assert data_source.ask(REPOSITORY_ID, EXAMPLE_QUESTIONS["full"]["question"]).fixture is True


def test_ask_accepts_a_request_object() -> None:
    from app.schemas.ask import AskRequest

    response = source().ask(REPOSITORY_ID, AskRequest(question=EXAMPLE_QUESTIONS["full"]["question"]))
    assert response.outcome == "full"
