"""Digital network graph engine built on NetworkX."""

from __future__ import annotations

from collections import defaultdict
from ipaddress import IPv4Address, IPv4Network
from typing import Any

import networkx as nx

from app.discovery.models import DeviceStateSnapshot, DiscoveredNetworkState
from app.domain.models import ACL, Device, Endpoint, PhysicalLink, Route, Service, TopologySpec, VLAN
from app.graph.models import (
    GraphEdgeRecord,
    GraphNodeRecord,
    GraphViewType,
    ReactFlowEdge,
    ReactFlowGraph,
    ReactFlowNode,
)


class GraphService:
    """Build graph views and execute graph queries."""

    def __init__(self) -> None:
        self._layout_y_by_type = {
            "device": 0.0,
            "interface": 120.0,
            "endpoint": 240.0,
            "vlan": 360.0,
            "subnet": 480.0,
            "gateway": 600.0,
            "route": 720.0,
            "acl": 840.0,
            "service": 960.0,
        }

    def build_from_topology(self, topology: TopologySpec) -> nx.MultiDiGraph:
        graph = nx.MultiDiGraph(name=topology.project.name, source="desired")
        device_by_id = {device.id: device for device in topology.devices}
        endpoint_by_id = {endpoint.id: endpoint for endpoint in topology.endpoints}
        vlan_by_id = {vlan.vlan_id: vlan for vlan in topology.vlans}

        for device in topology.devices:
            self._add_device(graph, device)
            for interface in device.interfaces:
                interface_id = _interface_node_id(device.id, interface.name)
                self._add_node(
                    graph,
                    interface_id,
                    "interface",
                    interface.name,
                    device_id=device.id,
                    enabled=interface.enabled,
                    access_vlan=interface.access_vlan,
                    trunk_vlans=list(interface.trunk_vlans),
                )
                self._add_edge(
                    graph,
                    device.id,
                    interface_id,
                    "attached_to",
                )

        for link in topology.links:
            self._add_edge(
                graph,
                _interface_node_id(link.source_device, link.source_interface),
                _interface_node_id(link.target_device, link.target_interface),
                "physically_connected",
            )
            self._add_edge(
                graph,
                _interface_node_id(link.target_device, link.target_interface),
                _interface_node_id(link.source_device, link.source_interface),
                "physically_connected",
            )

        for vlan in topology.vlans:
            vlan_node_id = _vlan_node_id(vlan.vlan_id)
            self._add_node(
                graph,
                vlan_node_id,
                "vlan",
                f"VLAN {vlan.vlan_id}",
                vlan_id=vlan.vlan_id,
                name=vlan.name,
            )

            if vlan.subnet is not None:
                subnet_node_id = _subnet_node_id(str(vlan.subnet))
                self._add_node(
                    graph,
                    subnet_node_id,
                    "subnet",
                    str(vlan.subnet),
                    network=str(vlan.subnet),
                )
                self._add_edge(graph, vlan_node_id, subnet_node_id, "depends_on")

            if vlan.gateway is not None:
                gateway_node_id = _gateway_node_id(str(vlan.gateway))
                self._add_node(
                    graph,
                    gateway_node_id,
                    "gateway",
                    str(vlan.gateway),
                    address=str(vlan.gateway),
                    vlan_id=vlan.vlan_id,
                )
                self._add_edge(graph, vlan_node_id, gateway_node_id, "uses_gateway")

        for endpoint in topology.endpoints:
            endpoint_node_id = _endpoint_node_id(endpoint.id)
            self._add_node(
                graph,
                endpoint_node_id,
                "endpoint",
                endpoint.hostname,
                endpoint_id=endpoint.id,
                device_id=endpoint.device_id,
                ip_address=str(endpoint.ip_address),
            )
            self._add_edge(graph, endpoint_node_id, endpoint.device_id, "attached_to")

            if endpoint.vlan_id is not None:
                self._add_edge(
                    graph,
                    endpoint_node_id,
                    _vlan_node_id(endpoint.vlan_id),
                    "member_of_vlan",
                )
            if endpoint.default_gateway is not None:
                self._add_edge(
                    graph,
                    endpoint_node_id,
                    _gateway_node_id(str(endpoint.default_gateway)),
                    "uses_gateway",
                )

        for device in topology.devices:
            for interface in device.interfaces:
                interface_node_id = _interface_node_id(device.id, interface.name)
                if interface.access_vlan is not None:
                    self._add_edge(
                        graph,
                        interface_node_id,
                        _vlan_node_id(interface.access_vlan),
                        "member_of_vlan",
                    )
                for vlan_id in interface.trunk_vlans:
                    self._add_edge(
                        graph,
                        interface_node_id,
                        _vlan_node_id(vlan_id),
                        "carried_over_trunk",
                    )

        for route in topology.routes:
            route_node_id = _route_node_id(route.id)
            self._add_node(
                graph,
                route_node_id,
                "route",
                str(route.destination),
                route_id=route.id,
                destination=str(route.destination),
                next_hop=str(route.next_hop) if route.next_hop else None,
            )
            self._add_edge(graph, route.device_id, route_node_id, "routes_to")
            if route.next_hop is not None:
                self._add_edge(
                    graph,
                    route_node_id,
                    _gateway_node_id(str(route.next_hop)),
                    "uses_gateway",
                )
            if route.outgoing_interface is not None:
                self._add_edge(
                    graph,
                    route_node_id,
                    _interface_node_id(route.device_id, route.outgoing_interface),
                    "depends_on",
                )

        for acl in topology.acls:
            acl_node_id = _acl_node_id(acl.id)
            self._add_node(
                graph,
                acl_node_id,
                "acl",
                acl.name,
                acl_id=acl.id,
                acl_type=acl.type,
            )
            if acl.device_id is not None:
                self._add_edge(graph, acl.device_id, acl_node_id, "protected_by_acl")
            self._connect_acl_targets(graph, acl, vlan_by_id, endpoint_by_id)

        for service in topology.services:
            service_node_id = _service_node_id(service.id)
            self._add_node(
                graph,
                service_node_id,
                "service",
                service.name,
                service_id=service.id,
                kind=service.kind,
                critical=service.critical,
            )
            if service.endpoint_id is not None:
                self._add_edge(graph, _endpoint_node_id(service.endpoint_id), service_node_id, "depends_on")
            if service.device_id is not None:
                self._add_edge(graph, service.device_id, service_node_id, "depends_on")
            if service.vlan_id is not None:
                self._add_edge(graph, _vlan_node_id(service.vlan_id), service_node_id, "depends_on")
            if service.subnet_id is not None:
                subnet = next((item for item in topology.subnets if item.id == service.subnet_id), None)
                if subnet is not None:
                    self._add_edge(graph, _subnet_node_id(str(subnet.network)), service_node_id, "depends_on")

        return graph

    def build_from_discovered_state(self, discovered_state: DiscoveredNetworkState) -> nx.MultiDiGraph:
        graph = nx.MultiDiGraph(name=discovered_state.project_name, source="discovered")

        for snapshot in discovered_state.device_snapshots:
            device_state = snapshot.discovered_state
            self._add_node(
                graph,
                device_state.device_id,
                "device",
                device_state.hostname,
                platform=device_state.platform,
                console=device_state.console.model_dump(),
            )

            for interface in device_state.interfaces:
                interface_node_id = _interface_node_id(device_state.device_id, interface.name)
                self._add_node(
                    graph,
                    interface_node_id,
                    "interface",
                    interface.name,
                    device_id=device_state.device_id,
                    ip_address=interface.ip_address,
                    status=interface.status,
                    protocol=interface.protocol,
                )
                self._add_edge(graph, device_state.device_id, interface_node_id, "attached_to")

            for vlan in device_state.vlans:
                vlan_node_id = _vlan_node_id(vlan.vlan_id)
                self._add_node(
                    graph,
                    vlan_node_id,
                    "vlan",
                    f"VLAN {vlan.vlan_id}",
                    vlan_id=vlan.vlan_id,
                    status=vlan.status,
                    name=vlan.name,
                )
                for interface_name in vlan.interfaces:
                    self._add_edge(
                        graph,
                        _interface_node_id(device_state.device_id, interface_name),
                        vlan_node_id,
                        "member_of_vlan",
                    )

            for trunk in device_state.trunk_vlans:
                interface_node_id = _interface_node_id(device_state.device_id, trunk.interface_name)
                for vlan_id in trunk.allowed_vlans:
                    vlan_node_id = _vlan_node_id(vlan_id)
                    if not graph.has_node(vlan_node_id):
                        self._add_node(
                            graph,
                            vlan_node_id,
                            "vlan",
                            f"VLAN {vlan_id}",
                            vlan_id=vlan_id,
                        )
                    self._add_edge(graph, interface_node_id, vlan_node_id, "carried_over_trunk")

            for route in device_state.routes:
                route_node_id = _route_node_id(f"{device_state.device_id}:{route.network}")
                self._add_node(
                    graph,
                    route_node_id,
                    "route",
                    route.network,
                    code=route.code,
                    next_hop=route.next_hop,
                )
                self._add_edge(graph, device_state.device_id, route_node_id, "routes_to")
                if route.next_hop is not None:
                    gateway_node_id = _gateway_node_id(route.next_hop)
                    self._add_node(graph, gateway_node_id, "gateway", route.next_hop, address=route.next_hop)
                    self._add_edge(graph, route_node_id, gateway_node_id, "uses_gateway")
                if route.outgoing_interface is not None:
                    self._add_edge(
                        graph,
                        route_node_id,
                        _interface_node_id(device_state.device_id, route.outgoing_interface),
                        "depends_on",
                    )

            for acl in device_state.acls:
                acl_node_id = _acl_node_id(f"{device_state.device_id}:{acl.name}")
                self._add_node(
                    graph,
                    acl_node_id,
                    "acl",
                    acl.name,
                    acl_type=acl.acl_type,
                    entry_count=len(acl.entries),
                )
                self._add_edge(graph, device_state.device_id, acl_node_id, "protected_by_acl")

        return graph

    def get_view(self, graph: nx.MultiDiGraph, view_type: GraphViewType) -> nx.MultiDiGraph:
        edge_types_by_view = {
            "physical": {"physically_connected", "attached_to"},
            "layer2": {"attached_to", "member_of_vlan", "carried_over_trunk"},
            "layer3": {"uses_gateway", "routes_to", "depends_on", "attached_to"},
            "dependency": {"depends_on", "uses_gateway", "protected_by_acl", "member_of_vlan", "carried_over_trunk"},
            "service": {"depends_on", "uses_gateway", "routes_to", "member_of_vlan"},
        }
        allowed = edge_types_by_view[view_type]
        view = nx.MultiDiGraph(name=f"{graph.graph.get('name', 'graph')}:{view_type}")

        for node_id, data in graph.nodes(data=True):
            view.add_node(node_id, **data)

        for source, target, key, data in graph.edges(keys=True, data=True):
            if data.get("edge_type") in allowed:
                view.add_edge(source, target, key=key, **data)

        self._remove_isolated_nodes(view)
        return view

    def endpoints_in_vlan(self, graph: nx.MultiDiGraph, vlan_id: int) -> list[str]:
        vlan_node_id = _vlan_node_id(vlan_id)
        endpoints = [
            node_id
            for node_id, _, data in graph.in_edges(vlan_node_id, data=True)
            if data.get("edge_type") == "member_of_vlan" and graph.nodes[node_id].get("node_type") == "endpoint"
        ]
        return sorted(endpoints)

    def vlans_using_trunk(self, graph: nx.MultiDiGraph, interface_node_id: str) -> list[str]:
        vlans = [
            target
            for _, target, data in graph.out_edges(interface_node_id, data=True)
            if data.get("edge_type") == "carried_over_trunk"
        ]
        return sorted(vlans)

    def devices_depending_on_interface(self, graph: nx.MultiDiGraph, interface_node_id: str) -> list[str]:
        undirected = graph.to_undirected()
        component = nx.node_connected_component(undirected, interface_node_id)
        return sorted(
            node_id
            for node_id in component
            if graph.nodes[node_id].get("node_type") == "device"
        )

    def path_from_endpoint_to_gateway(
        self,
        graph: nx.MultiDiGraph,
        endpoint_node_id: str,
        gateway_node_id: str,
    ) -> list[str]:
        return nx.shortest_path(graph.to_undirected(), endpoint_node_id, gateway_node_id)

    def path_from_endpoint_to_service(
        self,
        graph: nx.MultiDiGraph,
        endpoint_node_id: str,
        service_node_id: str,
    ) -> list[str]:
        return nx.shortest_path(graph.to_undirected(), endpoint_node_id, service_node_id)

    def disconnected_components_after_removal(
        self,
        graph: nx.MultiDiGraph,
        *,
        node_id: str | None = None,
        edge: tuple[str, str] | None = None,
    ) -> list[list[str]]:
        mutated = graph.copy()
        if node_id is not None and mutated.has_node(node_id):
            mutated.remove_node(node_id)
        if edge is not None and mutated.has_edge(edge[0], edge[1]):
            mutated.remove_edges_from(list(mutated.edges(edge[0], edge[1], keys=True)))
        undirected = mutated.to_undirected()
        return [sorted(component) for component in nx.connected_components(undirected)]

    def transitive_dependencies(self, graph: nx.MultiDiGraph, node_id: str) -> list[str]:
        descendants = nx.descendants(graph, node_id)
        return sorted(descendants)

    def to_records(self, graph: nx.MultiDiGraph) -> tuple[list[GraphNodeRecord], list[GraphEdgeRecord]]:
        nodes = [
            GraphNodeRecord(
                id=node_id,
                node_type=data["node_type"],
                label=data["label"],
                attributes={key: value for key, value in data.items() if key not in {"node_type", "label"}},
            )
            for node_id, data in graph.nodes(data=True)
        ]
        edges = [
            GraphEdgeRecord(
                source=source,
                target=target,
                edge_type=data["edge_type"],
                attributes={key: value for key, value in data.items() if key != "edge_type"},
            )
            for source, target, data in graph.edges(data=True)
        ]
        return nodes, edges

    def to_react_flow(self, graph: nx.MultiDiGraph) -> ReactFlowGraph:
        grouped_by_type: dict[str, list[str]] = defaultdict(list)
        for node_id, data in graph.nodes(data=True):
            grouped_by_type[data["node_type"]].append(node_id)

        nodes: list[ReactFlowNode] = []
        for node_type, node_ids in grouped_by_type.items():
            for index, node_id in enumerate(sorted(node_ids)):
                data = graph.nodes[node_id]
                nodes.append(
                    ReactFlowNode(
                        id=node_id,
                        position={
                            "x": float(index * 240),
                            "y": self._layout_y_by_type.get(node_type, 1080.0),
                        },
                        data={
                            "label": data["label"],
                            "node_type": data["node_type"],
                            **{
                                key: value
                                for key, value in data.items()
                                if key not in {"label", "node_type"}
                            },
                        },
                    ),
                )

        edges: list[ReactFlowEdge] = []
        for source, target, key, data in graph.edges(keys=True, data=True):
            edges.append(
                ReactFlowEdge(
                    id=f"{source}->{target}:{key}",
                    source=source,
                    target=target,
                    label=data["edge_type"],
                    data={key: value for key, value in data.items()},
                ),
            )

        return ReactFlowGraph(nodes=nodes, edges=edges)

    def _add_device(self, graph: nx.MultiDiGraph, device: Device) -> None:
        self._add_node(
            graph,
            device.id,
            "device",
            device.hostname,
            device_type=device.type,
            platform=device.platform,
            site_id=device.site_id,
        )

    def _connect_acl_targets(
        self,
        graph: nx.MultiDiGraph,
        acl: ACL,
        vlan_by_id: dict[int, VLAN],
        endpoint_by_id: dict[str, Endpoint],
    ) -> None:
        for rule in acl.rules:
            source_vlan = _match_vlan_for_selector(rule.source, vlan_by_id)
            if source_vlan is not None:
                self._add_edge(graph, _vlan_node_id(source_vlan.vlan_id), _acl_node_id(acl.id), "protected_by_acl")
            destination_vlan = _match_vlan_for_selector(rule.destination, vlan_by_id)
            if destination_vlan is not None:
                self._add_edge(graph, _acl_node_id(acl.id), _vlan_node_id(destination_vlan.vlan_id), "protected_by_acl")
            source_endpoint = _match_endpoint_for_selector(rule.source, endpoint_by_id)
            if source_endpoint is not None:
                self._add_edge(graph, _endpoint_node_id(source_endpoint.id), _acl_node_id(acl.id), "protected_by_acl")
            destination_endpoint = _match_endpoint_for_selector(rule.destination, endpoint_by_id)
            if destination_endpoint is not None:
                self._add_edge(graph, _acl_node_id(acl.id), _endpoint_node_id(destination_endpoint.id), "protected_by_acl")

    @staticmethod
    def _add_node(
        graph: nx.MultiDiGraph,
        node_id: str,
        node_type: str,
        label: str,
        **attributes: Any,
    ) -> None:
        graph.add_node(node_id, node_type=node_type, label=label, **attributes)

    @staticmethod
    def _add_edge(
        graph: nx.MultiDiGraph,
        source: str,
        target: str,
        edge_type: str,
        **attributes: Any,
    ) -> None:
        graph.add_edge(source, target, edge_type=edge_type, **attributes)

    @staticmethod
    def _remove_isolated_nodes(graph: nx.MultiDiGraph) -> None:
        isolated = [node_id for node_id in graph.nodes if graph.degree(node_id) == 0]
        graph.remove_nodes_from(isolated)


def _interface_node_id(device_id: str, interface_name: str) -> str:
    return f"interface:{device_id}:{interface_name}"


def _vlan_node_id(vlan_id: int) -> str:
    return f"vlan:{vlan_id}"


def _subnet_node_id(network: str) -> str:
    return f"subnet:{network}"


def _endpoint_node_id(endpoint_id: str) -> str:
    return f"endpoint:{endpoint_id}"


def _gateway_node_id(address: str) -> str:
    return f"gateway:{address}"


def _route_node_id(route_id: str) -> str:
    return f"route:{route_id}"


def _acl_node_id(acl_id: str) -> str:
    return f"acl:{acl_id}"


def _service_node_id(service_id: str) -> str:
    return f"service:{service_id}"


def _match_vlan_for_selector(selector: str, vlans: dict[int, VLAN]) -> VLAN | None:
    if selector == "any":
        return None
    if selector.startswith("host "):
        address = IPv4Address(selector.removeprefix("host ").strip())
        return next((vlan for vlan in vlans.values() if vlan.subnet and address in vlan.subnet), None)

    try:
        network = IPv4Network(selector, strict=False)
    except ValueError:
        return None
    return next((vlan for vlan in vlans.values() if vlan.subnet == network), None)


def _match_endpoint_for_selector(selector: str, endpoints: dict[str, Endpoint]) -> Endpoint | None:
    if not selector.startswith("host "):
        return None
    address = IPv4Address(selector.removeprefix("host ").strip())
    return next((endpoint for endpoint in endpoints.values() if endpoint.ip_address == address), None)
