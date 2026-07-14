"""Simulated console tests for Sprint 6 discovery workflows."""

from __future__ import annotations

from collections import deque

import pytest

from app.configuration.models import ConfigurationPreview, RenderedConfiguration
from app.discovery.console import PromptDetector
from app.discovery.models import DiscoveredNetworkState
from app.discovery.service import DiscoveryService
from app.domain.models import TopologySpec
from app.gns3.models import (
    GNS3ConsoleInfo,
    GNS3DeploymentResult,
    GNS3DomainNodeMapping,
    GNS3Project,
)


class _FakeGNS3Client:
    def __init__(self, console_by_node_id: dict[str, GNS3ConsoleInfo]) -> None:
        self.console_by_node_id = console_by_node_id

    async def get_node_console(self, project_id: str, node_id: str) -> GNS3ConsoleInfo:
        return self.console_by_node_id[node_id]


class _FakeConsoleChannel:
    def __init__(self, initial_output: str, responses: dict[str, str]) -> None:
        self.initial_output = initial_output
        self.responses = responses
        self.commands: list[str] = []
        self._queue: deque[str] = deque()
        self._bootstrap_pending = True

    async def open(self) -> None:
        self._queue.append(self.initial_output)

    async def write_line(self, line: str) -> None:
        self.commands.append(line)
        if self._bootstrap_pending and line == "":
            self._bootstrap_pending = False
            return
        self._queue.append(self.responses.get(line, ""))

    async def read_until_idle(
        self,
        *,
        idle_timeout: float = 0.25,
        max_wait: float = 10.0,
    ) -> str:
        return self._queue.popleft() if self._queue else ""

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_discovery_service_applies_config_and_collects_state() -> None:
    topology = TopologySpec.model_validate(
        {
            "project": {"name": "sprint6-demo"},
            "devices": [
                {"id": "r1", "hostname": "R1", "type": "router", "platform": "iosv"},
                {"id": "pc1", "hostname": "PC1", "type": "endpoint", "platform": "vpcs"},
            ],
        },
    )
    deployment = GNS3DeploymentResult(
        project=GNS3Project(project_id="proj-6", name="sprint6-demo", status="opened"),
        node_mappings=[
            GNS3DomainNodeMapping(
                domain_device_id="r1",
                gns3_node_id="node-r1",
                template_id="tmpl-iosv",
                name="R1",
            ),
            GNS3DomainNodeMapping(
                domain_device_id="pc1",
                gns3_node_id="node-pc1",
                template_id="tmpl-vpcs",
                name="PC1",
            ),
        ],
        links=[],
        devices={"r1": "node-r1", "pc1": "node-pc1"},
    )
    preview = ConfigurationPreview(
        project_name="sprint6-demo",
        rendered_configurations=[
            RenderedConfiguration(
                device_id="r1",
                hostname="R1",
                platform="iosv",
                template_name="iosv/base.j2",
                content="hostname R1\ninterface GigabitEthernet0/0\n no shutdown\nend\n",
                content_hash="router-hash",
            ),
            RenderedConfiguration(
                device_id="pc1",
                hostname="PC1",
                platform="vpcs",
                template_name="vpcs/ip_config.j2",
                content="set pcname PC1\nip 192.168.10.10 255.255.255.0 192.168.10.1\nsave\n",
                content_hash="pc-hash",
            ),
        ],
    )

    router_channel = _FakeConsoleChannel(
        initial_output="Would you like to enter the initial configuration dialog?",
        responses={
            "": "Router>\n",
            "no": "Press RETURN to get started!\n",
            "enable": "Router#\n",
            "terminal length 0": "Router#\n",
            "configure terminal": "Router(config)#\n",
            "hostname R1": "R1(config)#\n",
            "interface GigabitEthernet0/0": "R1(config-if)#\n",
            "no shutdown": "R1(config-if)#\n",
            "end": "R1#\n",
            "write memory": "Building configuration...\n[OK]\nR1#\n",
            "show running-config": "hostname R1\ninterface GigabitEthernet0/0\n no shutdown\nR1#\n",
            "show ip interface brief": (
                "Interface                  IP-Address      OK? Method Status                Protocol\n"
                "GigabitEthernet0/0         unassigned      YES unset  up                    up\n"
                "R1#\n"
            ),
            "show vlan brief": "R1#\n",
            "show interfaces trunk": "R1#\n",
            "show ip route": "Gateway of last resort is not set\nR1#\n",
            "show access-lists": "R1#\n",
            "show ip ospf neighbor": "R1#\n",
        },
    )
    vpcs_channel = _FakeConsoleChannel(
        initial_output="PC1>",
        responses={
            "": "PC1>\n",
            "set pcname PC1": "PC1>\n",
            "ip 192.168.10.10 255.255.255.0 192.168.10.1": "PC1>\n",
            "save": "PC1>\n",
            "show": "NAME   IP/MASK              GATEWAY\nPC1    192.168.10.10/24     192.168.10.1\nPC1>\n",
        },
    )

    async def channel_factory(console_info: GNS3ConsoleInfo):
        if console_info.node_id == "node-r1":
            return router_channel
        return vpcs_channel

    service = DiscoveryService(
        _FakeGNS3Client(
            {
                "node-r1": GNS3ConsoleInfo(
                    node_id="node-r1",
                    console_host="localhost",
                    console=5000,
                    console_type="telnet",
                ),
                "node-pc1": GNS3ConsoleInfo(
                    node_id="node-pc1",
                    console_host="localhost",
                    console=5004,
                    console_type="telnet",
                ),
            },
        ),
        channel_factory=channel_factory,
    )

    discovered = await service.synchronize_project_state(
        project_name="sprint6-demo",
        topology=topology,
        deployment_result=deployment,
        configuration_preview=preview,
    )

    assert isinstance(discovered, DiscoveredNetworkState)
    assert discovered.project_id == "proj-6"
    assert discovered.device_snapshots[0].desired_configuration_hash == "router-hash"
    assert discovered.device_snapshots[0].discovered_state.interfaces[0].status == "up"
    assert "configure terminal" in router_channel.commands
    assert "write memory" in router_channel.commands
    assert "show" in vpcs_channel.commands


def test_prompt_detector_recognizes_cisco_and_vpcs_prompts() -> None:
    assert PromptDetector.detect("Router#\n") is not None
    assert PromptDetector.detect("Router(config)#\n") is not None
    assert PromptDetector.detect("PC1>\n") is not None
