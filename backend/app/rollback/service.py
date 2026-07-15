"""Approved change deployment, verification, and rollback services."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from ipaddress import IPv4Address, IPv4Network
from uuid import uuid4

from app.changes.models import (
    AddACLRuleCommand,
    AddStaticRouteCommand,
    AddVLANToTrunkCommand,
    ChangeAccessVLANCommand,
    ChangeGatewayCommand,
    DeleteVLANCommand,
    EnableInterfaceCommand,
    NetworkChangeCommand,
    RemoveACLRuleCommand,
    RemoveStaticRouteCommand,
    RemoveVLANFromTrunkCommand,
    ShutdownInterfaceCommand,
)
from app.discovery.models import DiscoveredNetworkState
from app.discovery.service import (
    CiscoConsoleSession,
    DiscoveryService,
    VPCSConsoleSession,
)
from app.domain.models import ACLRule, Device, Endpoint, TopologySpec
from app.gns3.models import GNS3ConsoleInfo
from app.risk.models import RiskAssessment
from app.rollback.exceptions import ChangeApprovalError, UnsupportedRollbackStrategyError
from app.rollback.models import (
    ApprovalRecord,
    ChangeAuditEntry,
    ChangeCommandPlan,
    ChangeDeploymentResult,
    CommandOutputRecord,
    ConfigurationBackup,
    RollbackStrategy,
    ValidationComparison,
)
from app.simulation.models import ChangeSimulationResult
from app.validation.models import CombinedValidationResult, RuntimeValidationResult
from app.validation.service import ValidationService

ProjectResetHandler = Callable[[str], Awaitable[None]]


class MinimalChangeCommandGenerator:
    """Translate typed domain changes into minimal device CLI commands."""

    def build(self, topology: TopologySpec, command: NetworkChangeCommand) -> list[ChangeCommandPlan]:
        if isinstance(command, RemoveVLANFromTrunkCommand):
            return [
                ChangeCommandPlan(
                    device_id=command.device,
                    commands=[
                        f"interface {command.interface}",
                        f"switchport trunk allowed vlan remove {command.vlan_id}",
                    ],
                    inverse_commands=[
                        f"interface {command.interface}",
                        f"switchport trunk allowed vlan add {command.vlan_id}",
                    ],
                ),
            ]

        if isinstance(command, AddVLANToTrunkCommand):
            return [
                ChangeCommandPlan(
                    device_id=command.device,
                    commands=[
                        f"interface {command.interface}",
                        f"switchport trunk allowed vlan add {command.vlan_id}",
                    ],
                    inverse_commands=[
                        f"interface {command.interface}",
                        f"switchport trunk allowed vlan remove {command.vlan_id}",
                    ],
                ),
            ]

        if isinstance(command, ShutdownInterfaceCommand):
            return [
                ChangeCommandPlan(
                    device_id=command.device,
                    commands=[f"interface {command.interface}", "shutdown"],
                    inverse_commands=[f"interface {command.interface}", "no shutdown"],
                ),
            ]

        if isinstance(command, EnableInterfaceCommand):
            return [
                ChangeCommandPlan(
                    device_id=command.device,
                    commands=[f"interface {command.interface}", "no shutdown"],
                    inverse_commands=[f"interface {command.interface}", "shutdown"],
                ),
            ]

        if isinstance(command, ChangeAccessVLANCommand):
            interface = next(
                item
                for device in topology.devices
                if device.id == command.device
                for item in device.interfaces
                if item.name == command.interface
            )
            previous_vlan = interface.access_vlan or 1
            return [
                ChangeCommandPlan(
                    device_id=command.device,
                    commands=[
                        f"interface {command.interface}",
                        f"switchport access vlan {command.vlan_id}",
                    ],
                    inverse_commands=[
                        f"interface {command.interface}",
                        f"switchport access vlan {previous_vlan}",
                    ],
                ),
            ]

        if isinstance(command, ChangeGatewayCommand):
            target_interface = next(
                (
                    interface.name
                    for device in topology.devices
                    for interface in device.interfaces
                    if interface.ipv4_address is not None
                    and interface.ipv4_address.ip == next(
                        vlan.gateway
                        for vlan in topology.vlans
                        if vlan.vlan_id == command.vlan_id
                    )
                ),
                None,
            )
            previous_gateway = next(
                vlan.gateway
                for vlan in topology.vlans
                if vlan.vlan_id == command.vlan_id
            )
            if target_interface is None or previous_gateway is None:
                return []
            device_id = next(
                device.id
                for device in topology.devices
                if any(
                    interface.name == target_interface and interface.ipv4_address is not None
                    for interface in device.interfaces
                )
            )
            return [
                ChangeCommandPlan(
                    device_id=device_id,
                    commands=[
                        f"interface {target_interface}",
                        f"ip address {command.gateway} {self._netmask_for_vlan(topology, command.vlan_id)}",
                    ],
                    inverse_commands=[
                        f"interface {target_interface}",
                        f"ip address {previous_gateway} {self._netmask_for_vlan(topology, command.vlan_id)}",
                    ],
                ),
            ]

        if isinstance(command, AddStaticRouteCommand):
            route_command = self._build_static_route_command(
                command.destination,
                command.next_hop,
                command.outgoing_interface,
            )
            return [
                ChangeCommandPlan(
                    device_id=command.device,
                    commands=[route_command],
                    inverse_commands=[f"no {route_command}"],
                ),
            ]

        if isinstance(command, RemoveStaticRouteCommand):
            route = next(item for item in topology.routes if item.id == command.route_id)
            route_command = self._build_static_route_command(
                route.destination,
                route.next_hop,
                route.outgoing_interface,
            )
            return [
                ChangeCommandPlan(
                    device_id=route.device_id,
                    commands=[f"no {route_command}"],
                    inverse_commands=[route_command],
                ),
            ]

        if isinstance(command, AddACLRuleCommand):
            acl = next(item for item in topology.acls if item.id == command.acl_id)
            return [
                ChangeCommandPlan(
                    device_id=acl.device_id or "",
                    commands=[
                        f"ip access-list {acl.type} {acl.name}",
                        self._render_acl_rule(
                            ACLRule(
                                id=command.rule_id,
                                action=command.action,
                                protocol=command.protocol,
                                source=command.source,
                                destination=command.destination,
                                source_port=command.source_port,
                                destination_port=command.destination_port,
                            ),
                        ),
                    ],
                    inverse_commands=[
                        f"ip access-list {acl.type} {acl.name}",
                        f"no {self._render_acl_rule(ACLRule(id=command.rule_id, action=command.action, protocol=command.protocol, source=command.source, destination=command.destination, source_port=command.source_port, destination_port=command.destination_port))}",
                    ],
                ),
            ]

        if isinstance(command, RemoveACLRuleCommand):
            acl = next(item for item in topology.acls if item.id == command.acl_id)
            rule = next(item for item in acl.rules if item.id == command.rule_id)
            rendered_rule = self._render_acl_rule(rule)
            return [
                ChangeCommandPlan(
                    device_id=acl.device_id or "",
                    commands=[
                        f"ip access-list {acl.type} {acl.name}",
                        f"no {rendered_rule}",
                    ],
                    inverse_commands=[
                        f"ip access-list {acl.type} {acl.name}",
                        rendered_rule,
                    ],
                ),
            ]

        if isinstance(command, DeleteVLANCommand):
            plans: list[ChangeCommandPlan] = []
            for device in topology.devices:
                vlan_interfaces = [i for i in device.interfaces if i.access_vlan == command.vlan_id or command.vlan_id in i.trunk_vlans]
                if device.type == "switch" and vlan_interfaces:
                    plans.append(
                        ChangeCommandPlan(
                            device_id=device.id,
                            commands=[f"no vlan {command.vlan_id}"],
                            inverse_commands=[f"vlan {command.vlan_id}"],
                        ),
                    )
                subinterfaces = [i.name for i in device.interfaces if i.name.endswith(f".{command.vlan_id}")]
                for subinterface in subinterfaces:
                    plans.append(
                        ChangeCommandPlan(
                            device_id=device.id,
                            commands=[f"no interface {subinterface}"],
                            inverse_commands=self._restore_subinterface_commands(topology, device.id, subinterface),
                        ),
                    )
            return plans

        raise UnsupportedRollbackStrategyError(
            f"Minimal command generation is not implemented for '{command.type}'.",
        )

    @staticmethod
    def _build_static_route_command(
        destination: IPv4Network,
        next_hop: IPv4Address | None,
        outgoing_interface: str | None,
    ) -> str:
        pieces = ["ip route", str(destination.network_address), str(destination.netmask)]
        if next_hop is not None:
            pieces.append(str(next_hop))
        if outgoing_interface is not None:
            pieces.append(outgoing_interface)
        return " ".join(pieces)

    @staticmethod
    def _render_acl_rule(rule: ACLRule) -> str:
        parts = [rule.action, rule.protocol, rule.source, rule.destination]
        if rule.source_port:
            parts.append(rule.source_port)
        if rule.destination_port:
            parts.append(rule.destination_port)
        return " ".join(parts)

    @staticmethod
    def _netmask_for_vlan(topology: TopologySpec, vlan_id: int) -> str:
        vlan = next(item for item in topology.vlans if item.vlan_id == vlan_id)
        assert vlan.subnet is not None
        return str(vlan.subnet.netmask)

    @staticmethod
    def _restore_subinterface_commands(
        topology: TopologySpec,
        device_id: str,
        interface_name: str,
    ) -> list[str]:
        interface = next(
            item
            for device in topology.devices
            if device.id == device_id
            for item in device.interfaces
            if item.name == interface_name
        )
        vlan_id = int(interface_name.split(".")[-1])
        commands = [f"interface {interface_name}", f"encapsulation dot1Q {vlan_id}"]
        if interface.ipv4_address is not None:
            commands.append(
                f"ip address {interface.ipv4_address.ip} {interface.ipv4_address.network.netmask}",
            )
        if interface.enabled:
            commands.append("no shutdown")
        return commands


class ChangeDeploymentService:
    """Apply approved changes to live GNS3 devices and rollback on failure."""

    def __init__(
        self,
        *,
        gns3_client,
        discovery_service: DiscoveryService,
        command_generator: MinimalChangeCommandGenerator | None = None,
        project_reset_handler: ProjectResetHandler | None = None,
    ) -> None:
        self.gns3_client = gns3_client
        self.discovery_service = discovery_service
        self.command_generator = command_generator or MinimalChangeCommandGenerator()
        self.project_reset_handler = project_reset_handler

    async def execute_change(
        self,
        *,
        topology: TopologySpec,
        discovered_state: DiscoveredNetworkState,
        simulation_result: ChangeSimulationResult,
        risk_assessment: RiskAssessment,
        command: NetworkChangeCommand,
        approval: ApprovalRecord,
        rollback_strategy: RollbackStrategy = "inverse_commands",
    ) -> ChangeDeploymentResult:
        result = ChangeDeploymentResult(
            change_id=str(uuid4()),
            project_id=discovered_state.project_id,
            project_name=discovered_state.project_name,
            state="Draft",
            command_type=command.type,
            command_summary=command.summary(),
            risk_assessment=risk_assessment,
            simulation_result=simulation_result,
            approval=approval,
            discovered_state_before=discovered_state,
        )
        self._audit(result, "Draft", "Change created for deployment.")
        self._audit(result, "Simulated", "Simulation confirmed.")
        result.state = "Simulated"
        self._audit(result, "UnderReview", "Risk reviewed and awaiting approval.")
        result.state = "UnderReview"

        if not approval.approved:
            raise ChangeApprovalError("Change is not approved for live execution.")

        result.state = "Approved"
        self._audit(
            result,
            "Approved",
            f"Change approved by {approval.reviewer or 'unknown reviewer'}.",
        )

        console_infos = {
            snapshot.device_id: snapshot.discovered_state.console
            for snapshot in discovered_state.device_snapshots
        }
        try:
            plans = self.command_generator.build(topology, command)
            result.command_plans = plans
            backups = await self._collect_pre_change_backups(topology, plans, console_infos, result)
            result.backups = backups

            result.state = "Applying"
            self._audit(result, "Applying", "Applying minimal change commands to GNS3 devices.")
            await self._apply_change_plans(topology, plans, console_infos, result)
            result.state = "Verifying"
            self._audit(result, "Verifying", "Rediscovering state and running post-change validation.")
            post_change_state = await self.discovery_service.discover_project_state(
                project_id=discovered_state.project_id,
                project_name=discovered_state.project_name,
                topology=topology,
                console_infos=console_infos,
            )
            result.discovered_state_after = post_change_state
            validations = await self._run_post_change_validations(
                topology=topology,
                command=command,
                post_change_state=post_change_state,
                console_infos=console_infos,
            )
            result.post_change_validations = validations
            result.validation_comparisons = self._compare_simulated_and_actual(
                topology,
                simulation_result,
                validations,
            )

            if self._has_critical_failure(result.validation_comparisons):
                result.state = "Failed"
                self._audit(result, "Failed", "Critical post-change mismatch detected.")
                await self._rollback(
                    topology=topology,
                    result=result,
                    console_infos=console_infos,
                    strategy=rollback_strategy,
                )
                return result

            result.state = "Completed"
            self._audit(result, "Completed", "Change applied and verified successfully.")
            return result
        except Exception as error:
            result.state = "Failed"
            self._audit(result, "Failed", f"Change application failed: {error}")
            await self._rollback(
                topology=topology,
                result=result,
                console_infos=console_infos,
                strategy=rollback_strategy,
            )
            return result

    async def _collect_pre_change_backups(
        self,
        topology: TopologySpec,
        plans: list[ChangeCommandPlan],
        console_infos: dict[str, GNS3ConsoleInfo],
        result: ChangeDeploymentResult,
    ) -> list[ConfigurationBackup]:
        device_map = {device.id: device for device in topology.devices}
        backups: list[ConfigurationBackup] = []
        for plan in plans:
            device = device_map[plan.device_id]
            if device.platform == "vpcs":
                continue
            output = ""
            session = await self._build_session(device, console_infos[device.id])
            await session.open()
            try:
                await session.bootstrap()
                output = await session.execute("show running-config")
                backups.append(
                    ConfigurationBackup(
                        device_id=device.id,
                        hostname=device.hostname,
                        content=output,
                    ),
                )
                result.command_outputs.append(
                    CommandOutputRecord(
                        device_id=device.id,
                        command="show running-config",
                        output=output,
                    ),
                )
            finally:
                await session.close()
            plan.backup_restore_commands = self._extract_restore_commands(output)
        return backups

    async def _apply_change_plans(
        self,
        topology: TopologySpec,
        plans: list[ChangeCommandPlan],
        console_infos: dict[str, GNS3ConsoleInfo],
        result: ChangeDeploymentResult,
    ) -> None:
        device_map = {device.id: device for device in topology.devices}
        for plan in plans:
            device = device_map[plan.device_id]
            session = await self._build_session(device, console_infos[device.id])
            await session.open()
            try:
                await session.bootstrap()
                if device.platform == "vpcs":
                    for command in plan.commands:
                        output = await session.execute(command)
                        result.command_outputs.append(
                            CommandOutputRecord(
                                device_id=device.id,
                                command=command,
                                output=output,
                            ),
                        )
                else:
                    output = await session.execute("configure terminal")
                    result.command_outputs.append(
                        CommandOutputRecord(
                            device_id=device.id,
                            command="configure terminal",
                            output=output,
                        ),
                    )
                    for command in plan.commands:
                        output = await session.execute(command)
                        result.command_outputs.append(
                            CommandOutputRecord(
                                device_id=device.id,
                                command=command,
                                output=output,
                            ),
                        )
                    output = await session.execute("end")
                    result.command_outputs.append(
                        CommandOutputRecord(
                            device_id=device.id,
                            command="end",
                            output=output,
                        ),
                    )
                    output = await session.execute("write memory")
                    result.command_outputs.append(
                        CommandOutputRecord(
                            device_id=device.id,
                            command="write memory",
                            output=output,
                        ),
                    )
            finally:
                await session.close()

    async def _run_post_change_validations(
        self,
        *,
        topology: TopologySpec,
        command: NetworkChangeCommand,
        post_change_state: DiscoveredNetworkState,
        console_infos: dict[str, GNS3ConsoleInfo],
    ) -> list[CombinedValidationResult]:
        expected_topology = command.apply(topology)
        runtime_validator = self._runtime_validator(post_change_state, console_infos)
        validation_service = ValidationService(runtime_validator=runtime_validator)
        validations: list[CombinedValidationResult] = []
        for requirement in expected_topology.connectivity_requirements:
            validations.append(
                await validation_service.validate_connectivity(
                    expected_topology,
                    source_endpoint_id=requirement.source_endpoint_id,
                    target_endpoint_id=requirement.target_endpoint_id,
                    discovered_state=post_change_state,
                ),
            )
        return validations

    def _runtime_validator(
        self,
        discovered_state: DiscoveredNetworkState,
        console_infos: dict[str, GNS3ConsoleInfo],
    ):
        device_snapshots = {
            snapshot.device_id: snapshot.discovered_state
            for snapshot in discovered_state.device_snapshots
        }

        async def validate(topology: TopologySpec, source: Endpoint, target: Endpoint) -> RuntimeValidationResult:
            source_device = next(device for device in topology.devices if device.id == source.device_id)
            source_console = console_infos[source.device_id]
            session = await self._build_session(source_device, source_console)
            await session.open()
            try:
                await session.bootstrap()
                ping_output = await session.execute(f"ping {target.ip_address}")
            finally:
                await session.close()

            gateway_checks = []
            trunk_checks = []
            vlan_checks = []
            route_checks = []
            acl_checks = []
            ospf_checks = []

            for snapshot in device_snapshots.values():
                if snapshot.running_config is not None:
                    gateway_checks.append("running-config collected")
                if snapshot.vlans:
                    vlan_checks.append(f"{snapshot.device_id}: vlan brief collected")
                if snapshot.trunk_vlans:
                    trunk_checks.append(f"{snapshot.device_id}: interfaces trunk collected")
                if snapshot.routes:
                    route_checks.append(f"{snapshot.device_id}: ip route collected")
                if snapshot.acls:
                    acl_checks.append(f"{snapshot.device_id}: access-lists collected")
                if snapshot.ospf_neighbors:
                    ospf_checks.append(f"{snapshot.device_id}: ospf neighbor collected")

            reachable = self._ping_succeeded(ping_output)
            return RuntimeValidationResult(
                reachable=reachable,
                traceroute_path=[],
                interface_checks=gateway_checks,
                vlan_checks=vlan_checks,
                trunk_checks=trunk_checks,
                route_checks=route_checks,
                ospf_neighbor_checks=ospf_checks,
                acl_attachment_checks=acl_checks,
                technical_explanation="Runtime validation executed through live console ping and rediscovery checks.",
            )

        return validate

    def _compare_simulated_and_actual(
        self,
        topology: TopologySpec,
        simulation_result: ChangeSimulationResult,
        validations: list[CombinedValidationResult],
    ) -> list[ValidationComparison]:
        comparisons: list[ValidationComparison] = []
        for requirement, predicted, actual in zip(
            topology.connectivity_requirements,
            simulation_result.after_results,
            validations,
            strict=False,
        ):
            comparisons.append(
                ValidationComparison(
                    requirement_id=requirement.id,
                    predicted_reachable=predicted.predicted_reachable,
                    actual_reachable=actual.actual_reachable,
                    state=actual.state,
                    suspected_reason=actual.suspected_reason,
                    technical_explanation=actual.technical_explanation,
                ),
            )
        return comparisons

    async def _rollback(
        self,
        *,
        topology: TopologySpec,
        result: ChangeDeploymentResult,
        console_infos: dict[str, GNS3ConsoleInfo],
        strategy: RollbackStrategy,
    ) -> None:
        result.state = "RollingBack"
        result.rollback_strategy_used = strategy
        self._audit(result, "RollingBack", f"Starting rollback using '{strategy}'.")

        if strategy == "project_reset":
            if self.project_reset_handler is None:
                raise UnsupportedRollbackStrategyError("No project reset handler is configured.")
            await self.project_reset_handler(result.project_id)
            result.state = "RolledBack"
            result.rollback_executed = True
            self._audit(result, "RolledBack", "Project reset rollback executed.")
            return

        plans = result.command_plans
        device_map = {device.id: device for device in topology.devices}
        for plan in plans:
            commands = (
                plan.inverse_commands
                if strategy == "inverse_commands"
                else plan.backup_restore_commands
            )
            if not commands:
                raise UnsupportedRollbackStrategyError(
                    f"No rollback commands available for device '{plan.device_id}'.",
                )
            device = device_map[plan.device_id]
            session = await self._build_session(device, console_infos[plan.device_id])
            await session.open()
            try:
                await session.bootstrap()
                output = await session.execute("configure terminal")
                result.command_outputs.append(
                    CommandOutputRecord(
                        device_id=device.id,
                        command="configure terminal",
                        output=output,
                    ),
                )
                for command in commands:
                    output = await session.execute(command)
                    result.command_outputs.append(
                        CommandOutputRecord(
                            device_id=device.id,
                            command=command,
                            output=output,
                        ),
                    )
                output = await session.execute("end")
                result.command_outputs.append(
                    CommandOutputRecord(
                        device_id=device.id,
                        command="end",
                        output=output,
                    ),
                )
                output = await session.execute("write memory")
                result.command_outputs.append(
                    CommandOutputRecord(
                        device_id=device.id,
                        command="write memory",
                        output=output,
                    ),
                )
            finally:
                await session.close()

        result.state = "RolledBack"
        result.rollback_executed = True
        self._audit(result, "RolledBack", "Rollback commands executed successfully.")

    async def _build_session(self, device: Device, console_info: GNS3ConsoleInfo):
        channel = await self.discovery_service.channel_factory(console_info)
        if device.platform == "vpcs":
            return VPCSConsoleSession(channel)
        return CiscoConsoleSession(
            channel,
            self.discovery_service._discovery_commands_for_platform(device.platform),
        )

    @staticmethod
    def _ping_succeeded(output: str) -> bool:
        lowered = output.lower()
        return "unreachable" not in lowered and "timeout" not in lowered and "100%" not in lowered

    @staticmethod
    def _has_critical_failure(comparisons: list[ValidationComparison]) -> bool:
        return any(item.state == "MODEL_RUNTIME_MISMATCH" for item in comparisons)

    @staticmethod
    def _extract_restore_commands(running_config: str) -> list[str]:
        commands: list[str] = []
        for raw_line in running_config.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(("Building configuration", "Current configuration", "end", "!")):
                continue
            commands.append(stripped)
        return commands

    @staticmethod
    def _audit(
        result: ChangeDeploymentResult,
        state,
        message: str,
        *,
        device_id: str | None = None,
        command: str | None = None,
        output: str | None = None,
    ) -> None:
        result.audit_history.append(
            ChangeAuditEntry(
                state=state,
                message=message,
                device_id=device_id,
                command=command,
                output=output,
            ),
        )
