"""Sprint 8 reachability and validation tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.topology.service import TopologyService
from app.validation.models import RuntimeValidationResult
from app.validation.service import ValidationService


@pytest.mark.asyncio
async def test_validation_service_predicts_reachable_and_runtime_match() -> None:
    topology = TopologyService.load_file(Path("..") / "examples" / "three-vlan-office.yaml")

    async def runtime_validator(topology, source, target):
        _ = (topology, source, target)
        return RuntimeValidationResult(
            reachable=True,
            traceroute_path=["192.168.10.1", "192.168.20.10"],
            technical_explanation="Ping and traceroute succeeded in GNS3.",
        )

    result = await ValidationService(runtime_validator=runtime_validator).validate_connectivity(
        topology,
        source_endpoint_id="admin-endpoint",
        target_endpoint_id="student-endpoint",
    )

    assert result.predicted_reachable is True
    assert result.actual_reachable is True
    assert result.state == "MATCH"
    assert result.failure_stage is None


@pytest.mark.asyncio
async def test_validation_service_predicts_acl_block() -> None:
    topology = TopologyService.load_file(Path("..") / "examples" / "guest-isolation.yaml")

    result = await ValidationService().validate_connectivity(
        topology,
        source_endpoint_id="guest-endpoint-1",
        target_endpoint_id="admin-endpoint",
    )

    assert result.predicted_reachable is False
    assert result.failure_stage == "acl_evaluation"
    assert any(item.matched and item.action == "deny" for item in result.evaluated_acls)


@pytest.mark.asyncio
async def test_validation_service_reports_model_runtime_mismatch() -> None:
    topology = TopologyService.load_file(Path("..") / "examples" / "three-vlan-office.yaml")

    async def runtime_validator(topology, source, target):
        _ = (topology, source, target)
        return RuntimeValidationResult(
            reachable=False,
            technical_explanation="Runtime ping failed although model expected success.",
        )

    result = await ValidationService(runtime_validator=runtime_validator).validate_connectivity(
        topology,
        source_endpoint_id="admin-endpoint",
        target_endpoint_id="student-endpoint",
    )

    assert result.predicted_reachable is True
    assert result.actual_reachable is False
    assert result.state == "MODEL_RUNTIME_MISMATCH"
    assert result.suspected_reason is not None
