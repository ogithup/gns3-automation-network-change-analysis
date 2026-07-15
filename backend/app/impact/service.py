"""Deterministic rule-based root cause analysis service."""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network

from app.discovery.models import DiscoveredDeviceState, DiscoveredNetworkState
from app.domain.models import Device, Endpoint, PhysicalLink, TopologySpec
from app.impact.models import RootCauseAnalysisResult, RootCauseFinding
from app.validation.models import CombinedValidationResult


class RootCauseAnalysisService:
    """Diagnose failed connectivity using rule-based layered checks."""

    def analyze_connectivity_failure(
        self,
        *,
        topology: TopologySpec,
        discovered_state: DiscoveredNetworkState,
        source_endpoint_id: str,
        target_endpoint_id: str,
        validation_result: CombinedValidationResult | None = None,
    ) -> RootCauseAnalysisResult:
        source = next(endpoint for endpoint in topology.endpoints if endpoint.id == source_endpoint_id)
        target = next(endpoint for endpoint in topology.endpoints if endpoint.id == target_endpoint_id)
        device_map = {device.id: device for device in topology.devices}
        snapshots = {
            snapshot.device_id: snapshot.discovered_state
            for snapshot in discovered_state.device_snapshots
        }

        if validation_result and validation_result.predicted_reachable:
            return RootCauseAnalysisResult(
                source_endpoint_id=source.id,
                target_endpoint_id=target.id,
                findings=[],
            )

        source_switch_id, source_switch_port = _resolve_switch_attachment(topology.links, source.device_id)
        router_switch_id, router_switch_port = _resolve_router_switch_attachment(topology)
        gateway_device, gateway_interface = _find_gateway_device(topology, source.default_gateway)
        target_gateway_device, target_gateway_interface = _find_gateway_device(topology, target.default_gateway)

        source_switch_state = snapshots.get(source_switch_id or "")
        router_switch_state = snapshots.get(router_switch_id or "")
        gateway_state = snapshots.get(gateway_device.id) if gateway_device is not None else None
        target_gateway_state = (
            snapshots.get(target_gateway_device.id) if target_gateway_device is not None else None
        )

        shutdown_finding = _build_shutdown_finding(
            device=gateway_device,
            interface_name=gateway_interface,
            discovered_state=gateway_state,
        )
        if shutdown_finding is None:
            shutdown_finding = _build_shutdown_finding(
                device=target_gateway_device,
                interface_name=target_gateway_interface,
                discovered_state=target_gateway_state,
            )
        if shutdown_finding is not None:
            return RootCauseAnalysisResult(
                source_endpoint_id=source.id,
                target_endpoint_id=target.id,
                findings=[shutdown_finding],
            )

        if not _gateway_is_valid(topology, source):
            return RootCauseAnalysisResult(
                source_endpoint_id=source.id,
                target_endpoint_id=target.id,
                findings=[
                    RootCauseFinding(
                        suspected_root_cause=f"{source.hostname} has an invalid gateway configuration.",
                        confidence_score=0.95,
                        osi_layer="Layer3",
                        supporting_evidence=[
                            f"Endpoint gateway {source.default_gateway} is not valid for source subnet/VLAN.",
                        ],
                        commands_evaluated=["show running-config", "show ip interface brief"],
                        failed_checks=["Source IP configuration"],
                        recommended_remediation=f"Correct the default gateway for {source.hostname}.",
                        rollback_recommendation="Rollback the gateway change if it was recently modified.",
                    ),
                ],
            )

        if source_switch_state is not None and source_switch_port is not None:
            expected_vlan = source.vlan_id
            discovered_vlan = _find_access_vlan(source_switch_state, source_switch_port)
            if expected_vlan is not None and discovered_vlan is not None and discovered_vlan != expected_vlan:
                return RootCauseAnalysisResult(
                    source_endpoint_id=source.id,
                    target_endpoint_id=target.id,
                    findings=[
                        RootCauseFinding(
                            suspected_root_cause=f"{source_switch_id.upper()} {source_switch_port} is in the wrong access VLAN.",
                            confidence_score=0.94,
                            osi_layer="Layer2",
                            supporting_evidence=[
                                f"Topology expects VLAN {expected_vlan} for {source.hostname}.",
                                f"show vlan brief places {source_switch_port} in VLAN {discovered_vlan}.",
                            ],
                            commands_evaluated=["show vlan brief"],
                            failed_checks=["Access VLAN membership"],
                            recommended_remediation=f"Assign {source_switch_port} to VLAN {expected_vlan}.",
                            rollback_recommendation="Rollback the access VLAN change on the switch port.",
                        ),
                    ],
                )

        if (
            router_switch_state is not None
            and router_switch_port is not None
            and target.vlan_id is not None
            and not _trunk_carries_vlan(router_switch_state, target.vlan_id)
        ):
            return RootCauseAnalysisResult(
                source_endpoint_id=source.id,
                target_endpoint_id=target.id,
                findings=[
                    RootCauseFinding(
                        suspected_root_cause=f"{router_switch_id.upper()} {router_switch_port} trunk does not carry VLAN {target.vlan_id}.",
                        confidence_score=0.98,
                        osi_layer="Layer2",
                        supporting_evidence=[
                            f"show interfaces trunk does not list VLAN {target.vlan_id}.",
                        ],
                        commands_evaluated=["show interfaces trunk"],
                        failed_checks=["Trunk VLAN propagation"],
                        recommended_remediation=f"Add VLAN {target.vlan_id} to the trunk allowed VLAN list.",
                        rollback_recommendation="Rollback the trunk VLAN removal if it was part of the recent change.",
                    ),
                ],
            )

        if gateway_device is not None and gateway_state is not None:
            target_network = _target_network(topology, target)
            if target_network is not None and not _routes_cover_network(gateway_state, target_network):
                has_ospf = any(
                    protocol.device_id == gateway_device.id and protocol.protocol == "ospf"
                    for protocol in topology.routing_protocols
                )
                if has_ospf and not gateway_state.ospf_neighbors:
                    finding = RootCauseFinding(
                        suspected_root_cause=f"{gateway_device.hostname} has no established OSPF neighbor.",
                        confidence_score=0.9,
                        osi_layer="Layer3",
                        supporting_evidence=[
                            "show ip ospf neighbor returned no active adjacency.",
                            f"Destination network {target_network} is not present in the routing table.",
                        ],
                        commands_evaluated=["show ip ospf neighbor", "show ip route"],
                        failed_checks=["OSPF neighbor state", "Routing table"],
                        recommended_remediation="Restore OSPF adjacency before retrying validation.",
                        rollback_recommendation="Rollback the routing change or restore OSPF configuration.",
                    )
                else:
                    finding = RootCauseFinding(
                        suspected_root_cause=f"{gateway_device.hostname} is missing a route to {target_network}.",
                        confidence_score=0.9,
                        osi_layer="Layer3",
                        supporting_evidence=[
                            f"show ip route does not contain {target_network}.",
                        ],
                        commands_evaluated=["show ip route"],
                        failed_checks=["Routing table"],
                        recommended_remediation=f"Add or restore a route toward {target_network}.",
                        rollback_recommendation="Rollback the route removal or restore previous routing state.",
                    )
                return RootCauseAnalysisResult(
                    source_endpoint_id=source.id,
                    target_endpoint_id=target.id,
                    findings=[finding],
                )

        if gateway_state is not None and _acl_blocks_traffic(gateway_state, source.ip_address, target.ip_address):
            return RootCauseAnalysisResult(
                source_endpoint_id=source.id,
                target_endpoint_id=target.id,
                findings=[
                    RootCauseFinding(
                        suspected_root_cause=f"An ACL on {gateway_device.hostname if gateway_device else 'the gateway'} denies the traffic.",
                        confidence_score=0.93,
                        osi_layer="Layer3",
                        supporting_evidence=[
                            f"show access-lists contains a deny entry matching {source.ip_address} to {target.ip_address}.",
                        ],
                        commands_evaluated=["show access-lists"],
                        failed_checks=["ACL behavior"],
                        recommended_remediation="Adjust the ACL to permit the required traffic.",
                        rollback_recommendation="Rollback the ACL change if the deny was recently introduced.",
                    ),
                ],
            )

        return RootCauseAnalysisResult(
            source_endpoint_id=source.id,
            target_endpoint_id=target.id,
            findings=[
                RootCauseFinding(
                    suspected_root_cause="No deterministic root cause matched the current evidence.",
                    confidence_score=0.4,
                    osi_layer="Layer3",
                    supporting_evidence=["Available evidence did not match any configured troubleshooting rule."],
                    commands_evaluated=["show ip interface brief", "show vlan brief", "show interfaces trunk", "show ip route", "show access-lists", "show ip ospf neighbor"],
                    failed_checks=["Unknown"],
                    recommended_remediation="Collect additional runtime evidence and rerun analysis.",
                    rollback_recommendation="Consider rollback if this failure was introduced by the latest change.",
                ),
            ],
        )


def _resolve_switch_attachment(links: list[PhysicalLink], endpoint_device_id: str) -> tuple[str | None, str | None]:
    for link in links:
        if link.source_device == endpoint_device_id:
            return link.target_device, link.target_interface
        if link.target_device == endpoint_device_id:
            return link.source_device, link.source_interface
    return None, None


def _resolve_router_switch_attachment(topology: TopologySpec) -> tuple[str | None, str | None]:
    for link in topology.links:
        source = next((device for device in topology.devices if device.id == link.source_device), None)
        target = next((device for device in topology.devices if device.id == link.target_device), None)
        if source and target and {source.type, target.type} == {"router", "switch"}:
            if target.type == "switch":
                return target.id, link.target_interface
            return source.id, link.source_interface
    return None, None


def _find_gateway_device(topology: TopologySpec, gateway: IPv4Address | None) -> tuple[Device | None, str | None]:
    if gateway is None:
        return None, None
    for device in topology.devices:
        for interface in device.interfaces:
            if interface.ipv4_address is not None and interface.ipv4_address.ip == gateway:
                return device, interface.name
    return None, None


def _gateway_is_valid(topology: TopologySpec, endpoint: Endpoint) -> bool:
    if endpoint.default_gateway is None:
        return False
    if endpoint.subnet_id:
        subnet = next((item for item in topology.subnets if item.id == endpoint.subnet_id), None)
        if subnet and endpoint.default_gateway not in subnet.network:
            return False
    if endpoint.vlan_id is not None:
        vlan = next((item for item in topology.vlans if item.vlan_id == endpoint.vlan_id), None)
        if vlan and vlan.subnet and endpoint.default_gateway not in vlan.subnet:
            return False
    gateway_device, _ = _find_gateway_device(topology, endpoint.default_gateway)
    return gateway_device is not None


def _build_shutdown_finding(
    *,
    device: Device | None,
    interface_name: str | None,
    discovered_state: DiscoveredDeviceState | None,
) -> RootCauseFinding | None:
    if device is None or interface_name is None or discovered_state is None:
        return None
    interface_state = next(
        (interface for interface in discovered_state.interfaces if interface.name == interface_name),
        None,
    )
    if interface_state is None or interface_state.status != "administratively down":
        return None
    return RootCauseFinding(
        suspected_root_cause=f"{device.hostname} {interface_name} is shutdown.",
        confidence_score=0.96,
        osi_layer="Layer3",
        supporting_evidence=[
            f"show ip interface brief marks {interface_name} as administratively down.",
        ],
        commands_evaluated=["show ip interface brief"],
        failed_checks=["Interface state"],
        recommended_remediation=f"Enable {interface_name} on {device.hostname}.",
        rollback_recommendation="Rollback the interface shutdown change if this was introduced by the deployment.",
    )


def _find_access_vlan(discovered_device: DiscoveredDeviceState, interface_name: str) -> int | None:
    for vlan in discovered_device.vlans:
        if interface_name in vlan.interfaces:
            return vlan.vlan_id
    return None


def _trunk_carries_vlan(discovered_device: DiscoveredDeviceState, vlan_id: int) -> bool:
    return any(vlan_id in trunk.allowed_vlans for trunk in discovered_device.trunk_vlans)


def _target_network(topology: TopologySpec, endpoint: Endpoint) -> IPv4Network | None:
    if endpoint.subnet_id:
        subnet = next((item for item in topology.subnets if item.id == endpoint.subnet_id), None)
        if subnet is not None:
            return subnet.network
    if endpoint.vlan_id is not None:
        vlan = next((item for item in topology.vlans if item.vlan_id == endpoint.vlan_id), None)
        if vlan is not None:
            return vlan.subnet
    return None


def _routes_cover_network(discovered_device: DiscoveredDeviceState, target_network: IPv4Network) -> bool:
    return any(
        IPv4Network(route.network, strict=False).overlaps(target_network)
        for route in discovered_device.routes
    )


def _acl_blocks_traffic(discovered_device: DiscoveredDeviceState, source_ip: IPv4Address, target_ip: IPv4Address) -> bool:
    source_text = str(source_ip)
    target_text = str(target_ip)
    for acl in discovered_device.acls:
        for entry in acl.entries:
            lowered = entry.lower()
            if "deny" in lowered and source_text in lowered and target_text in lowered:
                return True
    return False
