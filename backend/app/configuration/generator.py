"""Jinja2-based configuration rendering services."""

from __future__ import annotations

from hashlib import sha256
from ipaddress import IPv4Interface, IPv4Network
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, Template

from app.configuration.exceptions import (
    ConfigurationSyntaxError,
    UnsupportedPlatformError,
)
from app.configuration.models import (
    ACLContext,
    ACLRuleContext,
    ConfigurationPreview,
    DeviceConfigurationContext,
    DHCPPoolContext,
    InterfaceConfigurationContext,
    OSPFContext,
    OSPFNetworkContext,
    RenderedConfiguration,
    RouterSubinterfaceContext,
    StaticRouteContext,
    VLANContext,
)
from app.domain.models import ACL, DHCPPool, Device, Endpoint, Route, RoutingProtocol, TopologySpec


class TemplateRegistry:
    """Load per-platform Jinja2 templates from the local template directory."""

    def __init__(self, template_root: Path | None = None) -> None:
        self.template_root = template_root or Path(__file__).with_name("templates")
        self.environment = Environment(
            loader=FileSystemLoader(self.template_root),
            autoescape=False,
            trim_blocks=False,
            lstrip_blocks=True,
            undefined=StrictUndefined,
        )
        self._platform_templates = {
            "iosv": "iosv/base.j2",
            "iosvl2": "iosvl2/base.j2",
            "vpcs": "vpcs/ip_config.j2",
        }

    def get_template_name(self, platform: str) -> str:
        try:
            return self._platform_templates[platform]
        except KeyError as error:
            raise UnsupportedPlatformError(
                f"Unsupported configuration platform '{platform}'",
            ) from error

    def get_template(self, platform: str) -> Template:
        return self.environment.get_template(self.get_template_name(platform))


class DeviceContextBuilder:
    """Build deterministic template contexts from a validated topology."""

    def build(self, topology: TopologySpec, device: Device) -> DeviceConfigurationContext:
        if device.platform == "iosv":
            return self._build_router_context(topology, device)
        if device.platform == "iosvl2":
            return self._build_switch_context(topology, device)
        if device.platform == "vpcs":
            return self._build_vpcs_context(topology, device)

        raise UnsupportedPlatformError(
            f"Unsupported configuration platform '{device.platform}'",
        )

    def _build_router_context(
        self,
        topology: TopologySpec,
        device: Device,
    ) -> DeviceConfigurationContext:
        physical_interfaces: list[InterfaceConfigurationContext] = []
        subinterfaces: list[RouterSubinterfaceContext] = []

        for interface in sorted(device.interfaces, key=lambda item: item.name):
            if "." in interface.name:
                parent_interface, vlan_suffix = interface.name.split(".", maxsplit=1)
                subinterfaces.append(
                    RouterSubinterfaceContext(
                        name=interface.name,
                        parent_interface=parent_interface,
                        vlan_id=int(vlan_suffix),
                        description=interface.description,
                        ip_address=_stringify_ipv4_address(interface.ipv4_address),
                        subnet_mask=_stringify_subnet_mask(interface.ipv4_address),
                        enabled=interface.enabled,
                    ),
                )
                continue

            physical_interfaces.append(
                InterfaceConfigurationContext(
                    name=interface.name,
                    description=interface.description,
                    ip_address=_stringify_ipv4_address(interface.ipv4_address),
                    subnet_mask=_stringify_subnet_mask(interface.ipv4_address),
                    enabled=interface.enabled,
                ),
            )

        static_routes = [
            StaticRouteContext(
                destination_network=str(route.destination.network_address),
                subnet_mask=str(route.destination.netmask),
                next_hop=str(route.next_hop) if route.next_hop else None,
                outgoing_interface=route.outgoing_interface,
            )
            for route in sorted(
                _routes_for_device(topology.routes, device.id),
                key=lambda item: (str(item.destination), item.id),
            )
        ]

        ospf_contexts = [
            OSPFContext(
                process_id=protocol.process_id or 1,
                networks=[
                    OSPFNetworkContext(
                        network=str(network.network_address),
                        wildcard_mask=str(network.hostmask),
                    )
                    for network in sorted(protocol.networks, key=lambda item: str(item))
                ],
            )
            for protocol in sorted(
                _ospf_protocols_for_device(topology.routing_protocols, device.id),
                key=lambda item: item.process_id or 1,
            )
        ]

        router_networks = {
            interface.ipv4_address.network
            for interface in device.interfaces
            if interface.ipv4_address is not None
        }
        dhcp_pools = [
            DHCPPoolContext(
                name=pool.name,
                network=str(pool.subnet.network_address),
                subnet_mask=str(pool.subnet.netmask),
                default_router=str(pool.default_gateway),
                dns_servers=[str(server) for server in pool.dns_servers],
            )
            for pool in sorted(
                _dhcp_pools_for_networks(topology.dhcp_pools, router_networks),
                key=lambda item: item.id,
            )
        ]

        acls = [
            ACLContext(
                name=acl.name,
                acl_type=acl.type,
                rules=[
                    ACLRuleContext(
                        action=rule.action,
                        protocol=rule.protocol,
                        source=_format_acl_selector(rule.source),
                        destination=_format_acl_selector(rule.destination),
                        source_port=rule.source_port,
                        destination_port=rule.destination_port,
                    )
                    for rule in acl.rules
                ],
            )
            for acl in sorted(_acls_for_device(topology.acls, device.id), key=lambda item: item.id)
        ]

        return DeviceConfigurationContext(
            device_id=device.id,
            hostname=device.hostname,
            platform=device.platform,
            device_type=device.type,
            physical_interfaces=physical_interfaces,
            subinterfaces=subinterfaces,
            static_routes=static_routes,
            ospf=ospf_contexts,
            dhcp_pools=dhcp_pools,
            acls=acls,
        )

    def _build_switch_context(
        self,
        topology: TopologySpec,
        device: Device,
    ) -> DeviceConfigurationContext:
        vlans = [
            VLANContext(vlan_id=vlan.vlan_id, name=vlan.name)
            for vlan in sorted(topology.vlans, key=lambda item: item.vlan_id)
        ]

        access_ports: list[InterfaceConfigurationContext] = []
        trunk_ports: list[InterfaceConfigurationContext] = []
        physical_interfaces: list[InterfaceConfigurationContext] = []

        for interface in sorted(device.interfaces, key=lambda item: item.name):
            context = InterfaceConfigurationContext(
                name=interface.name,
                description=interface.description,
                ip_address=_stringify_ipv4_address(interface.ipv4_address),
                subnet_mask=_stringify_subnet_mask(interface.ipv4_address),
                enabled=interface.enabled,
                access_vlan=interface.access_vlan,
                trunk_vlans=list(interface.trunk_vlans),
            )
            physical_interfaces.append(context)

            if interface.trunk_vlans:
                trunk_ports.append(context)
            elif interface.access_vlan is not None:
                access_ports.append(context)

        return DeviceConfigurationContext(
            device_id=device.id,
            hostname=device.hostname,
            platform=device.platform,
            device_type=device.type,
            physical_interfaces=physical_interfaces,
            vlans=vlans,
            access_ports=access_ports,
            trunk_ports=trunk_ports,
        )

    def _build_vpcs_context(
        self,
        topology: TopologySpec,
        device: Device,
    ) -> DeviceConfigurationContext:
        endpoint = next(
            (endpoint for endpoint in topology.endpoints if endpoint.device_id == device.id),
            None,
        )
        if endpoint is None:
            raise ConfigurationSyntaxError(
                "VPCS device "
                f"'{device.hostname}' ({device.id}) is missing an endpoint record in the topology specification.",
            )
        subnet = _resolve_endpoint_network(topology, endpoint)

        return DeviceConfigurationContext(
            device_id=device.id,
            hostname=device.hostname,
            platform=device.platform,
            device_type=device.type,
            endpoint_ip_address=str(endpoint.ip_address),
            endpoint_subnet_mask=str(subnet.netmask),
            endpoint_gateway=str(endpoint.default_gateway) if endpoint.default_gateway else None,
        )


class ConfigurationSyntaxValidator:
    """Perform basic sanity checks on rendered configurations."""

    def validate(self, rendered: RenderedConfiguration) -> list[str]:
        warnings: list[str] = []
        content = rendered.content

        if "{{" in content or "{%" in content:
            raise ConfigurationSyntaxError(
                f"Unresolved template markers remain in configuration for '{rendered.device_id}'",
            )

        if rendered.platform in {"iosv", "iosvl2"} and "hostname " not in content:
            raise ConfigurationSyntaxError(
                f"Missing hostname statement in configuration for '{rendered.device_id}'",
            )

        if rendered.platform == "vpcs" and not content.startswith("set pcname"):
            raise ConfigurationSyntaxError(
                f"Invalid VPCS configuration header for '{rendered.device_id}'",
            )

        if not content.endswith("\n"):
            warnings.append("Configuration did not end with a trailing newline.")

        return warnings


class ConfigurationRenderer:
    """Render device configurations from topology data."""

    def __init__(
        self,
        template_registry: TemplateRegistry | None = None,
        context_builder: DeviceContextBuilder | None = None,
        syntax_validator: ConfigurationSyntaxValidator | None = None,
    ) -> None:
        self.template_registry = template_registry or TemplateRegistry()
        self.context_builder = context_builder or DeviceContextBuilder()
        self.syntax_validator = syntax_validator or ConfigurationSyntaxValidator()

    def render_device(self, topology: TopologySpec, device: Device) -> RenderedConfiguration:
        context = self.context_builder.build(topology, device)
        template_name = self.template_registry.get_template_name(device.platform)
        template = self.template_registry.get_template(device.platform)
        content = _normalize_rendered_content(template.render(**context.model_dump()))

        rendered = RenderedConfiguration(
            device_id=device.id,
            hostname=device.hostname,
            platform=device.platform,
            template_name=template_name,
            content=content,
            content_hash=_hash_content(content),
        )
        rendered.validation_warnings.extend(self.syntax_validator.validate(rendered))
        return rendered

    def render_topology(self, topology: TopologySpec) -> ConfigurationPreview:
        rendered_configurations = [
            self.render_device(topology, device)
            for device in sorted(topology.devices, key=lambda item: item.id)
        ]
        return ConfigurationPreview(
            project_name=topology.project.name,
            rendered_configurations=rendered_configurations,
        )

    def preview_text(self, topology: TopologySpec) -> str:
        preview = self.render_topology(topology)
        sections: list[str] = []
        for rendered in preview.rendered_configurations:
            sections.append(
                "\n".join(
                    [
                        f"## {rendered.hostname} ({rendered.platform})",
                        rendered.content.rstrip(),
                    ],
                ),
            )
        return "\n\n".join(sections) + "\n"


def _routes_for_device(routes: list[Route], device_id: str) -> list[Route]:
    return [route for route in routes if route.device_id == device_id]


def _ospf_protocols_for_device(
    protocols: list[RoutingProtocol],
    device_id: str,
) -> list[RoutingProtocol]:
    return [
        protocol
        for protocol in protocols
        if protocol.device_id == device_id and protocol.protocol == "ospf"
    ]


def _dhcp_pools_for_networks(
    pools: list[DHCPPool],
    networks: set[IPv4Network],
) -> list[DHCPPool]:
    return [pool for pool in pools if pool.subnet in networks]


def _acls_for_device(acls: list[ACL], device_id: str) -> list[ACL]:
    return [acl for acl in acls if acl.device_id == device_id]


def _resolve_endpoint_network(topology: TopologySpec, endpoint: Endpoint) -> IPv4Network:
    if endpoint.subnet_id:
        subnet = next(subnet for subnet in topology.subnets if subnet.id == endpoint.subnet_id)
        return subnet.network
    if endpoint.vlan_id is not None:
        vlan = next(vlan for vlan in topology.vlans if vlan.vlan_id == endpoint.vlan_id)
        if vlan.subnet is not None:
            return vlan.subnet
    return IPv4Interface(f"{endpoint.ip_address}/24").network


def _stringify_ipv4_address(address: IPv4Interface | None) -> str | None:
    if address is None:
        return None
    return str(address.ip)


def _stringify_subnet_mask(address: IPv4Interface | None) -> str | None:
    if address is None:
        return None
    return str(address.network.netmask)


def _format_acl_selector(selector: str) -> str:
    if selector == "any":
        return "any"
    if selector.startswith("host "):
        return selector

    network = IPv4Network(selector, strict=False)
    if network.prefixlen == 32:
        return f"host {network.network_address}"
    return f"{network.network_address} {network.hostmask}"


def _normalize_rendered_content(content: str) -> str:
    lines = [line.rstrip() for line in content.splitlines()]
    normalized = "\n".join(line for line in lines if line != "").strip()
    return normalized + "\n"


def _hash_content(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()
