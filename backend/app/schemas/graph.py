from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import GRAPH_NODE_CAP


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    type: str
    props: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    type: str
    rule: str | None = None
    # Relationship properties (for example a supersession edge's `method` and
    # `confidence`). `rule` stays a first-class field; `props` carries the rest so a
    # client can render an edge's provenance without a second request.
    props: dict[str, Any] = Field(default_factory=dict)


class GraphResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool = False
    fixture: bool

    @model_validator(mode="after")
    def _check_bounds(self) -> "GraphResponse":
        if len(self.nodes) > GRAPH_NODE_CAP:
            raise ValueError(
                f"R6_NODE_CAP: graph has {len(self.nodes)} nodes, the cap is {GRAPH_NODE_CAP}. "
                "Truncate before constructing the response."
            )
        known = {node.id for node in self.nodes}
        if len(known) != len(self.nodes):
            raise ValueError(
                f"R6_DUPLICATE_NODE: graph has {len(self.nodes)} nodes but only {len(known)} "
                f"distinct ids; an edge to a shared id would resolve ambiguously"
            )
        for edge in self.edges:
            if edge.source not in known or edge.target not in known:
                raise ValueError(
                    f"R6_DANGLING_EDGE: edge {edge.source} -> {edge.target} of type "
                    f"{edge.type!r} references a node that is not in nodes"
                )
        return self
