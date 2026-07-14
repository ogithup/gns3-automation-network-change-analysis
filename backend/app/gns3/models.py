"""Pydantic models for GNS3 API integration."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GNS3Version(BaseModel):
    """Version response from the GNS3 server."""

    version: str
    local: bool | None = None


class GNS3Project(BaseModel):
    """Project metadata returned by GNS3."""

    project_id: str
    name: str
    status: str | None = None


class GNS3Template(BaseModel):
    """Template metadata returned by GNS3."""

    template_id: str
    name: str
    template_type: str
    category: str | None = None
    compute_id: str | None = None


class GNS3Node(BaseModel):
    """Node metadata returned by GNS3."""

    node_id: str
    name: str
    node_type: str | None = None
    template_id: str | None = None
    console: int | None = None
    console_host: str | None = None
    console_type: str | None = None
    status: str | None = None
    x: int | None = None
    y: int | None = None


class GNS3Link(BaseModel):
    """Link metadata returned by GNS3."""

    link_id: str


class GNS3ProjectCreateRequest(BaseModel):
    """Input payload for project creation."""

    name: str


class GNS3NodeCreateRequest(BaseModel):
    """Input payload for node creation from a template."""

    name: str
    x: int | None = None
    y: int | None = None
    compute_id: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class GNS3NodeUpdateRequest(BaseModel):
    """Input payload for node updates."""

    x: int | None = None
    y: int | None = None


class GNS3LinkEndpoint(BaseModel):
    """One end of a GNS3 link."""

    node_id: str
    adapter_number: int
    port_number: int


class GNS3LinkCreateRequest(BaseModel):
    """Input payload for link creation."""

    endpoints: list[GNS3LinkEndpoint]


class GNS3ConsoleInfo(BaseModel):
    """Console connection details for a node."""

    node_id: str
    console_host: str | None = None
    console: int | None = None
    console_type: str | None = None


class GNS3DomainNodeMapping(BaseModel):
    """Mapping between a domain device identifier and a GNS3 node."""

    domain_device_id: str
    gns3_node_id: str
    template_id: str
    name: str


class GNS3NodeDeploymentRequest(BaseModel):
    """Planner-level input for a device node to be created."""

    domain_device_id: str
    name: str
    platform: str
    x: int | None = None
    y: int | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class GNS3LinkDeploymentRequest(BaseModel):
    """Planner-level input for a physical link to be created."""

    source_domain_device_id: str
    target_domain_device_id: str
    source_adapter_number: int
    source_port_number: int
    target_adapter_number: int
    target_port_number: int


class GNS3DeploymentPlan(BaseModel):
    """Dry-run view of planned GNS3 resources."""

    project_name: str
    nodes: list[GNS3NodeDeploymentRequest]
    links: list[GNS3LinkDeploymentRequest]


class GNS3DeploymentResult(BaseModel):
    """Deployment output including ID mappings."""

    project: GNS3Project
    node_mappings: list[GNS3DomainNodeMapping]
    links: list[GNS3Link]
    devices: dict[str, str] = Field(default_factory=dict)
