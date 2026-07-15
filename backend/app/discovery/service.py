"""Configuration deployment and state discovery services."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from app.configuration.models import ConfigurationPreview, RenderedConfiguration
from app.discovery.console import ConsoleChannel, PromptDetector, PromptMatch, TelnetConsoleChannel
from app.discovery.exceptions import ConfigurationApplyError, PromptDetectionError
from app.discovery.models import DeviceStateSnapshot, DiscoveredNetworkState
from app.discovery.parsers import DiscoveryParserRegistry
from app.domain.models import Device, TopologySpec
from app.gns3.client import GNS3Client
from app.gns3.models import GNS3ConsoleInfo, GNS3DeploymentResult

logger = logging.getLogger(__name__)

ConsoleChannelFactory = Callable[[GNS3ConsoleInfo], Awaitable[ConsoleChannel]]


class StateSnapshotStore:
    """In-memory state store for desired and discovered snapshots."""

    def __init__(self) -> None:
        self._states: dict[str, DiscoveredNetworkState] = {}

    def save(self, state: DiscoveredNetworkState) -> None:
        self._states[state.project_id] = state

    def get(self, project_id: str) -> DiscoveredNetworkState | None:
        return self._states.get(project_id)


class BaseConsoleSession:
    """Shared helpers for CLI automation."""

    cli_error_markers = (
        "% Invalid input",
        "% Incomplete command",
        "% Ambiguous command",
        "% Unrecognized command",
    )

    def __init__(self, channel: ConsoleChannel) -> None:
        self.channel = channel

    async def open(self) -> None:
        await self.channel.open()

    async def close(self) -> None:
        await self.channel.close()

    async def execute(self, command: str) -> str:
        await self.channel.write_line(command)
        output = await self.channel.read_until_idle()
        self._raise_for_cli_errors(command, output)
        return output

    def _raise_for_cli_errors(self, command: str, output: str) -> None:
        for marker in self.cli_error_markers:
            if marker in output:
                raise ConfigurationApplyError(
                    f"CLI rejected command '{command}': {marker}",
                )


class CiscoConsoleSession(BaseConsoleSession):
    """Cisco IOS interactive console handling."""

    def __init__(self, channel: ConsoleChannel, discovery_commands: list[str]) -> None:
        super().__init__(channel)
        self.discovery_commands = discovery_commands

    async def bootstrap(self) -> PromptMatch:
        output = await self.execute("")
        prompt = PromptDetector.detect(output)

        if prompt is not None and prompt.prompt_type == "setup_dialog":
            output = await self.execute("no")
            prompt = PromptDetector.detect(output)
            if prompt is None or prompt.prompt_type == "press_return":
                output = await self.execute("")
                prompt = PromptDetector.detect(output)

        if prompt is not None and prompt.prompt_type == "press_return":
            output = await self.execute("")
            prompt = PromptDetector.detect(output)

        if prompt is None:
            raise PromptDetectionError("Unable to detect Cisco prompt after bootstrap")

        if prompt.prompt_type == "user":
            output = await self.execute("enable")
            prompt = PromptDetector.detect(output)

        if prompt is None or prompt.prompt_type not in {"privileged", "config"}:
            raise PromptDetectionError(
                f"Unexpected Cisco prompt state '{prompt.prompt_type if prompt else 'unknown'}'",
            )

        await self.execute("terminal length 0")
        return prompt

    async def apply_configuration(self, rendered: RenderedConfiguration) -> None:
        commands = [
            line.strip()
            for line in rendered.content.splitlines()
            if line.strip() and line.strip() not in {"!", "end"}
        ]
        if not commands:
            return

        await self.execute("configure terminal")
        for command in commands:
            await self.execute(command)
        await self.execute("end")
        await self.execute("write memory")

    async def collect_outputs(self) -> dict[str, str]:
        outputs: dict[str, str] = {}
        for command in self.discovery_commands:
            outputs[command] = await self.execute(command)
        return outputs


class VPCSConsoleSession(BaseConsoleSession):
    """VPCS-specific command handling."""

    async def bootstrap(self) -> PromptMatch:
        output = await self.execute("")
        prompt = PromptDetector.detect(output)
        if prompt is None:
            output = await self.execute("")
            prompt = PromptDetector.detect(output)
        if prompt is None or prompt.prompt_type != "vpcs":
            raise PromptDetectionError("Unable to detect VPCS prompt")
        return prompt

    async def apply_configuration(self, rendered: RenderedConfiguration) -> None:
        for line in rendered.content.splitlines():
            command = line.strip()
            if command:
                await self.execute(command)

    async def collect_outputs(self) -> dict[str, str]:
        return {"show": await self.execute("show")}


class DiscoveryService:
    """Apply generated configuration and collect discovered state."""

    def __init__(
        self,
        gns3_client: GNS3Client,
        *,
        channel_factory: ConsoleChannelFactory | None = None,
        parser_registry: DiscoveryParserRegistry | None = None,
        state_store: StateSnapshotStore | None = None,
    ) -> None:
        self.gns3_client = gns3_client
        self.channel_factory = channel_factory or self._default_channel_factory
        self.parser_registry = parser_registry or DiscoveryParserRegistry()
        self.state_store = state_store or StateSnapshotStore()

    async def synchronize_project_state(
        self,
        *,
        project_name: str,
        topology: TopologySpec,
        deployment_result: GNS3DeploymentResult,
        configuration_preview: ConfigurationPreview,
    ) -> DiscoveredNetworkState:
        devices_by_id = {device.id: device for device in topology.devices}
        rendered_by_device_id = {
            rendered.device_id: rendered
            for rendered in configuration_preview.rendered_configurations
        }

        snapshots: list[DeviceStateSnapshot] = []
        for mapping in deployment_result.node_mappings:
            device = devices_by_id[mapping.domain_device_id]
            rendered = rendered_by_device_id.get(device.id)
            console_info = await self.gns3_client.get_node_console(
                deployment_result.project.project_id,
                mapping.gns3_node_id,
            )
            snapshot = await self._configure_and_discover_device(
                device=device,
                console_info=console_info,
                rendered=rendered,
            )
            snapshots.append(snapshot)

        discovered = DiscoveredNetworkState(
            project_id=deployment_result.project.project_id,
            project_name=project_name,
            device_snapshots=snapshots,
        )
        self.state_store.save(discovered)
        return discovered

    async def discover_project_state(
        self,
        *,
        project_id: str,
        project_name: str,
        topology: TopologySpec,
        console_infos: dict[str, GNS3ConsoleInfo],
    ) -> DiscoveredNetworkState:
        snapshots: list[DeviceStateSnapshot] = []
        for device in topology.devices:
            console_info = console_infos[device.id]
            snapshots.append(
                await self._configure_and_discover_device(
                    device=device,
                    console_info=console_info,
                    rendered=None,
                ),
            )

        discovered = DiscoveredNetworkState(
            project_id=project_id,
            project_name=project_name,
            device_snapshots=snapshots,
        )
        self.state_store.save(discovered)
        return discovered

    async def _configure_and_discover_device(
        self,
        *,
        device: Device,
        console_info: GNS3ConsoleInfo,
        rendered: RenderedConfiguration | None,
    ) -> DeviceStateSnapshot:
        channel = await self.channel_factory(console_info)
        session = (
            VPCSConsoleSession(channel)
            if device.platform == "vpcs"
            else CiscoConsoleSession(channel, self._discovery_commands_for_platform(device.platform))
        )

        await session.open()
        try:
            await session.bootstrap()
            if rendered is not None:
                logger.info("Applying configuration to %s", device.id)
                await session.apply_configuration(rendered)
            raw_outputs = await session.collect_outputs()
        finally:
            await session.close()

        discovered_state = self.parser_registry.parse_device(
            device_id=device.id,
            hostname=device.hostname,
            platform=device.platform,
            console=console_info,
            raw_outputs=raw_outputs,
        )
        return DeviceStateSnapshot(
            device_id=device.id,
            desired_configuration=rendered.content if rendered else None,
            desired_configuration_hash=rendered.content_hash if rendered else None,
            discovered_state=discovered_state,
        )

    @staticmethod
    async def _default_channel_factory(console_info: GNS3ConsoleInfo) -> ConsoleChannel:
        return TelnetConsoleChannel(console_info)

    @staticmethod
    def _discovery_commands_for_platform(platform: str) -> list[str]:
        if platform == "iosvl2":
            return [
                "show running-config",
                "show ip interface brief",
                "show vlan brief",
                "show interfaces trunk",
                "show access-lists",
            ]

        return [
            "show running-config",
            "show ip interface brief",
            "show ip route",
            "show access-lists",
            "show ip ospf neighbor",
        ]
