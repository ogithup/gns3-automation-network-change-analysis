"""Service layer for Sprint 14 workflow orchestration."""

from __future__ import annotations

import json
from uuid import uuid4

from app.addressing.models import AddressingRequest
from app.addressing.service import AddressingService
from app.ai.service import AIService
from app.api.errors import APIError
from app.api.progress import ProgressEventHub
from app.api.repositories import (
    ChangeRecord,
    DeploymentRecord,
    InMemoryChangeRepository,
    InMemoryDeploymentRepository,
    InMemoryReportRepository,
    ReportRecord,
)
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
from app.configuration.generator import ConfigurationRenderer
from app.configuration.exceptions import ConfigurationError
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
from app.domain.models import TopologySpec
from app.gns3.client import GNS3Client
from app.gns3.deployment import TopologyDeploymentPlanner, TopologyLayoutService
from app.gns3.models import GNS3ConsoleInfo
from app.gns3.profiles import PlatformProfileLoader, PortMappingService
from app.gns3.services import GNS3DeploymentOrchestrator, GNS3LinkService, GNS3NodeService, GNS3ProjectService, GNS3TemplateResolver
from app.impact.service import RootCauseAnalysisService
from app.reporting.service import ReportingService
from app.risk.service import RiskScoringService
from app.rollback.models import ApprovalRecord
from app.simulation.service import SimulationService
from app.topology.service import TopologyService
from app.validation.service import ValidationService


class WorkflowService:
    """High-level orchestration service behind the FastAPI routes."""

    def __init__(
        self,
        *,
        deployment_repository: InMemoryDeploymentRepository | None = None,
        change_repository: InMemoryChangeRepository | None = None,
        report_repository: InMemoryReportRepository | None = None,
        progress_hub: ProgressEventHub | None = None,
        gns3_client: GNS3Client | None = None,
    ) -> None:
        self.deployment_repository = deployment_repository or InMemoryDeploymentRepository()
        self.change_repository = change_repository or InMemoryChangeRepository()
        self.report_repository = report_repository or InMemoryReportRepository()
        self.progress_hub = progress_hub or ProgressEventHub()
        self.topology_service = TopologyService()
        self.addressing_service = AddressingService()
        self.ai_service = AIService()
        self.configuration_renderer = ConfigurationRenderer()
        self.validation_service = ValidationService()
        self.simulation_service = SimulationService()
        self.risk_service = RiskScoringService()
        self.root_cause_service = RootCauseAnalysisService()
        self.reporting_service = ReportingService()
        self.gns3_client = gns3_client or GNS3Client()
        planner = TopologyDeploymentPlanner(
            PlatformProfileLoader(),
            PortMappingService(PlatformProfileLoader()),
            TopologyLayoutService(),
        )
        self.deployment_orchestrator = GNS3DeploymentOrchestrator(
            GNS3ProjectService(self.gns3_client),
            GNS3NodeService(self.gns3_client, GNS3TemplateResolver(self.gns3_client)),
            GNS3LinkService(self.gns3_client),
            deployment_planner=planner,
        )

    def load_topology(
        self,
        *,
        specification: dict[str, object] | None = None,
        yaml_content: str | None = None,
        json_content: str | None = None,
    ) -> TopologySpec:
        if specification is not None:
            return self.topology_service.load_json(json.dumps(specification))
        if yaml_content is not None:
            return self.topology_service.load_yaml(yaml_content)
        if json_content is not None:
            return self.topology_service.load_json(json_content)
        raise ValueError("A specification payload is required.")

    def validate_specification(self, topology: TopologySpec) -> TopologySpec:
        return topology

    def create_ip_plan(self, request: AddressingRequest):
        return self.addressing_service.plan(request)

    def interpret_topology_prompt(self, prompt: str, *, context: dict[str, object] | None = None):
        return self.ai_service.interpret_topology_request(prompt, context=context)

    def interpret_change_prompt(
        self,
        prompt: str,
        *,
        deployment_id: str | None = None,
        specification: TopologySpec | None = None,
        context: dict[str, object] | None = None,
    ):
        if deployment_id is not None:
            topology = self.get_deployment(deployment_id).topology
        elif specification is not None:
            topology = specification
        else:
            raise ValueError("A deployment_id or specification is required for change interpretation.")
        return self.ai_service.interpret_change_request(prompt, topology=topology, context=context)

    def explain_ai_results(self, payload: dict[str, object]):
        return self.ai_service.explain_deterministic_results(payload=payload)

    async def create_deployment(self, *, project_name: str, topology: TopologySpec, correlation_id: str | None) -> DeploymentRecord:
        deployment_id = str(uuid4())
        await self.progress_hub.publish(deployment_id, {"status": "Creating GNS3 project"})
        await self.progress_hub.publish(deployment_id, {"status": "Creating devices"})
        await self.progress_hub.publish(deployment_id, {"status": "Creating links"})
        plan = self.deployment_orchestrator.build_dry_run_plan(project_name, topology)
        record = DeploymentRecord(
            id=deployment_id,
            project_name=project_name,
            status="Draft",
            topology=topology,
            correlation_id=correlation_id,
            dry_run_plan=plan,
        )
        self.deployment_repository.save(record)
        return record

    def get_deployment(self, deployment_id: str) -> DeploymentRecord:
        return self.deployment_repository.get(deployment_id)

    async def configure_deployment(self, deployment_id: str) -> DeploymentRecord:
        record = self.deployment_repository.get(deployment_id)
        await self.progress_hub.publish(deployment_id, {"status": "Applying configurations"})
        try:
            record.configuration_preview = self.configuration_renderer.render_topology(record.topology)
        except ConfigurationError as error:
            raise APIError(
                status_code=400,
                error="configuration_error",
                detail=str(error),
            ) from error
        record.status = "Configured"
        self.deployment_repository.save(record)
        return record

    async def discover_deployment(self, deployment_id: str) -> DeploymentRecord:
        record = self.deployment_repository.get(deployment_id)
        await self.progress_hub.publish(deployment_id, {"status": "Discovering network"})
        record.discovered_state = _build_synthetic_discovered_state(record.id, record.project_name, record.topology)
        record.status = "Discovered"
        self.deployment_repository.save(record)
        return record

    async def validate_deployment(self, deployment_id: str) -> DeploymentRecord:
        record = self.deployment_repository.get(deployment_id)
        await self.progress_hub.publish(deployment_id, {"status": "Running connectivity tests"})
        record.validations = []
        for requirement in record.topology.connectivity_requirements:
            record.validations.append(
                await self.validation_service.validate_connectivity(
                    record.topology,
                    source_endpoint_id=requirement.source_endpoint_id,
                    target_endpoint_id=requirement.target_endpoint_id,
                    discovered_state=record.discovered_state,
                ),
            )
        record.status = "Validated"
        self.deployment_repository.save(record)
        self.report_repository.save(
            ReportRecord(
                id=str(uuid4()),
                deployment_id=record.id,
                validations=record.validations,
            ),
        )
        return record

    async def cancel_deployment(self, deployment_id: str) -> DeploymentRecord:
        record = self.deployment_repository.get(deployment_id)
        record.status = "Cancelled"
        self.deployment_repository.save(record)
        await self.progress_hub.publish(deployment_id, {"status": "Cancelled"})
        return record

    async def create_change(self, deployment_id: str, command_payload: dict[str, object], correlation_id: str | None) -> ChangeRecord:
        command = _parse_change_command(command_payload)
        record = ChangeRecord(
            id=str(uuid4()),
            deployment_id=deployment_id,
            status="Draft",
            command_type=command.type,
            summary=command.summary(),
            command_payload=command.serialize(),
            correlation_id=correlation_id,
        )
        self.change_repository.save(record)
        await self.progress_hub.publish(record.id, {"status": "Change created"})
        return record

    async def simulate_change(self, change_id: str) -> ChangeRecord:
        record = self.change_repository.get(change_id)
        deployment = self.deployment_repository.get(record.deployment_id)
        command = _parse_change_command(record.command_payload)
        await self.progress_hub.publish(change_id, {"status": "Simulating change"})
        simulation = await self.simulation_service.simulate_change(deployment.topology, command)
        risk = self.risk_service.assess_change(deployment.topology, simulation)
        record.simulation = simulation
        record.risk = risk
        record.status = "Simulated"
        self.change_repository.save(record)
        await self.progress_hub.publish(change_id, {"status": "Calculating risk"})
        return record

    async def approve_change(self, change_id: str, approval: ApprovalRecord) -> ChangeRecord:
        record = self.change_repository.get(change_id)
        record.approval = approval
        record.status = "Approved" if approval.approved else "Rejected"
        self.change_repository.save(record)
        return record

    async def apply_change(self, change_id: str) -> ChangeRecord:
        record = self.change_repository.get(change_id)
        deployment = self.deployment_repository.get(record.deployment_id)
        if record.simulation is None or record.risk is None or record.approval is None:
            raise ValueError("Change must be simulated, risk-reviewed, and approved before apply.")

        await self.progress_hub.publish(change_id, {"status": "Applying approved change"})
        command = _parse_change_command(record.command_payload)
        updated_topology = command.apply(deployment.topology)
        deployment.topology = updated_topology
        deployment.discovered_state = _build_synthetic_discovered_state(deployment.id, deployment.project_name, updated_topology)
        deployment.validations = [
            await self.validation_service.validate_connectivity(
                updated_topology,
                source_endpoint_id=requirement.source_endpoint_id,
                target_endpoint_id=requirement.target_endpoint_id,
                discovered_state=deployment.discovered_state,
            )
            for requirement in updated_topology.connectivity_requirements
        ]
        record.root_causes = [
            self.root_cause_service.analyze_connectivity_failure(
                topology=updated_topology,
                discovered_state=deployment.discovered_state,
                source_endpoint_id=requirement.source_endpoint_id,
                target_endpoint_id=requirement.target_endpoint_id,
                validation_result=validation,
            )
            for requirement, validation in zip(
                updated_topology.connectivity_requirements,
                deployment.validations,
                strict=False,
            )
            if not validation.predicted_reachable
        ]
        record.status = "Completed"
        self.change_repository.save(record)
        self.deployment_repository.save(deployment)
        await self.progress_hub.publish(change_id, {"status": "Running post-change verification"})
        self.report_repository.save(
            ReportRecord(
                id=str(uuid4()),
                deployment_id=deployment.id,
                change_id=record.id,
                validations=deployment.validations,
                root_causes=record.root_causes,
            ),
        )
        return record

    async def rollback_change(self, change_id: str) -> ChangeRecord:
        record = self.change_repository.get(change_id)
        deployment = self.deployment_repository.get(record.deployment_id)
        command = _parse_change_command(record.command_payload)
        deployment.topology = command.undo(deployment.topology)
        deployment.discovered_state = _build_synthetic_discovered_state(deployment.id, deployment.project_name, deployment.topology)
        record.status = "RolledBack"
        self.deployment_repository.save(deployment)
        self.change_repository.save(record)
        return record

    async def cancel_change(self, change_id: str) -> ChangeRecord:
        record = self.change_repository.get(change_id)
        record.status = "Cancelled"
        self.change_repository.save(record)
        await self.progress_hub.publish(change_id, {"status": "Cancelled"})
        return record

    def get_change(self, change_id: str) -> ChangeRecord:
        return self.change_repository.get(change_id)

    def get_report(self, report_id: str) -> ReportRecord:
        return self.report_repository.get(report_id)

    def generate_report(
        self,
        *,
        deployment_id: str | None = None,
        change_id: str | None = None,
        address_plan=None,
        user_requirements: list[str] | None = None,
    ):
        deployment = self.get_deployment(deployment_id) if deployment_id is not None else None
        change = self.get_change(change_id) if change_id is not None else None
        report_record = None
        for item in self.report_repository.list():
            if deployment_id is not None and item.deployment_id == deployment_id:
                if change_id is None or item.change_id == change_id:
                    report_record = item
        generated = self.reporting_service.generate_report(
            deployment=deployment,
            change=change,
            report_record=report_record,
            address_plan=address_plan,
            user_requirements=user_requirements,
        )
        stored_record = ReportRecord(
            id=generated.id,
            deployment_id=deployment_id,
            change_id=change_id,
            validations=report_record.validations if report_record else [],
            root_causes=report_record.root_causes if report_record else [],
            generated_report=generated,
        )
        self.report_repository.save(stored_record)
        return generated

    async def check_gns3_connectivity(self):
        try:
            version = await self.gns3_client.get_version()
            return True, version, "GNS3 server is reachable."
        except Exception as error:
            return False, None, str(error)


def _parse_change_command(payload: dict[str, object]) -> NetworkChangeCommand:
    command_type = payload.get("type")
    mapping = {
        "DELETE_VLAN": DeleteVLANCommand,
        "CHANGE_ACCESS_VLAN": ChangeAccessVLANCommand,
        "ADD_VLAN_TO_TRUNK": AddVLANToTrunkCommand,
        "REMOVE_VLAN_FROM_TRUNK": RemoveVLANFromTrunkCommand,
        "SHUTDOWN_INTERFACE": ShutdownInterfaceCommand,
        "ENABLE_INTERFACE": EnableInterfaceCommand,
        "CHANGE_GATEWAY": ChangeGatewayCommand,
        "ADD_STATIC_ROUTE": AddStaticRouteCommand,
        "REMOVE_STATIC_ROUTE": RemoveStaticRouteCommand,
        "ADD_ACL_RULE": AddACLRuleCommand,
        "REMOVE_ACL_RULE": RemoveACLRuleCommand,
    }
    model = mapping[str(command_type)]
    return model.model_validate(payload)


def _build_synthetic_discovered_state(project_id: str, project_name: str, topology: TopologySpec) -> DiscoveredNetworkState:
    snapshots: list[DeviceStateSnapshot] = []
    for device in topology.devices:
        interfaces = [
            InterfaceOperationalState(
                name=interface.name,
                ip_address=str(interface.ipv4_address.ip) if interface.ipv4_address is not None else None,
                status="up" if interface.enabled else "administratively down",
                protocol="up" if interface.enabled else "down",
            )
            for interface in device.interfaces
        ]
        vlans: list[DiscoveredVLAN] = []
        trunks: list[DiscoveredTrunk] = []
        routes: list[DiscoveredRoute] = []
        acls: list[DiscoveredACL] = []
        ospf_neighbors: list[DiscoveredOSPFNeighbor] = []
        if device.type == "switch":
            for vlan in topology.vlans:
                ports = [interface.name for interface in device.interfaces if interface.access_vlan == vlan.vlan_id]
                vlans.append(
                    DiscoveredVLAN(
                        vlan_id=vlan.vlan_id,
                        name=vlan.name,
                        status="active",
                        interfaces=ports,
                    ),
                )
            for interface in device.interfaces:
                if interface.trunk_vlans:
                    trunks.append(
                        DiscoveredTrunk(
                            interface_name=interface.name,
                            allowed_vlans=list(interface.trunk_vlans),
                        ),
                    )
        if device.type == "router":
            for route in topology.routes:
                if route.device_id == device.id:
                    routes.append(
                        DiscoveredRoute(
                            code="S" if route.protocol == "static" else "O",
                            network=str(route.destination),
                            next_hop=str(route.next_hop) if route.next_hop else None,
                            outgoing_interface=route.outgoing_interface,
                        ),
                    )
            for acl in topology.acls:
                if acl.device_id == device.id:
                    acls.append(
                        DiscoveredACL(
                            name=acl.name,
                            acl_type=acl.type,
                            entries=[
                                f"{rule.action} {rule.protocol} {rule.source} {rule.destination}"
                                for rule in acl.rules
                            ],
                        ),
                    )
            if any(protocol.device_id == device.id and protocol.protocol == "ospf" for protocol in topology.routing_protocols):
                ospf_neighbors.append(
                    DiscoveredOSPFNeighbor(
                        neighbor_id="2.2.2.2",
                        address="10.0.0.2",
                        state="FULL/DR",
                        interface_name=device.interfaces[0].name,
                    ),
                )
        snapshots.append(
            DeviceStateSnapshot(
                device_id=device.id,
                discovered_state=DiscoveredDeviceState(
                    device_id=device.id,
                    hostname=device.hostname,
                    platform=device.platform,
                    console=GNS3ConsoleInfo(
                        node_id=device.id,
                        console_host="localhost",
                        console=5000,
                        console_type="telnet",
                    ),
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
    return DiscoveredNetworkState(project_id=project_id, project_name=project_name, device_snapshots=snapshots)
