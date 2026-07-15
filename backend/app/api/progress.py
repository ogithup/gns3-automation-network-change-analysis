"""Workflow progress event hub with WebSocket replay support."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any


class ProgressEventHub:
    """Store and broadcast workflow progress events."""

    def __init__(self) -> None:
        self._history: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._queues: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)

    async def publish(self, workflow_id: str, event: dict[str, Any]) -> None:
        self._history[workflow_id].append(event)
        for queue in list(self._queues[workflow_id]):
            await queue.put(event)

    def history(self, workflow_id: str) -> list[dict[str, Any]]:
        return list(self._history.get(workflow_id, []))

    def subscribe(self, workflow_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._queues[workflow_id].append(queue)
        return queue

    def unsubscribe(self, workflow_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        if workflow_id in self._queues and queue in self._queues[workflow_id]:
            self._queues[workflow_id].remove(queue)
