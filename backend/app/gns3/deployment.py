"""Topology layout and deployment helpers for Sprint 4."""

from __future__ import annotations

from collections import defaultdict

from app.domain.models import Device, TopologySpec
from app.gns3.exceptions import GNS3DeploymentError
from app.gns3.models import (
    GNS3DeploymentPlan,
    GNS3LinkDeploymentRequest,
    GNS3NodeDeploymentRequest,
)
from app.gns3.profiles import PlatformProfileLoader, PortMappingService


class TopologyLayoutService:
    """Assign deterministic coordinates to topology nodes."""

    def __init__(
        self,
        *,
        x_spacing: int = 220,
        router_y: int = 0,
        switch_y: int = 200,
        endpoint_y: int = 400,
        other_y: int = 600,
    ) -> None:
        self.x_spacing = x_spacing
        self.router_y = router_y
        self.switch_y = switch_y
        self.endpoint_y = endpoint_y
        self.other_y = other_y

    def assign(self, topology: TopologySpec) -> dict[str, tuple[int, int]]:
        grouped: dict[str, list[Device]] = defaultdict(list)
        for device in topology.devices:
            grouped[device.type].append(device)

        coordinates: dict[str, tuple[int, int]] = {}
        for device_type in ["router", "switch", "endpoint", "firewall", "server"]:
            devices = sorted(grouped.get(device_type, []), key=lambda item: item.id)
            y = self._resolve_y(device_type)
            for index, device in enumerate(devices):
                coordinates[device.id] = (index * self.x_spacing, y)

        return coordinates

    def _resolve_y(self, device_type: str) -> int:
        if device_type == "router":
            return self.router_y
        if device_type == "switch":
            return self.switch_y
        if device_type == "endpoint":
            return self.endpoint_y
        return self.other_y


class TopologyDeploymentPlanner:
    """Create dry-run node and link requests from a validated topology."""

    def __init__(
        self,
        profile_loader: PlatformProfileLoader,
        port_mapping_service: PortMappingService,
        layout_service: TopologyLayoutService,
    ) -> None:
        self.profile_loader = profile_loader
        self.port_mapping_service = port_mapping_service
        self.layout_service = layout_service

    def build_plan(
        self,
        topology: TopologySpec,
        *,
        project_name: str | None = None,
    ) -> GNS3DeploymentPlan:
        coordinates = self.layout_service.assign(topology)
        node_requests = self._build_node_requests(topology, coordinates)
        link_requests = self._build_link_requests(topology)

        return GNS3DeploymentPlan(
            project_name=project_name or topology.project.name,
            nodes=node_requests,
            links=link_requests,
        )

    def _build_node_requests(
        self,
        topology: TopologySpec,
        coordinates: dict[str, tuple[int, int]],
    ) -> list[GNS3NodeDeploymentRequest]:
        requests: list[GNS3NodeDeploymentRequest] = []

        for device in topology.devices:
            profile = self.profile_loader.get(device.platform)
            x, y = coordinates[device.id]
            requests.append(
                GNS3NodeDeploymentRequest(
                    domain_device_id=device.id,
                    name=device.hostname,
                    platform=device.platform,
                    x=x,
                    y=y,
                    properties={
                        "adapters": profile.minimum_adapters,
                    },
                ),
            )

        return requests

    def _build_link_requests(
        self,
        topology: TopologySpec,
    ) -> list[GNS3LinkDeploymentRequest]:
        device_by_id = {device.id: device for device in topology.devices}
        link_requests: list[GNS3LinkDeploymentRequest] = []

        for link in topology.links:
            source_device = device_by_id.get(link.source_device)
            target_device = device_by_id.get(link.target_device)
            if source_device is None or target_device is None:
                raise GNS3DeploymentError(
                    f"Cannot build link mapping for '{link.source_device}' -> '{link.target_device}'",
                )

            source_mapping = self.port_mapping_service.resolve(
                source_device.platform,
                link.source_interface,
            )
            target_mapping = self.port_mapping_service.resolve(
                target_device.platform,
                link.target_interface,
            )

            link_requests.append(
                GNS3LinkDeploymentRequest(
                    source_domain_device_id=link.source_device,
                    target_domain_device_id=link.target_device,
                    source_adapter_number=source_mapping.adapter_number,
                    source_port_number=source_mapping.port_number,
                    target_adapter_number=target_mapping.adapter_number,
                    target_port_number=target_mapping.port_number,
                ),
            )

        return link_requests
