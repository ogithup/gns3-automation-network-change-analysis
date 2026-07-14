"""Adapter-based parsers for CLI discovery outputs."""

from __future__ import annotations

import re

from app.discovery.models import (
    DiscoveredACL,
    DiscoveredDeviceState,
    DiscoveredOSPFNeighbor,
    DiscoveredRoute,
    DiscoveredTrunk,
    DiscoveredVLAN,
    InterfaceOperationalState,
)
from app.gns3.models import GNS3ConsoleInfo


class DiscoveryParserRegistry:
    """Parse collected CLI output into structured state."""

    def parse_device(
        self,
        *,
        device_id: str,
        hostname: str,
        platform: str,
        console: GNS3ConsoleInfo,
        raw_outputs: dict[str, str],
    ) -> DiscoveredDeviceState:
        return DiscoveredDeviceState(
            device_id=device_id,
            hostname=hostname,
            platform=platform,
            console=console,
            running_config=raw_outputs.get("show running-config"),
            interfaces=self.parse_ip_interface_brief(raw_outputs.get("show ip interface brief", "")),
            vlans=self.parse_vlan_brief(raw_outputs.get("show vlan brief", "")),
            trunk_vlans=self.parse_interfaces_trunk(raw_outputs.get("show interfaces trunk", "")),
            routes=self.parse_ip_route(raw_outputs.get("show ip route", "")),
            acls=self.parse_access_lists(raw_outputs.get("show access-lists", "")),
            ospf_neighbors=self.parse_ospf_neighbors(raw_outputs.get("show ip ospf neighbor", "")),
            raw_outputs=raw_outputs,
        )

    @staticmethod
    def parse_ip_interface_brief(output: str) -> list[InterfaceOperationalState]:
        states: list[InterfaceOperationalState] = []
        pattern = re.compile(
            r"^(?P<name>\S+)\s+(?P<ip>\S+)\s+\S+\s+\S+\s+(?P<status>administratively down|up|down)\s+(?P<protocol>up|down)$",
        )
        for line in output.splitlines():
            match = pattern.match(line.strip())
            if not match:
                continue
            ip_address = match.group("ip")
            states.append(
                InterfaceOperationalState(
                    name=match.group("name"),
                    ip_address=None if ip_address == "unassigned" else ip_address,
                    status=match.group("status"),
                    protocol=match.group("protocol"),
                ),
            )
        return states

    @staticmethod
    def parse_vlan_brief(output: str) -> list[DiscoveredVLAN]:
        vlans: list[DiscoveredVLAN] = []
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped or not stripped[0].isdigit():
                continue
            parts = re.split(r"\s{2,}", stripped)
            if len(parts) < 3:
                continue
            interfaces = []
            if len(parts) > 3:
                interfaces = [item.strip() for item in parts[3].split(",") if item.strip()]
            vlans.append(
                DiscoveredVLAN(
                    vlan_id=int(parts[0]),
                    name=parts[1],
                    status=parts[2],
                    interfaces=interfaces,
                ),
            )
        return vlans

    @staticmethod
    def parse_interfaces_trunk(output: str) -> list[DiscoveredTrunk]:
        trunks: list[DiscoveredTrunk] = []
        in_allowed_section = False

        for line in output.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if "Vlans allowed on trunk" in stripped:
                in_allowed_section = True
                continue
            if in_allowed_section and stripped.startswith("Port"):
                continue
            if in_allowed_section and re.match(r"^[A-Za-z].*", stripped):
                parts = re.split(r"\s{2,}", stripped)
                if len(parts) < 2:
                    continue
                trunks.append(
                    DiscoveredTrunk(
                        interface_name=parts[0],
                        allowed_vlans=_expand_vlan_list(parts[1]),
                    ),
                )
        return trunks

    @staticmethod
    def parse_ip_route(output: str) -> list[DiscoveredRoute]:
        routes: list[DiscoveredRoute] = []
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("Codes:", "Gateway of last resort")):
                continue

            connected_match = re.match(
                r"^(?P<code>[A-Z\*]+)\s+(?P<network>\d+\.\d+\.\d+\.\d+/\d+)\s+is directly connected,\s+(?P<iface>\S+)$",
                stripped,
            )
            if connected_match:
                routes.append(
                    DiscoveredRoute(
                        code=connected_match.group("code"),
                        network=connected_match.group("network"),
                        outgoing_interface=connected_match.group("iface"),
                    ),
                )
                continue

            routed_match = re.match(
                r"^(?P<code>[A-Z\*]+)\s+(?P<network>\d+\.\d+\.\d+\.\d+/\d+).+via\s+(?P<next_hop>\d+\.\d+\.\d+\.\d+)(?:,\s+\S+)?(?:,\s+(?P<iface>\S+))?$",
                stripped,
            )
            if routed_match:
                routes.append(
                    DiscoveredRoute(
                        code=routed_match.group("code"),
                        network=routed_match.group("network"),
                        next_hop=routed_match.group("next_hop"),
                        outgoing_interface=routed_match.group("iface"),
                    ),
                )
        return routes

    @staticmethod
    def parse_access_lists(output: str) -> list[DiscoveredACL]:
        acls: list[DiscoveredACL] = []
        current_acl: DiscoveredACL | None = None

        for line in output.splitlines():
            stripped = line.rstrip()
            if not stripped:
                continue

            header = re.match(r"^(Standard|Extended) IP access list (.+)$", stripped)
            if header:
                current_acl = DiscoveredACL(
                    name=header.group(2),
                    acl_type=header.group(1).lower(),
                )
                acls.append(current_acl)
                continue

            if current_acl is None and stripped[0].isdigit():
                current_acl = DiscoveredACL(name="numbered", acl_type=None)
                acls.append(current_acl)

            if current_acl is not None:
                current_acl.entries.append(stripped.strip())

        return acls

    @staticmethod
    def parse_ospf_neighbors(output: str) -> list[DiscoveredOSPFNeighbor]:
        neighbors: list[DiscoveredOSPFNeighbor] = []
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("Neighbor ID", "OSPF")):
                continue
            parts = re.split(r"\s{2,}", stripped)
            if len(parts) < 5:
                continue
            neighbors.append(
                DiscoveredOSPFNeighbor(
                    neighbor_id=parts[0],
                    state=parts[2],
                    address=parts[4],
                    interface_name=parts[5],
                ),
            )
        return neighbors


def _expand_vlan_list(raw_value: str) -> list[int]:
    vlan_ids: list[int] = []
    for part in raw_value.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start, end = token.split("-", maxsplit=1)
            vlan_ids.extend(range(int(start), int(end) + 1))
        else:
            vlan_ids.append(int(token))
    return vlan_ids
