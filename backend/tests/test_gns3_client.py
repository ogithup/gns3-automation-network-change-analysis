"""Mocked tests for the GNS3 API integration layer."""

from __future__ import annotations

import json

import httpx
import pytest

from app.domain.models import NetworkProject, TopologySpec
from app.gns3.client import GNS3Client
from app.gns3.exceptions import GNS3DeploymentError, GNS3TemplateNotFoundError
from app.gns3.models import GNS3LinkDeploymentRequest
from app.gns3.services import (
    GNS3DeploymentOrchestrator,
    GNS3LinkService,
    GNS3NodeService,
    GNS3ProjectService,
    GNS3TemplateResolver,
)


def _json_response(status_code: int, payload: object) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=payload,
    )


@pytest.mark.asyncio
async def test_gns3_client_reads_version_and_templates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/version":
            return _json_response(200, {"version": "2.2.59", "local": True})
        if request.url.path == "/v2/templates":
            return _json_response(
                200,
                [
                    {
                        "template_id": "tmpl-iosv",
                        "name": "IOSv",
                        "template_type": "qemu",
                    },
                    {
                        "template_id": "tmpl-vpcs",
                        "name": "VPCS",
                        "template_type": "vpcs",
                    },
                ],
            )
        raise AssertionError(f"Unexpected request path: {request.url.path}")

    transport = httpx.MockTransport(handler)
    async with GNS3Client(base_url="http://gns3.test", transport=transport) as client:
        version = await client.get_version()
        templates = await client.list_templates()

    assert version.version == "2.2.59"
    assert [template.name for template in templates] == ["IOSv", "VPCS"]


@pytest.mark.asyncio
async def test_template_resolver_maps_logical_platform_name() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/templates"
        return _json_response(
            200,
            [
                {
                    "template_id": "tmpl-iosvl2",
                    "name": "IOSvL2",
                    "template_type": "qemu",
                },
            ],
        )

    async with GNS3Client(
        base_url="http://gns3.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        resolver = GNS3TemplateResolver(client)
        template = await resolver.resolve("iosvl2")

    assert template.template_id == "tmpl-iosvl2"


@pytest.mark.asyncio
async def test_template_resolver_raises_for_missing_template() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/templates"
        return _json_response(200, [])

    async with GNS3Client(
        base_url="http://gns3.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        resolver = GNS3TemplateResolver(client)
        with pytest.raises(GNS3TemplateNotFoundError):
            await resolver.resolve("iosv")


@pytest.mark.asyncio
async def test_orchestrator_deploys_project_nodes_and_links() -> None:
    state = {"project_opened": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/projects" and request.method == "POST":
            payload = json.loads(request.content.decode())
            return _json_response(
                200,
                {
                    "project_id": "proj-1",
                    "name": payload["name"],
                    "status": "closed",
                },
            )
        if request.url.path == "/v2/projects/proj-1/open":
            state["project_opened"] = True
            return _json_response(
                200,
                {"project_id": "proj-1", "name": "demo", "status": "opened"},
            )
        if request.url.path == "/v2/templates":
            return _json_response(
                200,
                [
                    {
                        "template_id": "tmpl-iosv",
                        "name": "IOSv",
                        "template_type": "qemu",
                    },
                    {
                        "template_id": "tmpl-vpcs",
                        "name": "VPCS",
                        "template_type": "vpcs",
                    },
                ],
            )
        if request.url.path == "/v2/projects/proj-1/templates/tmpl-iosv":
            payload = json.loads(request.content.decode())
            return _json_response(
                200,
                {
                    "node_id": "node-r1",
                    "name": payload["name"],
                    "template_id": "tmpl-iosv",
                    "console_type": "telnet",
                },
            )
        if request.url.path == "/v2/projects/proj-1/templates/tmpl-vpcs":
            payload = json.loads(request.content.decode())
            return _json_response(
                200,
                {
                    "node_id": "node-pc1",
                    "name": payload["name"],
                    "template_id": "tmpl-vpcs",
                    "console_type": "telnet",
                },
            )
        if request.url.path == "/v2/projects/proj-1/links":
            return _json_response(200, {"link_id": "link-1"})

        raise AssertionError(f"Unexpected request: {request.method} {request.url.path}")

    topology = TopologySpec(
        project=NetworkProject(name="demo-topology"),
        devices=[
            {
                "id": "r1",
                "hostname": "R1",
                "type": "router",
                "platform": "iosv",
            },
            {
                "id": "pc1",
                "hostname": "PC1",
                "type": "endpoint",
                "platform": "vpcs",
            },
        ],
    )

    async with GNS3Client(
        base_url="http://gns3.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        orchestrator = GNS3DeploymentOrchestrator(
            GNS3ProjectService(client),
            GNS3NodeService(client, GNS3TemplateResolver(client)),
            GNS3LinkService(client),
        )
        result = await orchestrator.deploy(
            "demo",
            topology,
            link_requests=[
                GNS3LinkDeploymentRequest(
                    source_domain_device_id="r1",
                    target_domain_device_id="pc1",
                    source_adapter_number=0,
                    source_port_number=0,
                    target_adapter_number=0,
                    target_port_number=0,
                ),
            ],
        )

    assert state["project_opened"] is True
    assert result.project.project_id == "proj-1"
    assert len(result.node_mappings) == 2
    assert result.links[0].link_id == "link-1"


@pytest.mark.asyncio
async def test_orchestrator_rolls_back_project_on_partial_failure() -> None:
    state = {"deleted": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/projects" and request.method == "POST":
            return _json_response(
                200,
                {"project_id": "proj-rollback", "name": "rollback", "status": "closed"},
            )
        if request.url.path == "/v2/projects/proj-rollback/open":
            return _json_response(
                200,
                {
                    "project_id": "proj-rollback",
                    "name": "rollback",
                    "status": "opened",
                },
            )
        if request.url.path == "/v2/templates":
            return _json_response(
                200,
                [
                    {
                        "template_id": "tmpl-iosv",
                        "name": "IOSv",
                        "template_type": "qemu",
                    },
                ],
            )
        if request.url.path == "/v2/projects/proj-rollback/templates/tmpl-iosv":
            return httpx.Response(500, text="node create failed")
        if request.url.path == "/v2/projects/proj-rollback" and request.method == "DELETE":
            state["deleted"] = True
            return httpx.Response(204)

        raise AssertionError(f"Unexpected request: {request.method} {request.url.path}")

    topology = TopologySpec(
        project=NetworkProject(name="rollback-topology"),
        devices=[
            {
                "id": "r1",
                "hostname": "R1",
                "type": "router",
                "platform": "iosv",
            },
        ],
    )

    async with GNS3Client(
        base_url="http://gns3.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        orchestrator = GNS3DeploymentOrchestrator(
            GNS3ProjectService(client),
            GNS3NodeService(client, GNS3TemplateResolver(client)),
            GNS3LinkService(client),
        )
        with pytest.raises(GNS3DeploymentError, match="rollback completed"):
            await orchestrator.deploy("rollback", topology)

    assert state["deleted"] is True
