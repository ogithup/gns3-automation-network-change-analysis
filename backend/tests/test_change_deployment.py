"""Sprint 12 approved change deployment and rollback tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.changes.models import AddVLANToTrunkCommand, RemoveVLANFromTrunkCommand
from app.discovery.service import DiscoveryService
from app.gns3.models import GNS3ConsoleInfo
from app.risk.service import RiskScoringService
from app.rollback.models import ApprovalRecord
from app.rollback.service import ChangeDeploymentService
from app.simulation.service import SimulationService
from app.topology.service import TopologyService


def _load(name: str):
    return TopologyService.load_file(Path("..") / "examples" / name)


class StatefulMockChannel:
    def __init__(self, device_id: str, state: dict[str, object]) -> None:
        self.device_id = device_id
        self.state = state
        self.last_command = ""
        self.mode = "user"

    async def open(self) -> None:
        return None

    async def write_line(self, line: str) -> None:
        self.last_command = line

    async def read_until_idle(self, *, idle_timeout: float = 0.25, max_wait: float = 10.0) -> str:
        _ = (idle_timeout, max_wait)
        command = self.last_command.strip()
        if self.device_id in {"admin-pc", "student-pc", "guest-pc"}:
            return self._vpcs_output(command)
        return self._cisco_output(command)

    async def close(self) -> None:
        return None

    def _cisco_output(self, command: str) -> str:
        prompts = {
            "user": "Router>",
            "privileged": "Router#",
            "config": "Router(config)#",
        }
        if self.device_id == "sw1":
            prompts = {
                "user": "SW1>",
                "privileged": "SW1#",
                "config": "SW1(config)#",
            }

        if command == "":
            return f"{prompts[self.mode]}\n"
        if command == "enable":
            self.mode = "privileged"
            return f"{prompts[self.mode]}\n"
        if command == "terminal length 0":
            return f"{prompts[self.mode]}\n"
        if command == "configure terminal":
            self.mode = "config"
            return f"{prompts[self.mode]}\n"
        if command == "end":
            self.mode = "privileged"
            return f"{prompts[self.mode]}\n"
        if command == "write memory":
            return f"Building configuration...\n[OK]\n{prompts[self.mode]}\n"

        if self.device_id == "sw1" and self.mode == "config":
            if command == "interface GigabitEthernet0/1":
                return f"SW1(config-if)#\n"
            if command == "switchport trunk allowed vlan remove 20":
                self.state["allow_vlan20"] = False
                return "SW1(config-if)#\n"
            if command == "switchport trunk allowed vlan add 20":
                self.state["allow_vlan20"] = True
                return "SW1(config-if)#\n"

        if command == "show running-config":
            return self._running_config() + f"\n{prompts[self.mode]}\n"
        if command == "show ip interface brief":
            return self._ip_interface_brief() + f"\n{prompts[self.mode]}\n"
        if command == "show ip route":
            return self._ip_route() + f"\n{prompts[self.mode]}\n"
        if command == "show access-lists":
            return f"{prompts[self.mode]}\n"
        if command == "show ip ospf neighbor":
            return f"{prompts[self.mode]}\n"
        if command == "show vlan brief":
            return self._vlan_brief() + f"\n{prompts[self.mode]}\n"
        if command == "show interfaces trunk":
            return self._interfaces_trunk() + f"\n{prompts[self.mode]}\n"
        return f"{prompts[self.mode]}\n"

    def _vpcs_output(self, command: str) -> str:
        if command == "":
            return f"{self._vpcs_prompt()}\n"
        if command == "show":
            if self.device_id == "admin-pc":
                return (
                    "NAME   IP/MASK              GATEWAY\n"
                    "PC1    192.168.10.10/24     192.168.10.1\n"
                    f"{self._vpcs_prompt()}\n"
                )
            if self.device_id == "guest-pc":
                return (
                    "NAME   IP/MASK              GATEWAY\n"
                    "PC3    192.168.30.10/24     192.168.30.1\n"
                    f"{self._vpcs_prompt()}\n"
                )
            return (
                "NAME   IP/MASK              GATEWAY\n"
                "PC2    192.168.20.10/24     192.168.20.1\n"
                f"{self._vpcs_prompt()}\n"
            )
        if command == "ping 192.168.20.10":
            if self.state["allow_vlan20"]:
                return "84 bytes from 192.168.20.10 icmp_seq=1 ttl=64 time=1 ms\nPC1>\n"
            return "host (192.168.10.1) not reachable\nPC1>\n"
        if command == "ping 192.168.10.10":
            if self.device_id == "guest-pc":
                return "host (192.168.30.1) not reachable\nPC3>\n"
            if self.state["allow_vlan20"]:
                return "84 bytes from 192.168.10.10 icmp_seq=1 ttl=64 time=1 ms\nPC2>\n"
            return "host (192.168.20.1) not reachable\nPC2>\n"
        return f"{self._vpcs_prompt()}\n"

    def _vpcs_prompt(self) -> str:
        mapping = {
            "admin-pc": "PC1>",
            "student-pc": "PC2>",
            "guest-pc": "PC3>",
        }
        return mapping[self.device_id]

    def _running_config(self) -> str:
        if self.device_id == "r1":
            return (
                "hostname R1\n"
                "interface GigabitEthernet0/0\n"
                " no shutdown\n"
                "interface GigabitEthernet0/0.10\n"
                " encapsulation dot1Q 10\n"
                " ip address 192.168.10.1 255.255.255.0\n"
                "interface GigabitEthernet0/0.20\n"
                " encapsulation dot1Q 20\n"
                " ip address 192.168.20.1 255.255.255.0"
            )
        allowed = "10,20" if self.state["allow_vlan20"] else "10"
        return (
            "hostname SW1\n"
            "vlan 10\n"
            " name VLAN10\n"
            "vlan 20\n"
            " name VLAN20\n"
            "interface GigabitEthernet0/1\n"
            " switchport mode trunk\n"
            f" switchport trunk allowed vlan {allowed}\n"
            "interface GigabitEthernet0/2\n"
            " switchport mode access\n"
            " switchport access vlan 10\n"
            "interface GigabitEthernet0/3\n"
            " switchport mode access\n"
            " switchport access vlan 20"
        )

    def _ip_interface_brief(self) -> str:
        if self.device_id == "r1":
            return (
                "Interface                  IP-Address      OK? Method Status                Protocol\n"
                "GigabitEthernet0/0         unassigned      YES unset  up                    up\n"
                "GigabitEthernet0/0.10      192.168.10.1    YES manual up                    up\n"
                "GigabitEthernet0/0.20      192.168.20.1    YES manual up                    up"
            )
        return (
            "Interface                  IP-Address      OK? Method Status                Protocol\n"
            "GigabitEthernet0/1         unassigned      YES unset  up                    up\n"
            "GigabitEthernet0/2         unassigned      YES unset  up                    up\n"
            "GigabitEthernet0/3         unassigned      YES unset  up                    up"
        )

    def _ip_route(self) -> str:
        if not self.state["allow_vlan20"]:
            return (
                "Codes: C - connected\n"
                "C    192.168.10.0/24 is directly connected, GigabitEthernet0/0.10"
            )
        return (
            "Codes: C - connected\n"
            "C    192.168.10.0/24 is directly connected, GigabitEthernet0/0.10\n"
            "C    192.168.20.0/24 is directly connected, GigabitEthernet0/0.20"
        )

    def _vlan_brief(self) -> str:
        return (
            "VLAN Name                             Status    Ports\n"
            "1    default                          active\n"
            "10   VLAN10                           active    Gi0/2\n"
            "20   VLAN20                           active    Gi0/3"
        )

    def _interfaces_trunk(self) -> str:
        allowed = "10,20" if self.state["allow_vlan20"] else "10"
        return (
            "Port        Mode             Encapsulation  Status        Native vlan\n"
            "Gi0/1       on               802.1q         trunking      1\n\n"
            "Port        Vlans allowed on trunk\n"
            f"Gi0/1       {allowed}"
        )


class MockGNS3Client:
    async def get_node_console(self, project_id: str, node_id: str) -> GNS3ConsoleInfo:
        return GNS3ConsoleInfo(
            node_id=node_id,
            console_host="localhost",
            console=5000,
            console_type="telnet",
        )


@pytest.mark.asyncio
async def test_change_deployment_completes_when_runtime_matches_prediction() -> None:
    topology = _load("three-vlan-office.yaml")
    topology.connectivity_requirements = [
        requirement
        for requirement in topology.connectivity_requirements
        if requirement.id == "admin-to-student"
    ]
    topology.validation_tests = [
        test
        for test in topology.validation_tests
        if test.id == "test-admin-student"
    ]
    switch = next(device for device in topology.devices if device.id == "sw1")
    trunk = next(interface for interface in switch.interfaces if interface.name == "GigabitEthernet0/1")
    trunk.trunk_vlans = [10, 30]
    simulation = await SimulationService().simulate_change(
        topology,
        AddVLANToTrunkCommand(device="sw1", interface="GigabitEthernet0/1", vlan_id=20),
    )
    risk = RiskScoringService().assess_change(topology, simulation)
    shared_state = {"allow_vlan20": False}

    async def channel_factory(console_info: GNS3ConsoleInfo):
        return StatefulMockChannel(console_info.node_id, shared_state)

    discovery_service = DiscoveryService(
        gns3_client=MockGNS3Client(),
        channel_factory=channel_factory,
    )
    before_state = await discovery_service.discover_project_state(
        project_id="project-12",
        project_name="sprint12-validation",
        topology=topology,
        console_infos={
            device.id: GNS3ConsoleInfo(
                node_id=device.id,
                console_host="localhost",
                console=5000,
                console_type="telnet",
            )
            for device in topology.devices
        },
    )
    service = ChangeDeploymentService(
        gns3_client=MockGNS3Client(),
        discovery_service=discovery_service,
    )

    result = await service.execute_change(
        topology=topology,
        discovered_state=before_state,
        simulation_result=simulation,
        risk_assessment=risk,
        command=AddVLANToTrunkCommand(device="sw1", interface="GigabitEthernet0/1", vlan_id=20),
        approval=ApprovalRecord(approved=True, reviewer="tester"),
    )

    assert result.state == "Completed"
    assert result.rollback_executed is False
    assert any(plan.device_id == "sw1" for plan in result.command_plans)
    assert any(item.command == "switchport trunk allowed vlan add 20" for item in result.command_outputs)


@pytest.mark.asyncio
async def test_change_deployment_rolls_back_on_runtime_mismatch() -> None:
    topology = _load("three-vlan-office.yaml")
    simulation = await SimulationService().simulate_change(
        topology,
        RemoveVLANFromTrunkCommand(device="sw1", interface="GigabitEthernet0/1", vlan_id=20),
    )
    risk = RiskScoringService().assess_change(topology, simulation)
    shared_state = {"allow_vlan20": True, "fail_ping_after_change": True}

    class MismatchChannel(StatefulMockChannel):
        def _vpcs_output(self, command: str) -> str:
            if (
                self.device_id == "admin-pc"
                and command == "ping 192.168.20.10"
                and self.state["allow_vlan20"] is False
                and self.state.get("fail_ping_after_change")
            ):
                return "84 bytes from 192.168.20.10 icmp_seq=1 ttl=64 time=1 ms\nPC1>\n"
            return super()._vpcs_output(command)

    async def channel_factory(console_info: GNS3ConsoleInfo):
        return MismatchChannel(console_info.node_id, shared_state)

    discovery_service = DiscoveryService(
        gns3_client=MockGNS3Client(),
        channel_factory=channel_factory,
    )
    before_state = await discovery_service.discover_project_state(
        project_id="project-12",
        project_name="sprint12-validation",
        topology=topology,
        console_infos={
            device.id: GNS3ConsoleInfo(
                node_id=device.id,
                console_host="localhost",
                console=5000,
                console_type="telnet",
            )
            for device in topology.devices
        },
    )
    service = ChangeDeploymentService(
        gns3_client=MockGNS3Client(),
        discovery_service=discovery_service,
    )

    result = await service.execute_change(
        topology=topology,
        discovered_state=before_state,
        simulation_result=simulation,
        risk_assessment=risk,
        command=RemoveVLANFromTrunkCommand(device="sw1", interface="GigabitEthernet0/1", vlan_id=20),
        approval=ApprovalRecord(approved=True, reviewer="tester"),
    )

    assert result.state == "RolledBack"
    assert result.rollback_executed is True
    assert result.rollback_strategy_used == "inverse_commands"
    assert any(item.command == "switchport trunk allowed vlan add 20" for item in result.command_outputs)
