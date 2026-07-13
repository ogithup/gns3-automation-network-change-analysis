"""Vendor-neutral network domain models for NetTwin AI."""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Interface, IPv4Network
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.exceptions import DomainValidationError


class NetworkProject(BaseModel):
    """Top-level project metadata."""

    name: str
    description: str | None = None


class Site(BaseModel):
    """Logical site grouping for devices and services."""

    id: str
    name: str
    description: str | None = None


class Interface(BaseModel):
    """Vendor-neutral device interface model."""

    name: str
    description: str | None = None
    ipv4_address: IPv4Interface | None = None
    enabled: bool = True
    access_vlan: int | None = None
    trunk_vlans: list[int] = Field(default_factory=list)


class Device(BaseModel):
    """A network node that can be deployed or simulated."""

    id: str
    hostname: str
    type: Literal["router", "switch", "endpoint", "firewall", "server"]
    platform: str
    site_id: str | None = None
    interfaces: list[Interface] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_interfaces(self) -> Device:
        seen: set[str] = set()
        duplicates: list[str] = []

        for interface in self.interfaces:
            if interface.name in seen:
                duplicates.append(interface.name)
            seen.add(interface.name)

        if duplicates:
            duplicate_names = ", ".join(sorted(set(duplicates)))
            raise ValueError(
                f"Device '{self.id}' has duplicate interface names: {duplicate_names}",
            )

        return self


class PhysicalLink(BaseModel):
    """A physical connection between two device interfaces."""

    source_device: str
    source_interface: str
    target_device: str
    target_interface: str


class VLAN(BaseModel):
    """Layer 2 segment definition."""

    vlan_id: int = Field(ge=1, le=4094)
    name: str
    subnet: IPv4Network | None = None
    gateway: IPv4Address | None = None
    endpoint_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_gateway(self) -> VLAN:
        if self.gateway is None or self.subnet is None:
            return self

        if self.gateway not in self.subnet:
            raise ValueError(
                f"Gateway {self.gateway} is outside VLAN {self.vlan_id} subnet {self.subnet}",
            )

        return self


class Subnet(BaseModel):
    """Layer 3 network definition."""

    id: str
    name: str
    network: IPv4Network
    gateway: IPv4Address | None = None
    vlan_id: int | None = Field(default=None, ge=1, le=4094)

    @model_validator(mode="after")
    def validate_gateway(self) -> Subnet:
        if self.gateway is None:
            return self

        if self.gateway not in self.network:
            raise ValueError(
                f"Gateway {self.gateway} is outside subnet {self.network}",
            )

        return self


class Endpoint(BaseModel):
    """A host attached to the network."""

    id: str
    device_id: str
    hostname: str
    ip_address: IPv4Address
    vlan_id: int | None = Field(default=None, ge=1, le=4094)
    subnet_id: str | None = None
    default_gateway: IPv4Address | None = None


class DHCPPool(BaseModel):
    """DHCP scope definition."""

    id: str
    name: str
    subnet: IPv4Network
    default_gateway: IPv4Address
    dns_servers: list[IPv4Address] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_gateway(self) -> DHCPPool:
        if self.default_gateway not in self.subnet:
            raise ValueError(
                f"Default gateway {self.default_gateway} is outside DHCP subnet {self.subnet}",
            )

        return self


class Route(BaseModel):
    """A layer 3 route entry."""

    id: str
    device_id: str
    destination: IPv4Network
    next_hop: IPv4Address | None = None
    outgoing_interface: str | None = None
    protocol: Literal["static", "connected", "ospf"] = "static"


class RoutingProtocol(BaseModel):
    """Routing protocol configuration attached to a device."""

    id: str
    device_id: str
    protocol: Literal["ospf", "static", "connected"]
    process_id: int | None = Field(default=None, ge=1)
    networks: list[IPv4Network] = Field(default_factory=list)


class ACLRule(BaseModel):
    """A single ACL rule."""

    id: str
    action: Literal["permit", "deny"]
    protocol: Literal["ip", "icmp", "tcp", "udp"] = "ip"
    source: str
    destination: str
    source_port: str | None = None
    destination_port: str | None = None

    @model_validator(mode="after")
    def validate_network_selectors(self) -> ACLRule:
        _validate_acl_selector(self.source)
        _validate_acl_selector(self.destination)
        return self


class ACL(BaseModel):
    """An access control list."""

    id: str
    name: str
    type: Literal["standard", "extended"] = "extended"
    device_id: str | None = None
    rules: list[ACLRule] = Field(default_factory=list)


class Service(BaseModel):
    """A logical network service affected by changes."""

    id: str
    name: str
    kind: str
    endpoint_id: str | None = None
    device_id: str | None = None
    vlan_id: int | None = Field(default=None, ge=1, le=4094)
    subnet_id: str | None = None
    critical: bool = False
    ports: list[int] = Field(default_factory=list)


class ConnectivityRequirement(BaseModel):
    """Expected reachability between endpoints."""

    id: str
    source_endpoint_id: str
    target_endpoint_id: str
    protocol: Literal["ping", "icmp", "tcp", "udp"] = "ping"
    port: int | None = Field(default=None, ge=1, le=65535)
    expected: Literal["reachable", "blocked"]


class ValidationTest(BaseModel):
    """Validation test definition for later execution."""

    id: str
    name: str
    test_type: Literal["ping", "traceroute", "interface", "routing", "acl"]
    source_endpoint_id: str | None = None
    target_endpoint_id: str | None = None
    source_device_id: str | None = None
    target_device_id: str | None = None
    expected_success: bool = True


class TopologySpec(BaseModel):
    """Root topology document shared by deployment and simulation."""

    model_config = ConfigDict(extra="forbid")

    project: NetworkProject
    sites: list[Site] = Field(default_factory=list)
    devices: list[Device] = Field(default_factory=list)
    links: list[PhysicalLink] = Field(default_factory=list)
    vlans: list[VLAN] = Field(default_factory=list)
    subnets: list[Subnet] = Field(default_factory=list)
    endpoints: list[Endpoint] = Field(default_factory=list)
    dhcp_pools: list[DHCPPool] = Field(default_factory=list)
    routes: list[Route] = Field(default_factory=list)
    routing_protocols: list[RoutingProtocol] = Field(default_factory=list)
    acls: list[ACL] = Field(default_factory=list)
    services: list[Service] = Field(default_factory=list)
    connectivity_requirements: list[ConnectivityRequirement] = Field(
        default_factory=list,
    )
    validation_tests: list[ValidationTest] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_topology(self) -> TopologySpec:
        errors: list[str] = []

        device_map = _unique_by_key(self.devices, "id", "device", errors)
        site_map = _unique_by_key(self.sites, "id", "site", errors)
        subnet_map = _unique_by_key(self.subnets, "id", "subnet", errors)
        endpoint_map = _unique_by_key(self.endpoints, "id", "endpoint", errors)
        route_protocol_map = _unique_by_key(
            self.routing_protocols,
            "id",
            "routing protocol",
            errors,
        )
        acl_map = _unique_by_key(self.acls, "id", "ACL", errors)
        service_map = _unique_by_key(self.services, "id", "service", errors)
        validation_map = _unique_by_key(
            self.validation_tests,
            "id",
            "validation test",
            errors,
        )
        _ = (route_protocol_map, acl_map, service_map, validation_map)

        vlan_ids: set[int] = set()
        duplicate_vlan_ids: set[int] = set()
        for vlan in self.vlans:
            if vlan.vlan_id in vlan_ids:
                duplicate_vlan_ids.add(vlan.vlan_id)
            vlan_ids.add(vlan.vlan_id)
        if duplicate_vlan_ids:
            duplicates = ", ".join(str(item) for item in sorted(duplicate_vlan_ids))
            errors.append(f"Duplicate VLAN IDs: {duplicates}")

        for device in self.devices:
            if device.site_id and device.site_id not in site_map:
                errors.append(
                    f"Device '{device.id}' references missing site '{device.site_id}'",
                )

        for link in self.links:
            source_device = device_map.get(link.source_device)
            target_device = device_map.get(link.target_device)

            if source_device is None:
                errors.append(
                    f"Link references missing source device '{link.source_device}'",
                )
            if target_device is None:
                errors.append(
                    f"Link references missing target device '{link.target_device}'",
                )

            if source_device and not _device_has_interface(
                source_device,
                link.source_interface,
            ):
                errors.append(
                    f"Device '{link.source_device}' is missing interface '{link.source_interface}'",
                )
            if target_device and not _device_has_interface(
                target_device,
                link.target_interface,
            ):
                errors.append(
                    f"Device '{link.target_device}' is missing interface '{link.target_interface}'",
                )

        networks = [subnet.network for subnet in self.subnets]
        networks.extend(vlan.subnet for vlan in self.vlans if vlan.subnet is not None)
        networks.extend(
            interface.ipv4_address.network
            for device in self.devices
            for interface in device.interfaces
            if interface.ipv4_address is not None
        )
        _collect_overlapping_networks(networks, errors)

        used_ip_addresses: dict[IPv4Address, str] = {}
        for endpoint in self.endpoints:
            _register_ip(
                used_ip_addresses,
                endpoint.ip_address,
                f"endpoint '{endpoint.id}'",
                errors,
            )
        for device in self.devices:
            for interface in device.interfaces:
                if interface.ipv4_address is None:
                    continue
                _register_ip(
                    used_ip_addresses,
                    interface.ipv4_address.ip,
                    f"interface '{device.id}:{interface.name}'",
                    errors,
                )

        for endpoint in self.endpoints:
            if endpoint.device_id not in device_map:
                errors.append(
                    f"Endpoint '{endpoint.id}' references missing device '{endpoint.device_id}'",
                )

            if endpoint.subnet_id and endpoint.subnet_id not in subnet_map:
                errors.append(
                    f"Endpoint '{endpoint.id}' references missing subnet '{endpoint.subnet_id}'",
                )
            elif endpoint.subnet_id:
                subnet = subnet_map[endpoint.subnet_id]
                if endpoint.ip_address not in subnet.network:
                    errors.append(
                        f"Endpoint '{endpoint.id}' IP {endpoint.ip_address} is outside subnet {subnet.network}",
                    )
                if endpoint.default_gateway and endpoint.default_gateway not in subnet.network:
                    errors.append(
                        f"Endpoint '{endpoint.id}' gateway {endpoint.default_gateway} is outside subnet {subnet.network}",
                    )

            if endpoint.vlan_id is not None:
                vlan = _find_vlan(self.vlans, endpoint.vlan_id)
                if vlan is None:
                    errors.append(
                        f"Endpoint '{endpoint.id}' references missing VLAN {endpoint.vlan_id}",
                    )
                elif vlan.subnet and endpoint.ip_address not in vlan.subnet:
                    errors.append(
                        f"Endpoint '{endpoint.id}' IP {endpoint.ip_address} is outside VLAN {endpoint.vlan_id} subnet {vlan.subnet}",
                    )
                if vlan and vlan.subnet and endpoint.default_gateway and endpoint.default_gateway not in vlan.subnet:
                    errors.append(
                        f"Endpoint '{endpoint.id}' gateway {endpoint.default_gateway} is outside VLAN {endpoint.vlan_id} subnet {vlan.subnet}",
                    )

        for vlan in self.vlans:
            for endpoint_id in vlan.endpoint_ids:
                if endpoint_id not in endpoint_map:
                    errors.append(
                        f"VLAN {vlan.vlan_id} references missing endpoint '{endpoint_id}'",
                    )

        for dhcp_pool in self.dhcp_pools:
            if not any(dhcp_pool.subnet == subnet.network for subnet in self.subnets) and not any(
                dhcp_pool.subnet == vlan.subnet for vlan in self.vlans
            ):
                errors.append(
                    f"DHCP pool '{dhcp_pool.id}' subnet {dhcp_pool.subnet} is not declared in subnets or VLANs",
                )

        for route in self.routes:
            device = device_map.get(route.device_id)
            if device is None:
                errors.append(
                    f"Route '{route.id}' references missing device '{route.device_id}'",
                )
            elif route.outgoing_interface and not _device_has_interface(
                device,
                route.outgoing_interface,
            ):
                errors.append(
                    f"Route '{route.id}' references missing interface '{route.outgoing_interface}' on device '{route.device_id}'",
                )

        for protocol in self.routing_protocols:
            if protocol.device_id not in device_map:
                errors.append(
                    f"Routing protocol '{protocol.id}' references missing device '{protocol.device_id}'",
                )

        for acl in self.acls:
            if acl.device_id and acl.device_id not in device_map:
                errors.append(
                    f"ACL '{acl.id}' references missing device '{acl.device_id}'",
                )

        for service in self.services:
            if service.endpoint_id and service.endpoint_id not in endpoint_map:
                errors.append(
                    f"Service '{service.id}' references missing endpoint '{service.endpoint_id}'",
                )
            if service.device_id and service.device_id not in device_map:
                errors.append(
                    f"Service '{service.id}' references missing device '{service.device_id}'",
                )
            if service.subnet_id and service.subnet_id not in subnet_map:
                errors.append(
                    f"Service '{service.id}' references missing subnet '{service.subnet_id}'",
                )
            if service.vlan_id and _find_vlan(self.vlans, service.vlan_id) is None:
                errors.append(
                    f"Service '{service.id}' references missing VLAN '{service.vlan_id}'",
                )

        for requirement in self.connectivity_requirements:
            if requirement.source_endpoint_id not in endpoint_map:
                errors.append(
                    f"Connectivity requirement '{requirement.id}' references missing source endpoint '{requirement.source_endpoint_id}'",
                )
            if requirement.target_endpoint_id not in endpoint_map:
                errors.append(
                    f"Connectivity requirement '{requirement.id}' references missing target endpoint '{requirement.target_endpoint_id}'",
                )

        for test in self.validation_tests:
            if test.source_endpoint_id and test.source_endpoint_id not in endpoint_map:
                errors.append(
                    f"Validation test '{test.id}' references missing source endpoint '{test.source_endpoint_id}'",
                )
            if test.target_endpoint_id and test.target_endpoint_id not in endpoint_map:
                errors.append(
                    f"Validation test '{test.id}' references missing target endpoint '{test.target_endpoint_id}'",
                )
            if test.source_device_id and test.source_device_id not in device_map:
                errors.append(
                    f"Validation test '{test.id}' references missing source device '{test.source_device_id}'",
                )
            if test.target_device_id and test.target_device_id not in device_map:
                errors.append(
                    f"Validation test '{test.id}' references missing target device '{test.target_device_id}'",
                )

        if errors:
            formatted_errors = "\n".join(f"- {error}" for error in errors)
            raise DomainValidationError(f"Topology validation failed:\n{formatted_errors}")

        return self


def _unique_by_key(
    items: list[BaseModel],
    key: str,
    label: str,
    errors: list[str],
) -> dict[str, BaseModel]:
    seen: dict[str, BaseModel] = {}
    duplicates: set[str] = set()

    for item in items:
        item_key = getattr(item, key)
        if item_key in seen:
            duplicates.add(item_key)
        seen[item_key] = item

    if duplicates:
        duplicate_items = ", ".join(sorted(duplicates))
        errors.append(f"Duplicate {label} IDs: {duplicate_items}")

    return seen


def _device_has_interface(device: Device, interface_name: str) -> bool:
    return any(interface.name == interface_name for interface in device.interfaces)


def _collect_overlapping_networks(
    networks: list[IPv4Network],
    errors: list[str],
) -> None:
    for index, left in enumerate(networks):
        for right in networks[index + 1 :]:
            if left == right:
                continue
            if left.overlaps(right):
                errors.append(f"Overlapping subnets detected: {left} and {right}")


def _register_ip(
    used_ip_addresses: dict[IPv4Address, str],
    ip_address: IPv4Address,
    owner: str,
    errors: list[str],
) -> None:
    if ip_address in used_ip_addresses:
        errors.append(
            f"Duplicate IP address {ip_address} used by {used_ip_addresses[ip_address]} and {owner}",
        )
        return

    used_ip_addresses[ip_address] = owner


def _find_vlan(vlans: list[VLAN], vlan_id: int) -> VLAN | None:
    for vlan in vlans:
        if vlan.vlan_id == vlan_id:
            return vlan
    return None


def _validate_acl_selector(value: str) -> None:
    if value == "any":
        return

    if value.startswith("host "):
        host_address = value.removeprefix("host ").strip()
        IPv4Address(host_address)
        return

    try:
        IPv4Network(value, strict=False)
    except ValueError as error:
        raise ValueError(f"Invalid ACL selector '{value}'") from error
