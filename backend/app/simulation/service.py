"""Immutable change simulation and impact analysis service."""

from __future__ import annotations

import asyncio

from app.changes.models import NetworkChangeCommand
from app.domain.models import ConnectivityRequirement, TopologySpec
from app.graph.service import GraphService
from app.simulation.models import ChangeSimulationResult, ImpactSummary, NetworkSnapshot
from app.topology.service import TopologyService
from app.validation.models import CombinedValidationResult
from app.validation.service import ValidationService


class SimulationService:
    """Run network change simulations on isolated topology state."""

    def __init__(
        self,
        *,
        validation_service: ValidationService | None = None,
        graph_service: GraphService | None = None,
    ) -> None:
        self.validation_service = validation_service or ValidationService()
        self.graph_service = graph_service or GraphService()

    async def simulate_change(
        self,
        topology: TopologySpec,
        command: NetworkChangeCommand,
        *,
        scenario_name: str | None = None,
        requirements: list[ConnectivityRequirement] | None = None,
    ) -> ChangeSimulationResult:
        snapshot = NetworkSnapshot(
            name=scenario_name or topology.project.name,
            topology_yaml=TopologyService.to_yaml(topology),
        )
        baseline_requirements = requirements or topology.connectivity_requirements

        before_results = await self._run_requirements(topology, baseline_requirements)
        updated_topology = command.apply(topology)
        after_results = await self._run_requirements(updated_topology, baseline_requirements)

        before_graph = self.graph_service.build_from_topology(topology)
        after_graph = self.graph_service.build_from_topology(updated_topology)
        impact = self._calculate_impact(
            updated_topology,
            command,
            baseline_requirements,
            before_results,
            after_results,
            before_graph,
            after_graph,
        )
        direct_impacts, indirect_impacts = self._classify_impacts(command, impact)

        return ChangeSimulationResult(
            snapshot=snapshot,
            command_type=command.type,
            command_summary=command.summary(),
            before_results=before_results,
            after_results=after_results,
            impact=impact,
            direct_impacts=direct_impacts,
            indirect_impacts=indirect_impacts,
        )

    async def _run_requirements(
        self,
        topology: TopologySpec,
        requirements: list[ConnectivityRequirement],
    ) -> list[CombinedValidationResult]:
        tasks = [
            self.validation_service.validate_connectivity(
                topology,
                source_endpoint_id=requirement.source_endpoint_id,
                target_endpoint_id=requirement.target_endpoint_id,
            )
            for requirement in requirements
        ]
        return list(await asyncio.gather(*tasks))

    def _calculate_impact(
        self,
        topology: TopologySpec,
        command: NetworkChangeCommand,
        requirements: list[ConnectivityRequirement],
        before_results: list[CombinedValidationResult],
        after_results: list[CombinedValidationResult],
        before_graph,
        after_graph,
    ) -> ImpactSummary:
        affected_objects = set(command.affected_objects())
        affected_devices = sorted(item for item in affected_objects if not item.startswith(("interface:", "vlan:", "subnet:", "endpoint:", "service:", "route:", "acl:", "gateway:")))
        affected_interfaces = sorted(item for item in affected_objects if item.startswith("interface:"))
        affected_vlans = sorted(item for item in affected_objects if item.startswith("vlan:"))
        affected_subnets = sorted(item for item in affected_objects if item.startswith("subnet:"))
        affected_services = sorted(item for item in affected_objects if item.startswith("service:"))
        affected_endpoints = sorted(item for item in affected_objects if item.startswith("endpoint:"))

        changed_validation_tests: list[str] = []
        lost_reachability_paths: list[list[str]] = []
        for index, (before, after) in enumerate(zip(before_results, after_results, strict=False)):
            if (
                before.predicted_reachable != after.predicted_reachable
                or before.failure_stage != after.failure_stage
                or before.path != after.path
            ):
                changed_validation_tests.append(f"requirement:{index}")
                if before.predicted_reachable and not after.predicted_reachable:
                    lost_reachability_paths.append(before.path)
                if index < len(requirements):
                    requirement = requirements[index]
                    affected_endpoints.extend(
                        [
                            f"endpoint:{requirement.source_endpoint_id}",
                            f"endpoint:{requirement.target_endpoint_id}",
                        ],
                    )

        if not affected_endpoints:
            for path in lost_reachability_paths:
                affected_endpoints.extend(node for node in path if node.startswith("endpoint:"))
        affected_endpoints = sorted(set(affected_endpoints))

        redundancy_available = after_graph.number_of_edges() >= before_graph.number_of_edges()

        return ImpactSummary(
            affected_devices=affected_devices,
            affected_interfaces=affected_interfaces,
            affected_vlans=affected_vlans,
            affected_subnets=affected_subnets,
            affected_endpoints=affected_endpoints,
            affected_services=affected_services,
            lost_reachability_paths=lost_reachability_paths,
            changed_validation_tests=changed_validation_tests,
            redundancy_available=redundancy_available,
        )

    def _classify_impacts(
        self,
        command: NetworkChangeCommand,
        impact: ImpactSummary,
    ) -> tuple[list[str], list[str]]:
        direct = sorted(command.affected_objects())
        indirect = sorted(
            set(impact.affected_endpoints)
            | set(impact.affected_services)
            | {item for path in impact.lost_reachability_paths for item in path},
        )
        indirect = [item for item in indirect if item not in direct]
        return direct, indirect
