"""Sprint 13 root cause analysis tests."""

from __future__ import annotations

from pathlib import Path
from ipaddress import IPv4Address

from app.discovery.models import (
    DeviceStateSnapshot,
    DiscoveredACL,
    DiscoveredDeviceState,
    DiscoveredNetworkState,
    DiscoveredOSPFNeighbor,
    DiscoveredRoute,
    DiscoveredTrunk,
    DiscoveredVLAN,
    InterfaceOperationalState,
)
from app.gns3.models import GNS3ConsoleInfo
from app.impact.service import RootCauseAnalysisService
from app.topology.service import TopologyService


def _load(name: str):
    return TopologyService.load_file(Path("..") / "examples" / name)


def _state_for(
    topology,
    *,
    wrong_access_vlan: bool = False,
    missing_trunk_vlan: bool = False,
    shutdown_subinterface: bool = False,
    missing_route: bool = False,
    ospf_failure: bool = False,
    acl_deny: bool = False,
) -> DiscoveredNetworkState:
    snapshots = []
    for device in topology.devices:
        interfaces = []
        vlans = []
        trunks = []
        routes = []
        acls = []
        ospf_neighbors = []
        for interface in device.interfaces:
            status = "administratively down" if shutdown_subinterface and interface.name.endswith(".20") else "up"
            protocol = "down" if status != "up" else "up"
            interfaces.append(
                InterfaceOperationalState(
                    name=interface.name,
                    ip_address=str(interface.ipv4_address.ip) if interface.ipv4_address else None,
                    status=status,
                    protocol=protocol,
                ),
            )
        if device.id == "sw1":
            vlans = [
                DiscoveredVLAN(vlan_id=10, name="ADMIN", status="active", interfaces=["GigabitEthernet0/3"] if wrong_access_vlan else ["GigabitEthernet0/2"]),
                DiscoveredVLAN(vlan_id=20, name="STUDENT", status="active", interfaces=["GigabitEthernet0/2"] if wrong_access_vlan else ["GigabitEthernet0/3"]),
            ]
            trunks = [
                DiscoveredTrunk(
                    interface_name="GigabitEthernet0/1",
                    allowed_vlans=[10, 30] if missing_trunk_vlan else [10, 20, 30],
                ),
            ]
        if device.id == "r1":
            if not missing_route:
                routes = [
                    DiscoveredRoute(code="C", network="192.168.10.0/24", outgoing_interface="GigabitEthernet0/0.10"),
                    DiscoveredRoute(code="C", network="192.168.20.0/24", outgoing_interface="GigabitEthernet0/0.20"),
                ]
            else:
                routes = [DiscoveredRoute(code="C", network="192.168.10.0/24", outgoing_interface="GigabitEthernet0/0.10")]
            if acl_deny:
                acls = [
                    DiscoveredACL(
                        name="deny-admin-student",
                        acl_type="extended",
                        entries=["deny ip 192.168.10.10 192.168.20.10"],
                    ),
                ]
            if any(protocol.device_id == device.id for protocol in topology.routing_protocols) and not ospf_failure:
                ospf_neighbors = [
                    DiscoveredOSPFNeighbor(
                        neighbor_id="2.2.2.2",
                        address="10.0.0.2",
                        state="FULL/DR",
                        interface_name=device.interfaces[0].name,
                    ),
                ]
        snapshots.append(
            DeviceStateSnapshot(
                device_id=device.id,
                discovered_state=DiscoveredDeviceState(
                    device_id=device.id,
                    hostname=device.hostname,
                    platform=device.platform,
                    console=GNS3ConsoleInfo(node_id=device.id, console_host="localhost", console=5000, console_type="telnet"),
                    running_config=f"hostname {device.hostname}",
                    interfaces=interfaces,
                    vlans=vlans,
                    trunk_vlans=trunks,
                    routes=routes,
                    acls=acls,
                    ospf_neighbors=ospf_neighbors,
                    raw_outputs={},
                ),
            ),
        )
    return DiscoveredNetworkState(project_id="rca", project_name="rca", device_snapshots=snapshots)


def test_root_cause_detects_wrong_access_vlan() -> None:
    topology = _load("three-vlan-office.yaml")
    state = _state_for(topology, wrong_access_vlan=True)
    result = RootCauseAnalysisService().analyze_connectivity_failure(
        topology=topology,
        discovered_state=state,
        source_endpoint_id="admin-endpoint",
        target_endpoint_id="student-endpoint",
    )
    assert "wrong access VLAN" in result.findings[0].suspected_root_cause


def test_root_cause_detects_missing_trunk_vlan() -> None:
    topology = _load("three-vlan-office.yaml")
    state = _state_for(topology, missing_trunk_vlan=True)
    result = RootCauseAnalysisService().analyze_connectivity_failure(
        topology=topology,
        discovered_state=state,
        source_endpoint_id="admin-endpoint",
        target_endpoint_id="student-endpoint",
    )
    assert "does not carry VLAN 20" in result.findings[0].suspected_root_cause


def test_root_cause_detects_shutdown_subinterface() -> None:
    topology = _load("three-vlan-office.yaml")
    state = _state_for(topology, shutdown_subinterface=True)
    result = RootCauseAnalysisService().analyze_connectivity_failure(
        topology=topology,
        discovered_state=state,
        source_endpoint_id="admin-endpoint",
        target_endpoint_id="student-endpoint",
    )
    assert "shutdown" in result.findings[0].suspected_root_cause


def test_root_cause_detects_missing_static_route() -> None:
    topology = _load("two-router-ospf.yaml")
    state = _state_for(topology, missing_route=True)
    result = RootCauseAnalysisService().analyze_connectivity_failure(
        topology=topology,
        discovered_state=state,
        source_endpoint_id="branch-a-endpoint",
        target_endpoint_id="branch-b-endpoint",
    )
    assert "missing a route" in result.findings[0].suspected_root_cause


def test_root_cause_detects_ospf_failure() -> None:
    topology = _load("two-router-ospf.yaml")
    state = _state_for(topology, missing_route=True, ospf_failure=True)
    result = RootCauseAnalysisService().analyze_connectivity_failure(
        topology=topology,
        discovered_state=state,
        source_endpoint_id="branch-a-endpoint",
        target_endpoint_id="branch-b-endpoint",
    )
    assert "OSPF neighbor" in result.findings[0].suspected_root_cause


def test_root_cause_detects_acl_deny() -> None:
    topology = _load("three-vlan-office.yaml")
    state = _state_for(topology, acl_deny=True)
    result = RootCauseAnalysisService().analyze_connectivity_failure(
        topology=topology,
        discovered_state=state,
        source_endpoint_id="admin-endpoint",
        target_endpoint_id="student-endpoint",
    )
    assert "ACL" in result.findings[0].suspected_root_cause


def test_root_cause_detects_invalid_gateway() -> None:
    topology = _load("three-vlan-office.yaml")
    topology.endpoints[0].default_gateway = IPv4Address("10.10.10.1")
    state = _state_for(topology)
    result = RootCauseAnalysisService().analyze_connectivity_failure(
        topology=topology,
        discovered_state=state,
        source_endpoint_id="admin-endpoint",
        target_endpoint_id="student-endpoint",
    )
    assert "invalid gateway" in result.findings[0].suspected_root_cause
