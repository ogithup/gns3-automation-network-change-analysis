"""Optional real GNS3 connectivity test."""

from __future__ import annotations

import os

import httpx
import pytest


pytestmark = pytest.mark.skipif(
    not os.getenv("NETTWIN_RUN_REAL_GNS3"),
    reason="Set NETTWIN_RUN_REAL_GNS3=1 to execute live GNS3 connectivity tests.",
)


def test_real_gns3_version_endpoint() -> None:
    server_url = os.getenv("GNS3_SERVER_URL", "http://[::1]:3080")
    response = httpx.get(f"{server_url}/v2/version", timeout=5.0)
    response.raise_for_status()
    payload = response.json()
    assert "version" in payload
