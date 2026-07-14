"""Sprint 4 topology deployment and port mapping tests."""

from __future__ import annotations

import json

import httpx
import pytest

from app.domain.models import TopologySpec
from app.gns3.client import GNS3Client
from app.gns3.deployment import TopologyDeploymentPlanner, TopologyLayoutService
from app.gns3.profiles import PlatformProfileLoader, PortMappingService
from app.gns3.services import (
    GNS3DeploymentOrchestrator,
    GNS3LinkService,
    GNS3NodeService,
    GNS3ProjectService,
    GNS3TemplateResolver,
)


def _json_response(status_code: int, payload: object) -> httpx.Response:
    return httpx.Response(status_code=status_code, json=payload)


def _build_topology() -> TopologySpec:
    return TopologySpec.model_validate(
        {
            "project": {"name": "deployment-demo"},
            "devices": [
                {
                    "id": "r1",
                    "hostname": "R1",
                    "type": "router",
                    "platform": "iosv",
                    "interfaces": [{"name": "GigabitEthernet0/0"}],
                },
                {
                    "id": "sw1",
                    "hostname": "SW1",
                    "type": "switch",
                    "platform": "iosvl2",
                    "interfaces": [
                        {"name": "GigabitEthernet0/1"},
                        {"name": "GigabitEthernet0/2"},
                    ],
                },
                {
                    "id": "pc1",
                    "hostname": "PC1",
                    "type": "endpoint",
                    "platform": "vpcs",
                    "interfaces": [{"name": "Ethernet0"}],
                },
            ],
            "links": [
                {
                    "source_device": "r1",
                    "source_interface": "GigabitEthernet0/0",
                    "target_device": "sw1",
                    "target_interface": "GigabitEthernet0/1",
                },
                {
                    "source_device": "sw1",
                    "source_interface": "GigabitEthernet0/2",
                    "target_device": "pc1",
                    "target_interface": "Ethernet0",
                },
            ],
        },
    )


def test_port_mapping_service_maps_interfaces_to_adapters() -> None:
    port_mapping = PortMappingService(PlatformProfileLoader())

    iosv_mapping = port_mapping.resolve("iosv", "GigabitEthernet0/1")
    subif_mapping = port_mapping.resolve("iosv", "GigabitEthernet0/1.10")
    vpcs_mapping = port_mapping.resolve("vpcs", "Ethernet0")

    assert (iosv_mapping.adapter_number, iosv_mapping.port_number) == (1, 0)
    assert (subif_mapping.adapter_number, subif_mapping.port_number) == (1, 0)
    assert (vpcs_mapping.adapter_number, vpcs_mapping.port_number) == (0, 0)


def test_layout_service_assigns_deterministic_coordinates() -> None:
    topology = _build_topology()
    layout = TopologyLayoutService()

    coordinates = layout.assign(topology)

    assert coordinates["r1"] == (0, 0)
    assert coordinates["sw1"] == (0, 200)
    assert coordinates["pc1"] == (0, 400)


def test_deployment_planner_builds_nodes_and_links() -> None:
    topology = _build_topology()
    planner = TopologyDeploymentPlanner(
        PlatformProfileLoader(),
        PortMappingService(PlatformProfileLoader()),
        TopologyLayoutService(),
    )

    plan = planner.build_plan(topology)

    assert [node.name for node in plan.nodes] == ["R1", "SW1", "PC1"]
    assert plan.nodes[0].properties["adapters"] == 4
    assert len(plan.links) == 2
    assert plan.links[0].source_adapter_number == 0
    assert plan.links[0].target_adapter_number == 1


@pytest.mark.asyncio
async def test_orchestrator_uses_planner_and_starts_nodes_in_order() -> None:
    request_log: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_log.append((request.method, request.url.path))
        if request.url.path == "/v2/projects" and request.method == "POST":
            payload = json.loads(request.content.decode())
            return _json_response(
                200,
                {"project_id": "proj-4", "name": payload["name"], "status": "closed"},
            )
        if request.url.path == "/v2/projects/proj-4/open":
            return _json_response(
                200,
                {"project_id": "proj-4", "name": "deployment-demo", "status": "opened"},
            )
        if request.url.path == "/v2/templates":
            return _json_response(
                200,
                [
                    {"template_id": "tmpl-iosv", "name": "IOSv", "template_type": "qemu"},
                    {"template_id": "tmpl-iosvl2", "name": "IOSvL2", "template_type": "qemu"},
                    {"template_id": "tmpl-vpcs", "name": "VPCS", "template_type": "vpcs"},
                ],
            )
        if request.url.path == "/v2/projects/proj-4/templates/tmpl-iosv":
            payload = json.loads(request.content.decode())
            return _json_response(200, {"node_id": "node-r1", "name": payload["name"]})
        if request.url.path == "/v2/projects/proj-4/templates/tmpl-iosvl2":
            payload = json.loads(request.content.decode())
            return _json_response(200, {"node_id": "node-sw1", "name": payload["name"]})
        if request.url.path == "/v2/projects/proj-4/templates/tmpl-vpcs":
            payload = json.loads(request.content.decode())
            return _json_response(200, {"node_id": "node-pc1", "name": payload["name"]})
        if request.url.path == "/v2/projects/proj-4/links":
            return _json_response(200, {"link_id": "link-1"})
        if request.url.path.endswith("/start"):
            node_id = request.url.path.split("/")[-2]
            return _json_response(200, {"node_id": node_id, "name": node_id})

        raise AssertionError(f"Unexpected request: {request.method} {request.url.path}")

    planner = TopologyDeploymentPlanner(
        PlatformProfileLoader(),
        PortMappingService(PlatformProfileLoader()),
        TopologyLayoutService(),
    )
    topology = _build_topology()

    async with GNS3Client(
        base_url="http://gns3.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        orchestrator = GNS3DeploymentOrchestrator(
            GNS3ProjectService(client),
            GNS3NodeService(client, GNS3TemplateResolver(client)),
            GNS3LinkService(client),
            deployment_planner=planner,
        )
        result = await orchestrator.deploy(topology.project.name, topology)

    assert result.devices == {
        "r1": "node-r1",
        "sw1": "node-sw1",
        "pc1": "node-pc1",
    }
    assert ("POST", "/v2/projects/proj-4/nodes/node-r1/start") in request_log
    assert ("POST", "/v2/projects/proj-4/nodes/node-sw1/start") in request_log
    assert ("POST", "/v2/projects/proj-4/nodes/node-pc1/start") in request_log
