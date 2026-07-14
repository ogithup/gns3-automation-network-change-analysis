"""Service layer for GNS3 resource management."""

from __future__ import annotations

from app.domain.models import TopologySpec
from app.gns3.client import GNS3Client
from app.gns3.exceptions import GNS3DeploymentError, GNS3TemplateNotFoundError
from app.gns3.models import (
    GNS3DeploymentPlan,
    GNS3DeploymentResult,
    GNS3DomainNodeMapping,
    GNS3Link,
    GNS3LinkCreateRequest,
    GNS3LinkDeploymentRequest,
    GNS3LinkEndpoint,
    GNS3Node,
    GNS3NodeCreateRequest,
    GNS3NodeDeploymentRequest,
    GNS3Project,
    GNS3ProjectCreateRequest,
    GNS3Template,
)


class GNS3ProjectService:
    """Project lifecycle operations."""

    def __init__(self, client: GNS3Client) -> None:
        self.client = client

    async def create(self, name: str) -> GNS3Project:
        return await self.client.create_project(GNS3ProjectCreateRequest(name=name))

    async def open(self, project_id: str) -> GNS3Project:
        return await self.client.open_project(project_id)

    async def close(self, project_id: str) -> GNS3Project:
        return await self.client.close_project(project_id)

    async def delete(self, project_id: str) -> None:
        await self.client.delete_project(project_id)

    async def list(self) -> list[GNS3Project]:
        return await self.client.list_projects()


class GNS3TemplateResolver:
    """Resolve logical platform names to concrete GNS3 templates."""

    def __init__(self, client: GNS3Client) -> None:
        self.client = client
        self._aliases = {
            "iosv": ["IOSv", "iosv"],
            "iosvl2": ["IOSvL2", "iosvl2"],
            "vpcs": ["VPCS", "vpcs"],
            "ethernet_switch": ["Ethernet switch", "ethernet_switch"],
            "c2691": ["c2691"],
        }

    async def list_templates(self) -> list[GNS3Template]:
        return await self.client.list_templates()

    async def resolve(self, platform: str) -> GNS3Template:
        templates = await self.list_templates()
        aliases = self._aliases.get(platform.lower(), [platform])

        for alias in aliases:
            for template in templates:
                if template.name == alias:
                    return template

        raise GNS3TemplateNotFoundError(
            f"No GNS3 template found for logical platform '{platform}'",
        )


class GNS3NodeService:
    """Node operations and domain-to-GNS3 mapping support."""

    def __init__(
        self,
        client: GNS3Client,
        template_resolver: GNS3TemplateResolver,
    ) -> None:
        self.client = client
        self.template_resolver = template_resolver

    async def create(
        self,
        project_id: str,
        request: GNS3NodeDeploymentRequest,
    ) -> tuple[GNS3Node, GNS3DomainNodeMapping]:
        template = await self.template_resolver.resolve(request.platform)
        node = await self.client.create_node(
            project_id,
            template.template_id,
            GNS3NodeCreateRequest(
                name=request.name,
                x=request.x,
                y=request.y,
                properties=request.properties,
            ),
        )
        return node, GNS3DomainNodeMapping(
            domain_device_id=request.domain_device_id,
            gns3_node_id=node.node_id,
            template_id=template.template_id,
            name=node.name,
        )

    async def start(self, project_id: str, node_id: str) -> GNS3Node:
        return await self.client.start_node(project_id, node_id)

    async def stop(self, project_id: str, node_id: str) -> GNS3Node:
        return await self.client.stop_node(project_id, node_id)


class GNS3LinkService:
    """Link operations between created nodes."""

    def __init__(self, client: GNS3Client) -> None:
        self.client = client

    async def create(
        self,
        project_id: str,
        request: GNS3LinkDeploymentRequest,
        mapping_by_domain_id: dict[str, GNS3DomainNodeMapping],
    ) -> GNS3Link:
        source_mapping = mapping_by_domain_id[request.source_domain_device_id]
        target_mapping = mapping_by_domain_id[request.target_domain_device_id]
        return await self.client.create_link(
            project_id,
            GNS3LinkCreateRequest(
                endpoints=[
                    GNS3LinkEndpoint(
                        node_id=source_mapping.gns3_node_id,
                        adapter_number=request.source_adapter_number,
                        port_number=request.source_port_number,
                    ),
                    GNS3LinkEndpoint(
                        node_id=target_mapping.gns3_node_id,
                        adapter_number=request.target_adapter_number,
                        port_number=request.target_port_number,
                    ),
                ],
            ),
        )


class GNS3DeploymentOrchestrator:
    """Create projects and resources with rollback on partial failures."""

    def __init__(
        self,
        project_service: GNS3ProjectService,
        node_service: GNS3NodeService,
        link_service: GNS3LinkService,
    ) -> None:
        self.project_service = project_service
        self.node_service = node_service
        self.link_service = link_service

    def build_dry_run_plan(
        self,
        project_name: str,
        topology: TopologySpec,
        *,
        link_requests: list[GNS3LinkDeploymentRequest] | None = None,
    ) -> GNS3DeploymentPlan:
        return GNS3DeploymentPlan(
            project_name=project_name,
            nodes=[
                GNS3NodeDeploymentRequest(
                    domain_device_id=device.id,
                    name=device.hostname,
                    platform=device.platform,
                )
                for device in topology.devices
            ],
            links=link_requests or [],
        )

    async def deploy(
        self,
        project_name: str,
        topology: TopologySpec,
        *,
        link_requests: list[GNS3LinkDeploymentRequest] | None = None,
    ) -> GNS3DeploymentResult:
        project = await self.project_service.create(project_name)
        created_project_id = project.project_id
        node_mappings: list[GNS3DomainNodeMapping] = []
        links: list[GNS3Link] = []

        try:
            project = await self.project_service.open(created_project_id)

            for device in topology.devices:
                _, mapping = await self.node_service.create(
                    created_project_id,
                    GNS3NodeDeploymentRequest(
                        domain_device_id=device.id,
                        name=device.hostname,
                        platform=device.platform,
                    ),
                )
                node_mappings.append(mapping)

            mapping_by_domain_id = {
                mapping.domain_device_id: mapping
                for mapping in node_mappings
            }

            for link_request in link_requests or []:
                link = await self.link_service.create(
                    created_project_id,
                    link_request,
                    mapping_by_domain_id,
                )
                links.append(link)

            return GNS3DeploymentResult(
                project=project,
                node_mappings=node_mappings,
                links=links,
            )
        except Exception as error:
            try:
                await self.project_service.delete(created_project_id)
            except Exception as cleanup_error:
                raise GNS3DeploymentError(
                    f"Deployment failed and cleanup also failed: {cleanup_error}",
                ) from error

            raise GNS3DeploymentError(
                f"Deployment failed and rollback completed: {error}",
            ) from error
