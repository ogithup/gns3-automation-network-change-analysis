"""Typed network change command models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from ipaddress import IPv4Address, IPv4Network
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.exceptions import UnsupportedChangeError
from app.domain.models import ACL, ACLRule, Interface, Route, TopologySpec, VLAN
from app.topology.service import TopologyService


class ChangeDiff(BaseModel):
    """Before/after diff summary for a change command."""

    before: str
    after: str


class NetworkChangeCommand(BaseModel, ABC):
    """Base command for isolated domain changes."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    type: str
    description: str | None = None

    def validate(self, state: TopologySpec) -> None:
        self._validate(state)

    def apply(self, state: TopologySpec) -> TopologySpec:
        self.validate(state)
        updated = state.model_copy(deep=True)
        self._apply(updated)
        TopologySpec.model_validate(updated.model_dump(mode="python"))
        return updated

    def undo(self, state: TopologySpec) -> TopologySpec:
        reverted = state.model_copy(deep=True)
        self._undo(reverted)
        TopologySpec.model_validate(reverted.model_dump(mode="python"))
        return reverted

    def affected_objects(self) -> list[str]:
        return self._affected_objects()

    def config_diff(self, before: TopologySpec, after: TopologySpec) -> ChangeDiff:
        return ChangeDiff(
            before=TopologyService.to_yaml(before),
            after=TopologyService.to_yaml(after),
        )

    def summary(self) -> str:
        return self._summary()

    def serialize(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)

    @abstractmethod
    def _validate(self, state: TopologySpec) -> None: ...

    @abstractmethod
    def _apply(self, state: TopologySpec) -> None: ...

    @abstractmethod
    def _undo(self, state: TopologySpec) -> None: ...

    @abstractmethod
    def _affected_objects(self) -> list[str]: ...

    @abstractmethod
    def _summary(self) -> str: ...


class DeviceInterfaceCommand(NetworkChangeCommand, ABC):
    """Base class for commands targeting a device interface."""

    device: str
    interface: str

    def _get_interface(self, state: TopologySpec) -> Interface:
        device = next((item for item in state.devices if item.id == self.device), None)
        if device is None:
            raise UnsupportedChangeError(f"Device '{self.device}' does not exist.")
        interface = next((item for item in device.interfaces if item.name == self.interface), None)
        if interface is None:
            raise UnsupportedChangeError(
                f"Interface '{self.interface}' does not exist on device '{self.device}'.",
            )
        return interface


class DeleteVLANCommand(NetworkChangeCommand):
    """Delete a VLAN from the isolated topology state."""

    type: Literal["DELETE_VLAN"] = "DELETE_VLAN"
    vlan_id: int
    _removed_vlan: ClassVar[VLAN | None] = None

    def _validate(self, state: TopologySpec) -> None:
        vlan = next((item for item in state.vlans if item.vlan_id == self.vlan_id), None)
        if vlan is None:
            raise UnsupportedChangeError(f"VLAN {self.vlan_id} does not exist.")

    def _apply(self, state: TopologySpec) -> None:
        vlan = next(item for item in state.vlans if item.vlan_id == self.vlan_id)
        type(self)._removed_vlan = vlan.model_copy(deep=True)
        state.vlans = [item for item in state.vlans if item.vlan_id != self.vlan_id]
        state.subnets = [item for item in state.subnets if item.vlan_id != self.vlan_id]
        state.dhcp_pools = [
            item for item in state.dhcp_pools if item.subnet != vlan.subnet
        ]
        state.services = [
            item
            for item in state.services
            if item.vlan_id != self.vlan_id
            and not (
                item.subnet_id is not None
                and item.subnet_id.startswith(f"vlan{self.vlan_id}")
            )
        ]
        for device in state.devices:
            for interface in device.interfaces:
                if interface.access_vlan == self.vlan_id:
                    interface.access_vlan = None
                interface.trunk_vlans = [item for item in interface.trunk_vlans if item != self.vlan_id]
        for endpoint in state.endpoints:
            if endpoint.vlan_id == self.vlan_id:
                endpoint.vlan_id = None
                endpoint.subnet_id = None
                endpoint.default_gateway = None

    def _undo(self, state: TopologySpec) -> None:
        if type(self)._removed_vlan is None:
            raise UnsupportedChangeError("No deleted VLAN state available for undo.")
        state.vlans.append(type(self)._removed_vlan.model_copy(deep=True))

    def _affected_objects(self) -> list[str]:
        return [f"vlan:{self.vlan_id}"]

    def _summary(self) -> str:
        return f"Delete VLAN {self.vlan_id}"


class ChangeAccessVLANCommand(DeviceInterfaceCommand):
    """Change the access VLAN on a switch interface."""

    type: Literal["CHANGE_ACCESS_VLAN"] = "CHANGE_ACCESS_VLAN"
    vlan_id: int
    previous_vlan_id: int | None = None

    def _validate(self, state: TopologySpec) -> None:
        interface = self._get_interface(state)
        if interface.trunk_vlans:
            raise UnsupportedChangeError("Cannot change access VLAN on a trunk interface.")
        if not any(item.vlan_id == self.vlan_id for item in state.vlans):
            raise UnsupportedChangeError(f"VLAN {self.vlan_id} does not exist.")

    def _apply(self, state: TopologySpec) -> None:
        interface = self._get_interface(state)
        self.previous_vlan_id = interface.access_vlan
        interface.access_vlan = self.vlan_id

    def _undo(self, state: TopologySpec) -> None:
        interface = self._get_interface(state)
        interface.access_vlan = self.previous_vlan_id

    def _affected_objects(self) -> list[str]:
        return [self.device, f"interface:{self.device}:{self.interface}", f"vlan:{self.vlan_id}"]

    def _summary(self) -> str:
        return f"Change access VLAN on {self.device}:{self.interface} to VLAN {self.vlan_id}"


class RemoveVLANFromTrunkCommand(DeviceInterfaceCommand):
    """Remove a VLAN from a trunk allowed list."""

    type: Literal["REMOVE_VLAN_FROM_TRUNK"] = "REMOVE_VLAN_FROM_TRUNK"
    vlan_id: int

    def _validate(self, state: TopologySpec) -> None:
        interface = self._get_interface(state)
        if self.vlan_id not in interface.trunk_vlans:
            raise UnsupportedChangeError(
                f"VLAN {self.vlan_id} is not allowed on trunk {self.device}:{self.interface}.",
            )

    def _apply(self, state: TopologySpec) -> None:
        interface = self._get_interface(state)
        interface.trunk_vlans = [item for item in interface.trunk_vlans if item != self.vlan_id]

    def _undo(self, state: TopologySpec) -> None:
        interface = self._get_interface(state)
        if self.vlan_id not in interface.trunk_vlans:
            interface.trunk_vlans.append(self.vlan_id)
            interface.trunk_vlans.sort()

    def _affected_objects(self) -> list[str]:
        return [self.device, f"interface:{self.device}:{self.interface}", f"vlan:{self.vlan_id}"]

    def _summary(self) -> str:
        return f"Remove VLAN {self.vlan_id} from trunk {self.device}:{self.interface}"


class AddVLANToTrunkCommand(DeviceInterfaceCommand):
    """Add a VLAN to a trunk allowed list."""

    type: Literal["ADD_VLAN_TO_TRUNK"] = "ADD_VLAN_TO_TRUNK"
    vlan_id: int

    def _validate(self, state: TopologySpec) -> None:
        interface = self._get_interface(state)
        if self.vlan_id in interface.trunk_vlans:
            raise UnsupportedChangeError(
                f"VLAN {self.vlan_id} is already present on trunk {self.device}:{self.interface}.",
            )
        if not any(item.vlan_id == self.vlan_id for item in state.vlans):
            raise UnsupportedChangeError(f"VLAN {self.vlan_id} does not exist.")

    def _apply(self, state: TopologySpec) -> None:
        interface = self._get_interface(state)
        interface.trunk_vlans.append(self.vlan_id)
        interface.trunk_vlans.sort()

    def _undo(self, state: TopologySpec) -> None:
        interface = self._get_interface(state)
        interface.trunk_vlans = [item for item in interface.trunk_vlans if item != self.vlan_id]

    def _affected_objects(self) -> list[str]:
        return [self.device, f"interface:{self.device}:{self.interface}", f"vlan:{self.vlan_id}"]

    def _summary(self) -> str:
        return f"Add VLAN {self.vlan_id} to trunk {self.device}:{self.interface}"


class ShutdownInterfaceCommand(DeviceInterfaceCommand):
    """Administratively disable an interface."""

    type: Literal["SHUTDOWN_INTERFACE"] = "SHUTDOWN_INTERFACE"

    def _validate(self, state: TopologySpec) -> None:
        interface = self._get_interface(state)
        if not interface.enabled:
            raise UnsupportedChangeError(f"Interface {self.device}:{self.interface} is already shutdown.")

    def _apply(self, state: TopologySpec) -> None:
        self._get_interface(state).enabled = False

    def _undo(self, state: TopologySpec) -> None:
        self._get_interface(state).enabled = True

    def _affected_objects(self) -> list[str]:
        return [self.device, f"interface:{self.device}:{self.interface}"]

    def _summary(self) -> str:
        return f"Shutdown interface {self.device}:{self.interface}"


class EnableInterfaceCommand(DeviceInterfaceCommand):
    """Administratively enable an interface."""

    type: Literal["ENABLE_INTERFACE"] = "ENABLE_INTERFACE"

    def _validate(self, state: TopologySpec) -> None:
        interface = self._get_interface(state)
        if interface.enabled:
            raise UnsupportedChangeError(f"Interface {self.device}:{self.interface} is already enabled.")

    def _apply(self, state: TopologySpec) -> None:
        self._get_interface(state).enabled = True

    def _undo(self, state: TopologySpec) -> None:
        self._get_interface(state).enabled = False

    def _affected_objects(self) -> list[str]:
        return [self.device, f"interface:{self.device}:{self.interface}"]

    def _summary(self) -> str:
        return f"Enable interface {self.device}:{self.interface}"


class ChangeGatewayCommand(NetworkChangeCommand):
    """Change the gateway for a VLAN and its endpoints."""

    type: Literal["CHANGE_GATEWAY"] = "CHANGE_GATEWAY"
    vlan_id: int
    gateway: IPv4Address
    previous_gateway: IPv4Address | None = None

    def _validate(self, state: TopologySpec) -> None:
        vlan = next((item for item in state.vlans if item.vlan_id == self.vlan_id), None)
        if vlan is None or vlan.subnet is None:
            raise UnsupportedChangeError(f"VLAN {self.vlan_id} does not exist or has no subnet.")
        if self.gateway not in vlan.subnet:
            raise UnsupportedChangeError(f"Gateway {self.gateway} is outside VLAN {self.vlan_id} subnet.")

    def _apply(self, state: TopologySpec) -> None:
        vlan = next(item for item in state.vlans if item.vlan_id == self.vlan_id)
        self.previous_gateway = vlan.gateway
        vlan.gateway = self.gateway
        for subnet in state.subnets:
            if subnet.vlan_id == self.vlan_id:
                subnet.gateway = self.gateway
        for endpoint in state.endpoints:
            if endpoint.vlan_id == self.vlan_id:
                endpoint.default_gateway = self.gateway

    def _undo(self, state: TopologySpec) -> None:
        vlan = next(item for item in state.vlans if item.vlan_id == self.vlan_id)
        vlan.gateway = self.previous_gateway
        for subnet in state.subnets:
            if subnet.vlan_id == self.vlan_id:
                subnet.gateway = self.previous_gateway
        for endpoint in state.endpoints:
            if endpoint.vlan_id == self.vlan_id:
                endpoint.default_gateway = self.previous_gateway

    def _affected_objects(self) -> list[str]:
        return [f"vlan:{self.vlan_id}", f"gateway:{self.gateway}"]

    def _summary(self) -> str:
        return f"Change gateway of VLAN {self.vlan_id} to {self.gateway}"


class AddStaticRouteCommand(NetworkChangeCommand):
    """Add a static route entry."""

    type: Literal["ADD_STATIC_ROUTE"] = "ADD_STATIC_ROUTE"
    route_id: str
    device: str
    destination: IPv4Network
    next_hop: IPv4Address | None = None
    outgoing_interface: str | None = None

    def _validate(self, state: TopologySpec) -> None:
        if any(item.id == self.route_id for item in state.routes):
            raise UnsupportedChangeError(f"Route '{self.route_id}' already exists.")
        if not any(item.id == self.device for item in state.devices):
            raise UnsupportedChangeError(f"Device '{self.device}' does not exist.")

    def _apply(self, state: TopologySpec) -> None:
        state.routes.append(
            Route(
                id=self.route_id,
                device_id=self.device,
                destination=self.destination,
                next_hop=self.next_hop,
                outgoing_interface=self.outgoing_interface,
                protocol="static",
            ),
        )

    def _undo(self, state: TopologySpec) -> None:
        state.routes = [item for item in state.routes if item.id != self.route_id]

    def _affected_objects(self) -> list[str]:
        return [self.device, f"route:{self.route_id}"]

    def _summary(self) -> str:
        return f"Add static route {self.destination} on {self.device}"


class RemoveStaticRouteCommand(NetworkChangeCommand):
    """Remove a static route entry."""

    type: Literal["REMOVE_STATIC_ROUTE"] = "REMOVE_STATIC_ROUTE"
    route_id: str
    _removed_route: ClassVar[Route | None] = None

    def _validate(self, state: TopologySpec) -> None:
        if not any(item.id == self.route_id for item in state.routes):
            raise UnsupportedChangeError(f"Route '{self.route_id}' does not exist.")

    def _apply(self, state: TopologySpec) -> None:
        route = next(item for item in state.routes if item.id == self.route_id)
        type(self)._removed_route = route.model_copy(deep=True)
        state.routes = [item for item in state.routes if item.id != self.route_id]

    def _undo(self, state: TopologySpec) -> None:
        if type(self)._removed_route is None:
            raise UnsupportedChangeError("No removed route state available for undo.")
        state.routes.append(type(self)._removed_route.model_copy(deep=True))

    def _affected_objects(self) -> list[str]:
        return [f"route:{self.route_id}"]

    def _summary(self) -> str:
        return f"Remove static route {self.route_id}"


class AddACLRuleCommand(NetworkChangeCommand):
    """Add a rule to an existing ACL."""

    type: Literal["ADD_ACL_RULE"] = "ADD_ACL_RULE"
    acl_id: str
    rule_id: str
    action: Literal["permit", "deny"]
    protocol: Literal["ip", "icmp", "tcp", "udp"] = "ip"
    source: str
    destination: str
    source_port: str | None = None
    destination_port: str | None = None

    def _validate(self, state: TopologySpec) -> None:
        acl = next((item for item in state.acls if item.id == self.acl_id), None)
        if acl is None:
            raise UnsupportedChangeError(f"ACL '{self.acl_id}' does not exist.")
        if any(item.id == self.rule_id for item in acl.rules):
            raise UnsupportedChangeError(f"ACL rule '{self.rule_id}' already exists.")

    def _apply(self, state: TopologySpec) -> None:
        acl = next(item for item in state.acls if item.id == self.acl_id)
        acl.rules.append(
            ACLRule(
                id=self.rule_id,
                action=self.action,
                protocol=self.protocol,
                source=self.source,
                destination=self.destination,
                source_port=self.source_port,
                destination_port=self.destination_port,
            ),
        )

    def _undo(self, state: TopologySpec) -> None:
        acl = next(item for item in state.acls if item.id == self.acl_id)
        acl.rules = [item for item in acl.rules if item.id != self.rule_id]

    def _affected_objects(self) -> list[str]:
        return [f"acl:{self.acl_id}", f"acl-rule:{self.rule_id}"]

    def _summary(self) -> str:
        return f"Add ACL rule {self.rule_id} to {self.acl_id}"


class RemoveACLRuleCommand(NetworkChangeCommand):
    """Remove a rule from an ACL."""

    type: Literal["REMOVE_ACL_RULE"] = "REMOVE_ACL_RULE"
    acl_id: str
    rule_id: str
    _removed_rule: ClassVar[ACLRule | None] = None

    def _validate(self, state: TopologySpec) -> None:
        acl = next((item for item in state.acls if item.id == self.acl_id), None)
        if acl is None:
            raise UnsupportedChangeError(f"ACL '{self.acl_id}' does not exist.")
        if not any(item.id == self.rule_id for item in acl.rules):
            raise UnsupportedChangeError(f"ACL rule '{self.rule_id}' does not exist.")

    def _apply(self, state: TopologySpec) -> None:
        acl = next(item for item in state.acls if item.id == self.acl_id)
        rule = next(item for item in acl.rules if item.id == self.rule_id)
        type(self)._removed_rule = rule.model_copy(deep=True)
        acl.rules = [item for item in acl.rules if item.id != self.rule_id]

    def _undo(self, state: TopologySpec) -> None:
        if type(self)._removed_rule is None:
            raise UnsupportedChangeError("No removed ACL rule state available for undo.")
        acl = next(item for item in state.acls if item.id == self.acl_id)
        acl.rules.append(type(self)._removed_rule.model_copy(deep=True))

    def _affected_objects(self) -> list[str]:
        return [f"acl:{self.acl_id}", f"acl-rule:{self.rule_id}"]

    def _summary(self) -> str:
        return f"Remove ACL rule {self.rule_id} from {self.acl_id}"
