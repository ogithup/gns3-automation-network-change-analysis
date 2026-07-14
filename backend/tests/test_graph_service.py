"""Sprint 7 graph engine tests."""

from __future__ import annotations

from pathlib import Path

from app.discovery.models import (
    DeviceStateSnapshot,
    DiscoveredACL,
    DiscoveredDeviceState,
    DiscoveredNetworkState,
    DiscoveredRoute,
    DiscoveredTrunk,
    DiscoveredVLAN,
    InterfaceOperationalState,
)
from app.gns3.models import GNS3ConsoleInfo
from app.graph.service import GraphService
from app.topology.service import TopologyService


def test_graph_service_builds_desired_graph_and_queries() -> None:
    topology = TopologyService.load_file(Path("..") / "examples" / "three-vlan-office.yaml")
    service = GraphService()

    graph = service.build_from_topology(topology)
    layer2 = service.get_view(graph, "layer2")
    dependency = service.get_view(graph, "dependency")

    endpoints = service.endpoints_in_vlan(graph, 30)
    trunk_vlans = service.vlans_using_trunk(graph, "interface:sw1:GigabitEthernet0/1")
    interface_dependents = service.devices_depending_on_interface(graph, "interface:sw1:GigabitEthernet0/1")
    gateway_path = service.path_from_endpoint_to_gateway(
        graph,
        "endpoint:guest-endpoint",
        "gateway:192.168.30.1",
    )
    service_path = service.path_from_endpoint_to_service(
        graph,
        "endpoint:guest-endpoint",
        "service:guest-dhcp-service",
    )
    components_after_removal = service.disconnected_components_after_removal(
        graph,
        node_id="interface:sw1:GigabitEthernet0/1",
    )
    dependencies = service.transitive_dependencies(graph, "endpoint:guest-endpoint")
    react_flow = service.to_react_flow(layer2)

    assert graph.nodes["r1"]["node_type"] == "device"
    assert "endpoint:guest-endpoint" in endpoints
    assert trunk_vlans == ["vlan:10", "vlan:20", "vlan:30"]
    assert "sw1" in interface_dependents
    assert gateway_path[-1] == "gateway:192.168.30.1"
    assert service_path[-1] == "service:guest-dhcp-service"
    assert any("endpoint:guest-endpoint" in component for component in components_after_removal)
    assert "service:guest-dhcp-service" in dependencies
    assert len(react_flow.nodes) > 0
    assert len(react_flow.edges) > 0
    assert dependency.number_of_nodes() > 0


def test_graph_service_builds_discovered_graph() -> None:
    discovered = DiscoveredNetworkState(
        project_id="proj-7",
        project_name="discovered-demo",
        device_snapshots=[
            DeviceStateSnapshot(
                device_id="r1",
                desired_configuration="hostname R1",
                desired_configuration_hash="hash",
                discovered_state=DiscoveredDeviceState(
                    device_id="r1",
                    hostname="R1",
                    platform="iosv",
                    console=GNS3ConsoleInfo(
                        node_id="node-r1",
                        console_host="localhost",
                        console=5000,
                        console_type="telnet",
                    ),
                    interfaces=[
                        InterfaceOperationalState(
                            name="GigabitEthernet0/0",
                            ip_address="10.0.0.1",
                            status="up",
                            protocol="up",
                        ),
                    ],
                    vlans=[
                        DiscoveredVLAN(vlan_id=10, name="ADMIN", status="active", interfaces=["GigabitEthernet0/0"]),
                    ],
                    trunk_vlans=[
                        DiscoveredTrunk(interface_name="GigabitEthernet0/0", allowed_vlans=[10, 20]),
                    ],
                    routes=[
                        DiscoveredRoute(code="C", network="10.0.0.0/30", outgoing_interface="GigabitEthernet0/0"),
                    ],
                    acls=[
                        DiscoveredACL(name="guest-to-admin", acl_type="extended", entries=["10 deny ip any any"]),
                    ],
                ),
            ),
        ],
    )
    service = GraphService()

    graph = service.build_from_discovered_state(discovered)
    records = service.to_records(graph)
    service_view = service.get_view(graph, "service")

    assert graph.nodes["r1"]["node_type"] == "device"
    assert "interface:r1:GigabitEthernet0/0" in graph.nodes
    assert "vlan:10" in graph.nodes
    assert len(records[0]) > 0
    assert len(records[1]) > 0
    assert isinstance(service_view.number_of_nodes(), int)
