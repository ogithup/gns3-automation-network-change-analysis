"""Sprint 9 change command tests."""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network
from pathlib import Path

import pytest

from app.changes.models import (
    AddACLRuleCommand,
    AddStaticRouteCommand,
    AddVLANToTrunkCommand,
    ChangeAccessVLANCommand,
    ChangeGatewayCommand,
    RemoveACLRuleCommand,
    RemoveStaticRouteCommand,
    RemoveVLANFromTrunkCommand,
    ShutdownInterfaceCommand,
)
from app.changes.service import ChangeService
from app.domain.exceptions import UnsupportedChangeError
from app.topology.service import TopologyService


def _load(name: str):
    return TopologyService.load_file(Path("..") / "examples" / name)


def test_change_access_vlan_apply_and_undo() -> None:
    topology = _load("three-vlan-office.yaml")
    command = ChangeAccessVLANCommand(device="sw1", interface="GigabitEthernet0/4", vlan_id=20)

    updated = command.apply(topology)
    reverted = command.undo(updated)

    assert next(i for d in updated.devices if d.id == "sw1" for i in d.interfaces if i.name == "GigabitEthernet0/4").access_vlan == 20
    assert next(i for d in reverted.devices if d.id == "sw1" for i in d.interfaces if i.name == "GigabitEthernet0/4").access_vlan == 30


def test_remove_vlan_from_trunk_and_undo() -> None:
    topology = _load("three-vlan-office.yaml")
    command = RemoveVLANFromTrunkCommand(device="sw1", interface="GigabitEthernet0/1", vlan_id=30)

    updated = command.apply(topology)
    reverted = command.undo(updated)

    trunk = next(i for d in updated.devices if d.id == "sw1" for i in d.interfaces if i.name == "GigabitEthernet0/1")
    trunk_reverted = next(i for d in reverted.devices if d.id == "sw1" for i in d.interfaces if i.name == "GigabitEthernet0/1")
    assert trunk.trunk_vlans == [10, 20]
    assert trunk_reverted.trunk_vlans == [10, 20, 30]


def test_shutdown_interface_and_invalid_repeat() -> None:
    topology = _load("three-vlan-office.yaml")
    command = ShutdownInterfaceCommand(device="r1", interface="GigabitEthernet0/0.30")
    updated = command.apply(topology)

    assert next(i for d in updated.devices if d.id == "r1" for i in d.interfaces if i.name == "GigabitEthernet0/0.30").enabled is False

    with pytest.raises(UnsupportedChangeError):
        command.apply(updated)


def test_change_gateway_updates_vlan_subnet_and_endpoints() -> None:
    topology = _load("guest-isolation.yaml")
    command = ChangeGatewayCommand(vlan_id=30, gateway=IPv4Address("172.16.30.254"))

    updated = command.apply(topology)

    vlan = next(item for item in updated.vlans if item.vlan_id == 30)
    endpoint = next(item for item in updated.endpoints if item.id == "guest-endpoint-1")
    assert vlan.gateway == IPv4Address("172.16.30.254")
    assert endpoint.default_gateway == IPv4Address("172.16.30.254")


def test_add_and_remove_static_route() -> None:
    topology = _load("three-vlan-office.yaml")
    add_command = AddStaticRouteCommand(
        route_id="admin-default",
        device="r1",
        destination=IPv4Network("10.10.10.0/24"),
        next_hop=IPv4Address("10.0.0.2"),
    )
    updated = add_command.apply(topology)
    remove_command = RemoveStaticRouteCommand(route_id="admin-default")
    removed = remove_command.apply(updated)
    restored = remove_command.undo(removed)

    assert any(item.id == "admin-default" for item in updated.routes)
    assert all(item.id != "admin-default" for item in removed.routes)
    assert any(item.id == "admin-default" for item in restored.routes)


def test_add_and_remove_acl_rule() -> None:
    topology = _load("guest-isolation.yaml")
    add_command = AddACLRuleCommand(
        acl_id="guest-isolation",
        rule_id="deny-guest-gateway",
        action="deny",
        source="172.16.30.0/24",
        destination="172.16.10.1/32",
    )
    updated = add_command.apply(topology)
    remove_command = RemoveACLRuleCommand(acl_id="guest-isolation", rule_id="deny-guest-gateway")
    removed = remove_command.apply(updated)
    restored = remove_command.undo(removed)

    acl = next(item for item in updated.acls if item.id == "guest-isolation")
    assert any(rule.id == "deny-guest-gateway" for rule in acl.rules)
    assert all(rule.id != "deny-guest-gateway" for rule in next(item for item in removed.acls if item.id == "guest-isolation").rules)
    assert any(rule.id == "deny-guest-gateway" for rule in next(item for item in restored.acls if item.id == "guest-isolation").rules)


def test_preview_returns_diff_and_summary() -> None:
    topology = _load("three-vlan-office.yaml")
    command = AddVLANToTrunkCommand(device="sw1", interface="GigabitEthernet0/1", vlan_id=30)

    with pytest.raises(UnsupportedChangeError):
        command.apply(topology)

    valid_command = ChangeAccessVLANCommand(device="sw1", interface="GigabitEthernet0/4", vlan_id=20)
    preview = ChangeService.preview(valid_command, topology)

    assert "Change access VLAN" in preview["summary"]
    assert "GigabitEthernet0/4" in preview["diff"].before
    assert "access_vlan: 20" in preview["diff"].after
