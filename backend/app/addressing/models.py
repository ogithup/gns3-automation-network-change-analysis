"""Addressing and VLSM planning models."""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network
from typing import Literal

from pydantic import BaseModel, Field


class SegmentRequirement(BaseModel):
    """A LAN or VLAN segment that needs an address allocation."""

    name: str
    host_count: int = Field(ge=1)
    vlan_id: int | None = Field(default=None, ge=1, le=4094)
    fixed_subnet: IPv4Network | None = None
    switch_management_count: int = Field(default=0, ge=0)
    extra_reserved_count: int = Field(default=0, ge=0)
    gateway_policy: Literal["first_usable", "last_usable"] = "first_usable"

    @property
    def required_usable_hosts(self) -> int:
        return self.host_count + 1 + self.switch_management_count + self.extra_reserved_count


class PointToPointRequirement(BaseModel):
    """A point-to-point allocation, optionally using /31."""

    name: str
    use_slash31: bool = False
    fixed_subnet: IPv4Network | None = None

    @property
    def prefix_length(self) -> int:
        return 31 if self.use_slash31 else 30


class AddressingRequest(BaseModel):
    """Planner input for VLSM allocation."""

    base_network: IPv4Network
    segments: list[SegmentRequirement] = Field(default_factory=list)
    reserved_networks: list[IPv4Network] = Field(default_factory=list)
    point_to_point_links: list[PointToPointRequirement] = Field(default_factory=list)


class HostAssignment(BaseModel):
    """A named IP assignment within an allocated subnet."""

    role: Literal["gateway", "switch_management", "endpoint", "link_endpoint"]
    name: str
    ip_address: IPv4Address


class SegmentAllocation(BaseModel):
    """Allocated details for a segment or point-to-point link."""

    name: str
    kind: Literal["segment", "point_to_point"]
    network: IPv4Network
    prefix_length: int
    gateway: IPv4Address | None = None
    vlan_id: int | None = None
    host_capacity: int
    requested_hosts: int
    host_assignments: list[HostAssignment] = Field(default_factory=list)
    explanation: list[str] = Field(default_factory=list)


class AddressingPlan(BaseModel):
    """Final deterministic addressing plan."""

    base_network: IPv4Network
    allocations: list[SegmentAllocation]
    reserved_networks: list[IPv4Network]
    unallocated_networks: list[IPv4Network]
    report: str


class MinimalSubnetCalculation(BaseModel):
    """Derived prefix and capacity for a host requirement."""

    required_usable_hosts: int
    prefix_length: int
    total_addresses: int
    usable_hosts: int


class AllocationReportRow(BaseModel):
    """Human-readable row used for planning output."""

    name: str
    kind: str
    network: str
    gateway: str | None = None
    notes: list[str] = Field(default_factory=list)
