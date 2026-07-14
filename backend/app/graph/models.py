"""Graph models and React Flow serialization types."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


GraphNodeType = Literal[
    "device",
    "interface",
    "vlan",
    "subnet",
    "endpoint",
    "gateway",
    "route",
    "acl",
    "service",
]

GraphEdgeType = Literal[
    "physically_connected",
    "attached_to",
    "member_of_vlan",
    "carried_over_trunk",
    "uses_gateway",
    "routes_to",
    "protected_by_acl",
    "depends_on",
]

GraphViewType = Literal["physical", "layer2", "layer3", "dependency", "service"]


class GraphNodeRecord(BaseModel):
    """Serializable graph node representation."""

    id: str
    node_type: GraphNodeType
    label: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class GraphEdgeRecord(BaseModel):
    """Serializable graph edge representation."""

    source: str
    target: str
    edge_type: GraphEdgeType
    attributes: dict[str, Any] = Field(default_factory=dict)


class ReactFlowNode(BaseModel):
    """React Flow node serialization."""

    id: str
    type: str = "default"
    position: dict[str, float]
    data: dict[str, Any]


class ReactFlowEdge(BaseModel):
    """React Flow edge serialization."""

    id: str
    source: str
    target: str
    label: str | None = None
    type: str = "smoothstep"
    data: dict[str, Any] = Field(default_factory=dict)


class ReactFlowGraph(BaseModel):
    """React Flow graph payload."""

    nodes: list[ReactFlowNode] = Field(default_factory=list)
    edges: list[ReactFlowEdge] = Field(default_factory=list)

