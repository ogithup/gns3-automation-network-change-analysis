"""Console channel abstractions and prompt detection."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Protocol

from app.discovery.exceptions import ConsoleConnectionError
from app.gns3.models import GNS3ConsoleInfo


class ConsoleChannel(Protocol):
    """Minimal async console transport abstraction."""

    async def open(self) -> None:
        """Open the underlying transport."""

    async def write_line(self, line: str) -> None:
        """Write a command followed by a newline."""

    async def read_until_idle(
        self,
        *,
        idle_timeout: float = 0.25,
        max_wait: float = 10.0,
    ) -> str:
        """Read until the channel is idle."""

    async def close(self) -> None:
        """Close the transport."""


@dataclass(slots=True)
class PromptMatch:
    """Detected prompt type and raw prompt text."""

    prompt_type: str
    prompt_text: str


class PromptDetector:
    """Recognize Cisco and VPCS console prompts."""

    _patterns = [
        ("setup_dialog", re.compile(r"Would you like to enter the initial configuration dialog\?")),
        ("config", re.compile(r"(?m)^[A-Za-z0-9_.-]+\((?:config[^\)]*)\)#$")),
        ("privileged", re.compile(r"(?m)^[A-Za-z0-9_.-]+#$")),
        ("vpcs", re.compile(r"(?m)^PC\d*>$")),
        ("user", re.compile(r"(?m)^[A-Za-z0-9_.-]+>$")),
        ("press_return", re.compile(r"Press RETURN to get started!", re.IGNORECASE)),
    ]

    @classmethod
    def detect(cls, text: str) -> PromptMatch | None:
        stripped = text.strip()
        for prompt_type, pattern in cls._patterns:
            matches = pattern.findall(stripped)
            if matches:
                last_match = matches[-1]
                prompt_text = last_match if isinstance(last_match, str) else stripped
                return PromptMatch(prompt_type=prompt_type, prompt_text=prompt_text)

        return None


class TelnetConsoleChannel:
    """Telnet-backed console channel using telnetlib3."""

    def __init__(self, console_info: GNS3ConsoleInfo) -> None:
        self.console_info = console_info
        self._reader: object | None = None
        self._writer: object | None = None

    async def open(self) -> None:
        if not self.console_info.console_host or not self.console_info.console:
            raise ConsoleConnectionError(
                f"Missing console host/port for node '{self.console_info.node_id}'",
            )

        if self.console_info.console_type not in {None, "telnet"}:
            raise ConsoleConnectionError(
                f"Unsupported console type '{self.console_info.console_type}'",
            )

        try:
            import telnetlib3  # type: ignore
        except ImportError as error:
            raise ConsoleConnectionError(
                "telnetlib3 is required for Sprint 6 console sessions",
            ) from error

        self._reader, self._writer = await telnetlib3.open_connection(
            host=self.console_info.console_host,
            port=self.console_info.console,
            connect_minwait=0.05,
            connect_maxwait=1.0,
            shell=None,
        )

    async def write_line(self, line: str) -> None:
        if self._writer is None:
            raise ConsoleConnectionError("Console channel is not open")

        self._writer.write(f"{line}\n")
        await self._writer.drain()

    async def read_until_idle(
        self,
        *,
        idle_timeout: float = 0.25,
        max_wait: float = 10.0,
    ) -> str:
        if self._reader is None:
            raise ConsoleConnectionError("Console channel is not open")

        chunks: list[str] = []
        deadline = time.monotonic() + max_wait

        while time.monotonic() < deadline:
            timeout = idle_timeout if chunks else max_wait
            try:
                chunk = await asyncio.wait_for(self._reader.read(65535), timeout=timeout)
            except TimeoutError:
                break

            if not chunk:
                break

            chunks.append(chunk)

            if PromptDetector.detect("".join(chunks)) is not None:
                try:
                    chunk = await asyncio.wait_for(self._reader.read(65535), timeout=idle_timeout)
                except TimeoutError:
                    break
                if not chunk:
                    break
                chunks.append(chunk)

        return "".join(chunks)

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None
        self._reader = None
