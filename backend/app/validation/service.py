"""Hybrid reachability and runtime validation engine."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from ipaddress import IPv4Address, IPv4Network

from app.discovery.models import DiscoveredNetworkState
from app.domain.models import ACL, ACLRule, Device, Endpoint, PhysicalLink, Route, TopologySpec, VLAN
from app.graph.service import GraphService
from app.validation.models import (
    ACLEvaluation,
    CombinedValidationResult,
    ModelReachabilityResult,
    RouteEvaluation,
    RuntimeValidationResult,
)

RuntimeValidator = Callable[[TopologySpec, Endpoint, Endpoint], Awaitable[RuntimeValidationResult]]


class ValidationService:
    """Evaluate predicted and runtime reachability."""

    def __init__(
        self,
        *,
        graph_service: GraphService | None = None,
        runtime_validator: RuntimeValidator | None = None,
    ) -> None:
        self.graph_service = graph_service or GraphService()
        self.runtime_validator = runtime_validator

    async def validate_connectivity(
        self,
        topology: TopologySpec,
        *,
        source_endpoint_id: str,
        target_endpoint_id: str,
        discovered_state: DiscoveredNetworkState | None = None,
    ) -> CombinedValidationResult:
        _ = discovered_state
        source = next((endpoint for endpoint in topology.endpoints if endpoint.id == source_endpoint_id), None)
        target = next((endpoint for endpoint in topology.endpoints if endpoint.id == target_endpoint_id), None)

        if source is None:
            predicted = ModelReachabilityResult(
                reachable=False,
                failure_stage="source_active",
                technical_explanation=f"Source endpoint '{source_endpoint_id}' is missing from the current state.",
            )
            return CombinedValidationResult(
                predicted_reachable=False,
                actual_reachable=None,
                state="MODEL_ONLY",
                failure_stage=predicted.failure_stage,
                technical_explanation=predicted.technical_explanation,
            )

        if target is None:
            predicted = ModelReachabilityResult(
                reachable=False,
                failure_stage="destination_availability",
                technical_explanation=f"Target endpoint '{target_endpoint_id}' is missing from the current state.",
            )
            return CombinedValidationResult(
                predicted_reachable=False,
                actual_reachable=None,
                state="MODEL_ONLY",
                failure_stage=predicted.failure_stage,
                technical_explanation=predicted.technical_explanation,
            )

        predicted = self._analyze_model(topology, source, target)
        runtime_result: RuntimeValidationResult | None = None
        actual_reachable: bool | None = None

        if self.runtime_validator is not None:
            runtime_result = await self.runtime_validator(topology, source, target)
            actual_reachable = runtime_result.reachable

        state = _resolve_match_state(predicted.reachable, actual_reachable)
        suspected_reason = None
        if state == "MODEL_RUNTIME_MISMATCH":
            suspected_reason = "Configuration was not applied successfully"

        return CombinedValidationResult(
            predicted_reachable=predicted.reachable,
            actual_reachable=actual_reachable,
            state=state,
            path=predicted.path,
            evaluated_routes=predicted.evaluated_routes,
            evaluated_acls=predicted.evaluated_acls,
            failure_stage=predicted.failure_stage,
            technical_explanation=predicted.technical_explanation
            if runtime_result is None
            else f"{predicted.technical_explanation} Runtime: {runtime_result.technical_explanation}",
            suspected_reason=suspected_reason,
            runtime=runtime_result,
        )

    def _analyze_model(
        self,
        topology: TopologySpec,
        source: Endpoint,
        target: Endpoint,
    ) -> ModelReachabilityResult:
        devices_by_id = {device.id: device for device in topology.devices}
        vlans_by_id = {vlan.vlan_id: vlan for vlan in topology.vlans}
        links = topology.links

        source_device = devices_by_id[source.device_id]
        target_device = devices_by_id[target.device_id]
        source_vlan = vlans_by_id.get(source.vlan_id) if source.vlan_id is not None else None
        target_vlan = vlans_by_id.get(target.vlan_id) if target.vlan_id is not None else None

        source_link = _find_link_for_device(links, source.device_id)
        target_link = _find_link_for_device(links, target.device_id)
        source_switch_interface = _find_peer_interface(source_link, source.device_id)
        target_switch_interface = _find_peer_interface(target_link, target.device_id)
        switch_device_id = _find_peer_device(source_link, source.device_id)

        if source_device.type != "endpoint":
            return ModelReachabilityResult(
                reachable=False,
                failure_stage="source_active",
                technical_explanation=f"Source device '{source.device_id}' is not an endpoint.",
            )

        if source_vlan is None or source.default_gateway is None:
            return ModelReachabilityResult(
                reachable=False,
                failure_stage="source_addressing",
                technical_explanation=f"Source endpoint '{source.id}' is missing VLAN or gateway information.",
            )

        if source.ip_address not in source_vlan.subnet:
            return ModelReachabilityResult(
                reachable=False,
                failure_stage="source_addressing",
                technical_explanation=f"Source IP {source.ip_address} is outside VLAN {source_vlan.vlan_id}.",
            )

        if source_switch_interface is None:
            return ModelReachabilityResult(
                reachable=False,
                failure_stage="access_vlan",
                technical_explanation=f"No switch access interface found for endpoint '{source.id}'.",
            )

        switch_device = devices_by_id[switch_device_id] if switch_device_id is not None else None
        switch_interface = _find_interface(switch_device, source_switch_interface) if switch_device is not None else None
        if switch_interface is None or switch_interface.access_vlan != source.vlan_id:
            return ModelReachabilityResult(
                reachable=False,
                failure_stage="access_vlan",
                technical_explanation=f"Switch access VLAN is not aligned for endpoint '{source.id}'.",
            )

        trunk_interface = _find_trunk_interface_for_router_link(topology, switch_device_id)
        if trunk_interface is None or source.vlan_id not in trunk_interface.trunk_vlans:
            return ModelReachabilityResult(
                reachable=False,
                failure_stage="trunk_propagation",
                technical_explanation=f"VLAN {source.vlan_id} is not carried over the switch trunk.",
            )
        if (
            target.vlan_id is not None
            and source.vlan_id != target.vlan_id
            and target.vlan_id not in trunk_interface.trunk_vlans
        ):
            return ModelReachabilityResult(
                reachable=False,
                failure_stage="trunk_propagation",
                technical_explanation=f"Destination VLAN {target.vlan_id} is not carried over the switch trunk.",
            )

        gateway_device, gateway_interface_name = _find_gateway_interface(topology, source.default_gateway)
        if gateway_device is None or gateway_interface_name is None:
            return ModelReachabilityResult(
                reachable=False,
                failure_stage="gateway_availability",
                technical_explanation=f"Gateway {source.default_gateway} is not present on any device interface.",
            )

        gateway_interface = _find_interface(gateway_device, gateway_interface_name)
        if gateway_interface is None or not gateway_interface.enabled:
            return ModelReachabilityResult(
                reachable=False,
                failure_stage="gateway_availability",
                technical_explanation=f"Gateway interface '{gateway_interface_name}' is disabled.",
            )

        route_result = self._evaluate_routes(topology, gateway_device, source, target)
        if not route_result[0]:
            return ModelReachabilityResult(
                reachable=False,
                path=[f"endpoint:{source.id}", f"gateway:{source.default_gateway}"],
                evaluated_routes=route_result[1],
                failure_stage="route_selection",
                technical_explanation="No connected or routed path to the destination network was found.",
            )

        acl_result = self._evaluate_acls(topology.acls, gateway_device.id, source, target)
        if acl_result[0] is False:
            return ModelReachabilityResult(
                reachable=False,
                path=[
                    f"endpoint:{source.id}",
                    f"vlan:{source.vlan_id}",
                    f"gateway:{source.default_gateway}",
                    f"endpoint:{target.id}",
                ],
                evaluated_routes=route_result[1],
                evaluated_acls=acl_result[1],
                failure_stage="acl_evaluation",
                technical_explanation="An ACL on the gateway device denies the traffic.",
            )

        if target_switch_interface is None or target_vlan is None:
            return ModelReachabilityResult(
                reachable=False,
                failure_stage="destination_availability",
                evaluated_routes=route_result[1],
                evaluated_acls=acl_result[1],
                technical_explanation=f"Destination endpoint '{target.id}' is missing switch or VLAN information.",
            )

        target_switch = devices_by_id.get(_find_peer_device(target_link, target.device_id) or "")
        target_switch_port = _find_interface(target_switch, target_switch_interface) if target_switch is not None else None
        if target_switch_port is None or target_switch_port.access_vlan != target.vlan_id:
            return ModelReachabilityResult(
                reachable=False,
                failure_stage="destination_availability",
                evaluated_routes=route_result[1],
                evaluated_acls=acl_result[1],
                technical_explanation="Destination access VLAN is not aligned with endpoint membership.",
            )

        path = [
            f"endpoint:{source.id}",
            f"vlan:{source.vlan_id}",
            f"gateway:{source.default_gateway}",
            f"endpoint:{target.id}",
        ]
        if source.vlan_id != target.vlan_id:
            path.insert(2, f"trunk:{trunk_interface.name}")

        return ModelReachabilityResult(
            reachable=True,
            path=path,
            evaluated_routes=route_result[1],
            evaluated_acls=acl_result[1],
            technical_explanation="Model-based analysis found a valid VLAN, gateway, route, and ACL path.",
        )

    def _evaluate_routes(
        self,
        topology: TopologySpec,
        gateway_device: Device,
        source: Endpoint,
        target: Endpoint,
    ) -> tuple[bool, list[RouteEvaluation]]:
        evaluations: list[RouteEvaluation] = []
        target_network = _resolve_target_network(topology, target)
        if target_network is None:
            return False, evaluations

        connected_networks = [
            interface.ipv4_address.network
            for interface in gateway_device.interfaces
            if interface.ipv4_address is not None
        ]
        for network in connected_networks:
            evaluations.append(
                RouteEvaluation(
                    route_type="connected",
                    destination=str(network),
                    matched=IPv4Address(target.ip_address) in network,
                ),
            )
        if any(evaluation.matched for evaluation in evaluations):
            return True, evaluations

        static_routes = [
            route for route in topology.routes if route.device_id == gateway_device.id
        ]
        best_match: Route | None = None
        for route in static_routes:
            matched = target.ip_address in route.destination
            evaluations.append(
                RouteEvaluation(
                    route_type=route.protocol,
                    destination=str(route.destination),
                    next_hop=str(route.next_hop) if route.next_hop else None,
                    matched=matched,
                ),
            )
            if matched and (best_match is None or route.destination.prefixlen > best_match.destination.prefixlen):
                best_match = route

        return best_match is not None, evaluations

    def _evaluate_acls(
        self,
        acls: list[ACL],
        device_id: str,
        source: Endpoint,
        target: Endpoint,
    ) -> tuple[bool | None, list[ACLEvaluation]]:
        evaluations: list[ACLEvaluation] = []
        for acl in [item for item in acls if item.device_id == device_id]:
            for rule in acl.rules:
                matched = _acl_rule_matches(rule, source.ip_address, target.ip_address)
                evaluations.append(
                    ACLEvaluation(
                        acl_name=acl.name,
                        action=rule.action,
                        source=rule.source,
                        destination=rule.destination,
                        matched=matched,
                    ),
                )
                if matched:
                    return rule.action == "permit", evaluations

        return None, evaluations


def _resolve_match_state(predicted: bool, actual: bool | None) -> str:
    if actual is None:
        return "MODEL_ONLY"
    if predicted == actual:
        return "MATCH"
    return "MODEL_RUNTIME_MISMATCH"


def _find_link_for_device(links: list[PhysicalLink], device_id: str) -> PhysicalLink | None:
    return next(
        (
            link
            for link in links
            if link.source_device == device_id or link.target_device == device_id
        ),
        None,
    )


def _find_peer_interface(link: PhysicalLink | None, device_id: str) -> str | None:
    if link is None:
        return None
    if link.source_device == device_id:
        return link.target_interface
    return link.source_interface


def _find_peer_device(link: PhysicalLink | None, device_id: str) -> str | None:
    if link is None:
        return None
    if link.source_device == device_id:
        return link.target_device
    return link.source_device


def _find_interface(device: Device | None, interface_name: str | None):
    if device is None or interface_name is None:
        return None
    return next((interface for interface in device.interfaces if interface.name == interface_name), None)


def _find_trunk_interface_for_router_link(topology: TopologySpec, switch_device_id: str | None):
    if switch_device_id is None:
        return None
    switch = next((device for device in topology.devices if device.id == switch_device_id), None)
    if switch is None:
        return None
    return next((interface for interface in switch.interfaces if interface.trunk_vlans), None)


def _find_gateway_interface(topology: TopologySpec, gateway_address: IPv4Address) -> tuple[Device | None, str | None]:
    for device in topology.devices:
        for interface in device.interfaces:
            if interface.ipv4_address is not None and interface.ipv4_address.ip == gateway_address:
                return device, interface.name
    return None, None


def _resolve_target_network(topology: TopologySpec, endpoint: Endpoint) -> IPv4Network | None:
    if endpoint.subnet_id is not None:
        subnet = next((item for item in topology.subnets if item.id == endpoint.subnet_id), None)
        if subnet is not None:
            return subnet.network
    if endpoint.vlan_id is not None:
        vlan = next((item for item in topology.vlans if item.vlan_id == endpoint.vlan_id), None)
        if vlan is not None:
            return vlan.subnet
    return None


def _acl_rule_matches(rule: ACLRule, source_ip: IPv4Address, destination_ip: IPv4Address) -> bool:
    return _selector_matches(rule.source, source_ip) and _selector_matches(rule.destination, destination_ip)


def _selector_matches(selector: str, ip_address: IPv4Address) -> bool:
    if selector == "any":
        return True
    if selector.startswith("host "):
        return IPv4Address(selector.removeprefix("host ").strip()) == ip_address
    try:
        return ip_address in IPv4Network(selector, strict=False)
    except ValueError:
        return False
