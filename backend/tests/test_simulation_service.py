"""Sprint 10 simulation and impact analysis tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.changes.models import (
    DeleteVLANCommand,
    RemoveACLRuleCommand,
    RemoveStaticRouteCommand,
    RemoveVLANFromTrunkCommand,
    ShutdownInterfaceCommand,
)
from app.simulation.service import SimulationService
from app.topology.service import TopologyService


def _load(name: str):
    return TopologyService.load_file(Path("..") / "examples" / name)


@pytest.mark.asyncio
async def test_simulation_detects_vlan_delete_impact() -> None:
    topology = _load("three-vlan-office.yaml")
    command = DeleteVLANCommand(vlan_id=30)

    result = await SimulationService().simulate_change(topology, command)

    assert any(item == "vlan:30" for item in result.direct_impacts)
    assert result.impact.changed_validation_tests
    assert any("endpoint:guest-endpoint" in item for item in result.indirect_impacts)


@pytest.mark.asyncio
async def test_simulation_detects_trunk_vlan_removal_impact() -> None:
    topology = _load("three-vlan-office.yaml")
    command = RemoveVLANFromTrunkCommand(device="sw1", interface="GigabitEthernet0/1", vlan_id=30)

    result = await SimulationService().simulate_change(topology, command)

    assert "interface:sw1:GigabitEthernet0/1" in result.direct_impacts
    assert "vlan:30" in result.impact.affected_vlans


@pytest.mark.asyncio
async def test_simulation_detects_interface_shutdown_impact() -> None:
    topology = _load("three-vlan-office.yaml")
    command = ShutdownInterfaceCommand(device="r1", interface="GigabitEthernet0/0.30")

    result = await SimulationService().simulate_change(topology, command)

    assert "interface:r1:GigabitEthernet0/0.30" in result.direct_impacts
    assert result.impact.changed_validation_tests


@pytest.mark.asyncio
async def test_simulation_detects_route_removal_impact() -> None:
    topology = _load("three-vlan-office.yaml")
    command = RemoveStaticRouteCommand(route_id="guest-default")

    result = await SimulationService().simulate_change(topology, command)

    assert "route:guest-default" in result.direct_impacts
    assert isinstance(result.impact.redundancy_available, bool)


@pytest.mark.asyncio
async def test_simulation_detects_acl_change_impact() -> None:
    topology = _load("guest-isolation.yaml")
    command = RemoveACLRuleCommand(acl_id="guest-isolation", rule_id="deny-guest-admin")

    result = await SimulationService().simulate_change(topology, command)

    assert any(item.startswith("acl:") for item in result.direct_impacts)
    assert result.before_results[0].predicted_reachable is False
    assert result.after_results[0].predicted_reachable is True
