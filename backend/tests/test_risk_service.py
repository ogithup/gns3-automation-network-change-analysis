"""Sprint 11 risk scoring tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.changes.models import DeleteVLANCommand, EnableInterfaceCommand, RemoveACLRuleCommand
from app.risk.service import RiskScoringService
from app.simulation.service import SimulationService
from app.topology.service import TopologyService


def _load(name: str):
    return TopologyService.load_file(Path("..") / "examples" / name)


@pytest.mark.asyncio
async def test_vlan_delete_scores_critical_risk() -> None:
    topology = _load("three-vlan-office.yaml")
    simulation = await SimulationService().simulate_change(
        topology,
        DeleteVLANCommand(vlan_id=30),
    )

    assessment = RiskScoringService().assess_change(topology, simulation)

    assert assessment.risk_level == "Critical"
    assert assessment.recommendation == "Do not apply"
    assert assessment.total_score >= 75
    assert any("Critical service 'Guest DHCP'" in item for item in assessment.explanation)


@pytest.mark.asyncio
async def test_acl_change_scores_lower_than_vlan_delete() -> None:
    topology = _load("guest-isolation.yaml")
    simulation = await SimulationService().simulate_change(
        topology,
        RemoveACLRuleCommand(acl_id="guest-isolation", rule_id="deny-guest-admin"),
    )

    assessment = RiskScoringService().assess_change(topology, simulation)

    assert assessment.total_score < 75
    assert assessment.risk_level in {"Medium", "High"}
    assert any(
        factor.factor == "affected_critical_services" and factor.contribution > 0
        for factor in assessment.factor_scores
    )


@pytest.mark.asyncio
async def test_enable_interface_can_score_low_risk() -> None:
    topology = _load("three-vlan-office.yaml")
    topology.devices[0].interfaces[0].enabled = False
    simulation = await SimulationService().simulate_change(
        topology,
        EnableInterfaceCommand(device="r1", interface="GigabitEthernet0/0"),
    )

    assessment = RiskScoringService().assess_change(topology, simulation)

    assert assessment.risk_level == "Low"
    assert assessment.recommendation == "Safe to apply"
    assert assessment.total_score < 25
