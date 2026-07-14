"""Configuration rendering models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class InterfaceConfigurationContext(BaseModel):
    """Common interface rendering data."""

    name: str
    description: str | None = None
    ip_address: str | None = None
    subnet_mask: str | None = None
    enabled: bool = True
    access_vlan: int | None = None
    trunk_vlans: list[int] = Field(default_factory=list)


class RouterSubinterfaceContext(BaseModel):
    """Router-on-a-stick subinterface rendering data."""

    name: str
    parent_interface: str
    vlan_id: int
    description: str | None = None
    ip_address: str | None = None
    subnet_mask: str | None = None
    enabled: bool = True


class StaticRouteContext(BaseModel):
    """Static route rendering data."""

    destination_network: str
    subnet_mask: str
    next_hop: str | None = None
    outgoing_interface: str | None = None


class OSPFNetworkContext(BaseModel):
    """OSPF network statement rendering data."""

    network: str
    wildcard_mask: str
    area: int = 0


class OSPFContext(BaseModel):
    """OSPF process rendering data."""

    process_id: int
    networks: list[OSPFNetworkContext] = Field(default_factory=list)


class DHCPPoolContext(BaseModel):
    """DHCP pool rendering data."""

    name: str
    network: str
    subnet_mask: str
    default_router: str
    dns_servers: list[str] = Field(default_factory=list)


class ACLRuleContext(BaseModel):
    """ACL rule rendering data."""

    action: str
    protocol: str
    source: str
    destination: str
    source_port: str | None = None
    destination_port: str | None = None


class ACLContext(BaseModel):
    """ACL rendering data."""

    name: str
    acl_type: str
    rules: list[ACLRuleContext] = Field(default_factory=list)


class VLANContext(BaseModel):
    """Switch VLAN rendering data."""

    vlan_id: int
    name: str


class DeviceConfigurationContext(BaseModel):
    """Unified template context for a single device."""

    device_id: str
    hostname: str
    platform: str
    device_type: str
    physical_interfaces: list[InterfaceConfigurationContext] = Field(default_factory=list)
    subinterfaces: list[RouterSubinterfaceContext] = Field(default_factory=list)
    static_routes: list[StaticRouteContext] = Field(default_factory=list)
    ospf: list[OSPFContext] = Field(default_factory=list)
    dhcp_pools: list[DHCPPoolContext] = Field(default_factory=list)
    acls: list[ACLContext] = Field(default_factory=list)
    vlans: list[VLANContext] = Field(default_factory=list)
    access_ports: list[InterfaceConfigurationContext] = Field(default_factory=list)
    trunk_ports: list[InterfaceConfigurationContext] = Field(default_factory=list)
    endpoint_ip_address: str | None = None
    endpoint_subnet_mask: str | None = None
    endpoint_gateway: str | None = None


class RenderedConfiguration(BaseModel):
    """Rendered configuration for one device."""

    device_id: str
    hostname: str
    platform: str
    template_name: str
    content: str
    content_hash: str
    validation_warnings: list[str] = Field(default_factory=list)


class ConfigurationPreview(BaseModel):
    """Human-readable preview bundle."""

    project_name: str
    rendered_configurations: list[RenderedConfiguration] = Field(default_factory=list)

