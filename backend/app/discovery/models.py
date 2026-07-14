"""Discovery and operational state models."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.gns3.models import GNS3ConsoleInfo


class InterfaceOperationalState(BaseModel):
    """Operational view of an interface."""

    name: str
    ip_address: str | None = None
    status: str | None = None
    protocol: str | None = None


class DiscoveredVLAN(BaseModel):
    """VLAN state parsed from a device."""

    vlan_id: int
    name: str
    status: str | None = None
    interfaces: list[str] = Field(default_factory=list)


class DiscoveredTrunk(BaseModel):
    """Trunk interface state."""

    interface_name: str
    allowed_vlans: list[int] = Field(default_factory=list)


class DiscoveredRoute(BaseModel):
    """Route parsed from CLI output."""

    code: str
    network: str
    next_hop: str | None = None
    outgoing_interface: str | None = None


class DiscoveredACL(BaseModel):
    """ACL and its rendered entries."""

    name: str
    acl_type: str | None = None
    entries: list[str] = Field(default_factory=list)


class DiscoveredOSPFNeighbor(BaseModel):
    """OSPF neighbor state."""

    neighbor_id: str
    address: str
    state: str
    interface_name: str


class DiscoveredDeviceState(BaseModel):
    """Structured operational state for one device."""

    device_id: str
    hostname: str
    platform: str
    console: GNS3ConsoleInfo
    running_config: str | None = None
    interfaces: list[InterfaceOperationalState] = Field(default_factory=list)
    vlans: list[DiscoveredVLAN] = Field(default_factory=list)
    trunk_vlans: list[DiscoveredTrunk] = Field(default_factory=list)
    routes: list[DiscoveredRoute] = Field(default_factory=list)
    acls: list[DiscoveredACL] = Field(default_factory=list)
    ospf_neighbors: list[DiscoveredOSPFNeighbor] = Field(default_factory=list)
    raw_outputs: dict[str, str] = Field(default_factory=dict)


class DeviceStateSnapshot(BaseModel):
    """Desired and discovered state for a device."""

    device_id: str
    desired_configuration: str | None = None
    desired_configuration_hash: str | None = None
    discovered_state: DiscoveredDeviceState


class DiscoveredNetworkState(BaseModel):
    """Discovered project-wide state."""

    project_id: str
    project_name: str
    device_snapshots: list[DeviceStateSnapshot] = Field(default_factory=list)

