from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.common import GRAPH_NODE_CAP
from app.schemas.graph import GraphEdge, GraphNode, GraphResponse
from app.schemas.health import DependenciesResponse, DependencyStatus, HealthResponse


def nodes(count: int) -> list[GraphNode]:
    return [
        GraphNode(id=f"n{index}", label=f"node {index}", type="CodeEntity", props={})
        for index in range(count)
    ]


def test_graph_response_defaults_to_not_truncated() -> None:
    assert GraphResponse(nodes=nodes(3), edges=[], fixture=True).truncated is False


def test_graph_response_accepts_exactly_the_cap() -> None:
    assert len(GraphResponse(nodes=nodes(GRAPH_NODE_CAP), edges=[], fixture=True).nodes) == GRAPH_NODE_CAP


def test_graph_response_rejects_more_than_the_cap() -> None:
    with pytest.raises(ValidationError) as excinfo:
        GraphResponse(nodes=nodes(GRAPH_NODE_CAP + 1), edges=[], fixture=True)
    assert "R6_NODE_CAP" in str(excinfo.value)


def test_graph_response_rejects_a_dangling_edge() -> None:
    with pytest.raises(ValidationError) as excinfo:
        GraphResponse(nodes=nodes(2), edges=[GraphEdge(source="n0", target="n9", type="GOVERNS")], fixture=True)
    assert "R6_DANGLING_EDGE" in str(excinfo.value)


def test_graph_response_accepts_an_internal_edge() -> None:
    graph = GraphResponse(
        nodes=nodes(2),
        edges=[GraphEdge(source="n0", target="n1", type="SUPERSEDES", rule="1_revert_commit")],
        fixture=True,
    )
    assert graph.edges[0].rule == "1_revert_commit"


def test_health_response_shape() -> None:
    assert HealthResponse(status="ok", version="0.1.0", data_source="fixture").data_source == "fixture"


def test_dependencies_response_reports_not_configured() -> None:
    response = DependenciesResponse(
        services=[DependencyStatus(name="github", status="not configured", detail="GITHUB_TOKEN not set")],
        data_source="fixture",
    )
    assert response.services[0].status == "not configured"


def test_dependency_status_rejects_an_unknown_state() -> None:
    with pytest.raises(ValidationError):
        DependencyStatus(name="github", status="unknown", detail="")
