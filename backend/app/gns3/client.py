"""Asynchronous GNS3 API client."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.core.config import get_settings
from app.gns3.exceptions import (
    GNS3ConnectionError,
    GNS3RequestError,
    GNS3ResourceNotFoundError,
)
from app.gns3.models import (
    GNS3ConsoleInfo,
    GNS3Link,
    GNS3LinkCreateRequest,
    GNS3Node,
    GNS3NodeCreateRequest,
    GNS3NodeUpdateRequest,
    GNS3Project,
    GNS3ProjectCreateRequest,
    GNS3Template,
    GNS3Version,
)


class GNS3Client:
    """Reusable async client for the GNS3 REST API."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout: float | None = None,
        retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        self._base_url = (base_url or settings.gns3_server_url).rstrip("/")
        self._timeout = timeout or settings.gns3_request_timeout
        self._retries = max(retries, 0)
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> GNS3Client:
        await self.start()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.aclose()

    async def start(self) -> None:
        if self._client is not None:
            return

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=self._transport,
        )

    async def aclose(self) -> None:
        if self._client is None:
            return

        await self._client.aclose()
        self._client = None

    async def get_version(self) -> GNS3Version:
        data = await self._request("GET", "/v2/version")
        return GNS3Version.model_validate(data)

    async def list_projects(self) -> list[GNS3Project]:
        data = await self._request("GET", "/v2/projects")
        return [GNS3Project.model_validate(item) for item in data]

    async def create_project(self, request: GNS3ProjectCreateRequest) -> GNS3Project:
        data = await self._request(
            "POST",
            "/v2/projects",
            json=request.model_dump(exclude_none=True),
        )
        return GNS3Project.model_validate(data)

    async def open_project(self, project_id: str) -> GNS3Project:
        data = await self._request("POST", f"/v2/projects/{project_id}/open")
        return GNS3Project.model_validate(data)

    async def close_project(self, project_id: str) -> GNS3Project:
        data = await self._request("POST", f"/v2/projects/{project_id}/close")
        return GNS3Project.model_validate(data)

    async def delete_project(self, project_id: str) -> None:
        await self._request("DELETE", f"/v2/projects/{project_id}")

    async def list_templates(self) -> list[GNS3Template]:
        data = await self._request("GET", "/v2/templates")
        return [GNS3Template.model_validate(item) for item in data]

    async def create_node(
        self,
        project_id: str,
        template_id: str,
        request: GNS3NodeCreateRequest,
    ) -> GNS3Node:
        data = await self._request(
            "POST",
            f"/v2/projects/{project_id}/templates/{template_id}",
            json=request.model_dump(exclude_none=True),
        )
        return GNS3Node.model_validate(data)

    async def update_node_position(
        self,
        project_id: str,
        node_id: str,
        request: GNS3NodeUpdateRequest,
    ) -> GNS3Node:
        data = await self._request(
            "PUT",
            f"/v2/projects/{project_id}/nodes/{node_id}",
            json=request.model_dump(exclude_none=True),
        )
        return GNS3Node.model_validate(data)

    async def start_node(self, project_id: str, node_id: str) -> GNS3Node:
        data = await self._request(
            "POST",
            f"/v2/projects/{project_id}/nodes/{node_id}/start",
        )
        return GNS3Node.model_validate(data)

    async def stop_node(self, project_id: str, node_id: str) -> GNS3Node:
        data = await self._request(
            "POST",
            f"/v2/projects/{project_id}/nodes/{node_id}/stop",
        )
        return GNS3Node.model_validate(data)

    async def create_link(
        self,
        project_id: str,
        request: GNS3LinkCreateRequest,
    ) -> GNS3Link:
        payload = {
            "nodes": [
                endpoint.model_dump(exclude_none=True)
                for endpoint in request.endpoints
            ],
        }
        data = await self._request(
            "POST",
            f"/v2/projects/{project_id}/links",
            json=payload,
        )
        return GNS3Link.model_validate(data)

    async def get_node(self, project_id: str, node_id: str) -> GNS3Node:
        data = await self._request("GET", f"/v2/projects/{project_id}/nodes/{node_id}")
        return GNS3Node.model_validate(data)

    async def get_node_console(
        self,
        project_id: str,
        node_id: str,
    ) -> GNS3ConsoleInfo:
        node = await self.get_node(project_id, node_id)
        return GNS3ConsoleInfo(
            node_id=node.node_id,
            console_host=node.console_host,
            console=node.console,
            console_type=node.console_type,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> Any:
        if self._client is None:
            await self.start()
        assert self._client is not None

        attempts = self._retries + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = await self._client.request(method, path, json=json)
                return self._handle_response(response)
            except (httpx.ConnectError, httpx.TimeoutException) as error:
                last_error = error
                if attempt >= attempts:
                    break
                await asyncio.sleep(0.2 * attempt)

        raise GNS3ConnectionError(
            f"Unable to reach GNS3 server at {self._base_url}",
        ) from last_error

    @staticmethod
    def _handle_response(response: httpx.Response) -> Any:
        if response.status_code == 404:
            raise GNS3ResourceNotFoundError(
                f"GNS3 resource not found for {response.request.method} {response.request.url}",
            )

        if response.is_error:
            raise GNS3RequestError(
                f"GNS3 request failed with status {response.status_code}: {response.text}",
            )

        if not response.content:
            return None

        return response.json()

