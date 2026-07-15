"""Provider-independent structured LLM interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from ipaddress import IPv4Address
import re
from typing import Any

from app.ai.models import ClarificationItem, ProviderResult


class LLMProvider(ABC):
    """Abstract provider for structured AI tasks."""

    @abstractmethod
    def interpret_topology(self, prompt: str, *, context: dict[str, Any] | None = None) -> ProviderResult:
        raise NotImplementedError

    @abstractmethod
    def interpret_change(self, prompt: str, *, context: dict[str, Any] | None = None) -> ProviderResult:
        raise NotImplementedError

    @abstractmethod
    def explain_result(self, payload: dict[str, Any]) -> ProviderResult:
        raise NotImplementedError


class HeuristicLLMProvider(LLMProvider):
    """A deterministic provider-like adapter used until a real LLM is configured."""

    def interpret_topology(self, prompt: str, *, context: dict[str, Any] | None = None) -> ProviderResult:
        lowered = prompt.casefold()
        warnings = [
            "Heuristic provider in use. Review the interpreted topology before deployment.",
        ]
        if "three vlan" in lowered or "üç vlan" in lowered or "uc vlan" in lowered:
            topology = {
                "project": {
                    "name": "ai-three-vlan-office",
                    "description": prompt.strip(),
                },
                "sites": [{"id": "hq", "name": "Headquarters"}],
                "devices": [
                    {
                        "id": "r1",
                        "hostname": "R1",
                        "type": "router",
                        "platform": "iosv",
                        "site_id": "hq",
                        "interfaces": [
                            {"name": "GigabitEthernet0/0", "enabled": True},
                            {"name": "GigabitEthernet0/0.10", "enabled": True, "ipv4_address": "192.168.10.1/24"},
                            {"name": "GigabitEthernet0/0.20", "enabled": True, "ipv4_address": "192.168.20.1/24"},
                            {"name": "GigabitEthernet0/0.30", "enabled": True, "ipv4_address": "192.168.30.1/24"},
                        ],
                    },
                    {
                        "id": "sw1",
                        "hostname": "SW1",
                        "type": "switch",
                        "platform": "iosvl2",
                        "site_id": "hq",
                        "interfaces": [
                            {"name": "GigabitEthernet0/1", "enabled": True, "trunk_vlans": [10, 20, 30]},
                            {"name": "GigabitEthernet0/2", "enabled": True, "access_vlan": 10},
                            {"name": "GigabitEthernet0/3", "enabled": True, "access_vlan": 20},
                            {"name": "GigabitEthernet0/4", "enabled": True, "access_vlan": 30},
                        ],
                    },
                    {"id": "admin-pc", "hostname": "ADMIN-PC", "type": "endpoint", "platform": "vpcs", "site_id": "hq", "interfaces": [{"name": "Ethernet0", "enabled": True}]},
                    {"id": "student-pc", "hostname": "STUDENT-PC", "type": "endpoint", "platform": "vpcs", "site_id": "hq", "interfaces": [{"name": "Ethernet0", "enabled": True}]},
                    {"id": "guest-pc", "hostname": "GUEST-PC", "type": "endpoint", "platform": "vpcs", "site_id": "hq", "interfaces": [{"name": "Ethernet0", "enabled": True}]},
                ],
                "links": [
                    {"source_device": "r1", "source_interface": "GigabitEthernet0/0", "target_device": "sw1", "target_interface": "GigabitEthernet0/1"},
                    {"source_device": "sw1", "source_interface": "GigabitEthernet0/2", "target_device": "admin-pc", "target_interface": "Ethernet0"},
                    {"source_device": "sw1", "source_interface": "GigabitEthernet0/3", "target_device": "student-pc", "target_interface": "Ethernet0"},
                    {"source_device": "sw1", "source_interface": "GigabitEthernet0/4", "target_device": "guest-pc", "target_interface": "Ethernet0"},
                ],
                "vlans": [
                    {"vlan_id": 10, "name": "ADMIN", "subnet": "192.168.10.0/24", "gateway": "192.168.10.1", "endpoint_ids": ["admin-endpoint"]},
                    {"vlan_id": 20, "name": "STUDENT", "subnet": "192.168.20.0/24", "gateway": "192.168.20.1", "endpoint_ids": ["student-endpoint"]},
                    {"vlan_id": 30, "name": "GUEST", "subnet": "192.168.30.0/24", "gateway": "192.168.30.1", "endpoint_ids": ["guest-endpoint"]},
                ],
                "subnets": [
                    {"id": "vlan10-subnet", "name": "ADMIN subnet", "network": "192.168.10.0/24", "gateway": "192.168.10.1", "vlan_id": 10},
                    {"id": "vlan20-subnet", "name": "STUDENT subnet", "network": "192.168.20.0/24", "gateway": "192.168.20.1", "vlan_id": 20},
                    {"id": "vlan30-subnet", "name": "GUEST subnet", "network": "192.168.30.0/24", "gateway": "192.168.30.1", "vlan_id": 30},
                ],
                "endpoints": [
                    {"id": "admin-endpoint", "device_id": "admin-pc", "hostname": "ADMIN-PC", "ip_address": "192.168.10.10", "vlan_id": 10, "subnet_id": "vlan10-subnet", "default_gateway": "192.168.10.1"},
                    {"id": "student-endpoint", "device_id": "student-pc", "hostname": "STUDENT-PC", "ip_address": "192.168.20.10", "vlan_id": 20, "subnet_id": "vlan20-subnet", "default_gateway": "192.168.20.1"},
                    {"id": "guest-endpoint", "device_id": "guest-pc", "hostname": "GUEST-PC", "ip_address": "192.168.30.10", "vlan_id": 30, "subnet_id": "vlan30-subnet", "default_gateway": "192.168.30.1"},
                ],
                "dhcp_pools": [
                    {"id": "guest-dhcp", "name": "GUEST DHCP", "subnet": "192.168.30.0/24", "default_gateway": "192.168.30.1", "dns_servers": ["8.8.8.8"]},
                ],
                "routes": [],
                "routing_protocols": [],
                "acls": [],
                "services": [{"id": "guest-dhcp-service", "name": "Guest DHCP", "kind": "dhcp", "vlan_id": 30, "subnet_id": "vlan30-subnet", "critical": True}],
                "connectivity_requirements": [
                    {"id": "admin-to-student", "source_endpoint_id": "admin-endpoint", "target_endpoint_id": "student-endpoint", "protocol": "ping", "expected": "reachable"},
                ],
                "validation_tests": [
                    {"id": "test-admin-student", "name": "Admin to Student ping", "test_type": "ping", "source_endpoint_id": "admin-endpoint", "target_endpoint_id": "student-endpoint", "expected_success": True},
                ],
            }
            if "guest" in lowered and "admin" in lowered and ("erişemesin" in lowered or "erisemesin" in lowered or "cannot access" in lowered or "must not access" in lowered):
                topology["acls"] = [
                    {
                        "id": "guest-to-admin",
                        "name": "guest-to-admin",
                        "type": "extended",
                        "device_id": "r1",
                        "rules": [
                            {"id": "deny-guest-admin", "action": "deny", "protocol": "ip", "source": "192.168.30.0/24", "destination": "192.168.10.0/24"},
                            {"id": "permit-rest", "action": "permit", "protocol": "ip", "source": "any", "destination": "any"},
                        ],
                    },
                ]
                topology["connectivity_requirements"].append(
                    {"id": "guest-to-admin", "source_endpoint_id": "guest-endpoint", "target_endpoint_id": "admin-endpoint", "protocol": "ping", "expected": "blocked"},
                )
                topology["validation_tests"].append(
                    {"id": "test-guest-admin", "name": "Guest to Admin blocked", "test_type": "acl", "source_endpoint_id": "guest-endpoint", "target_endpoint_id": "admin-endpoint", "expected_success": False},
                )
            return ProviderResult(payload={"topology": topology}, warnings=warnings)

        return ProviderResult(
            clarifications=[
                ClarificationItem(
                    field="topology_scope",
                    question="How many devices, VLANs, and endpoint groups should be created?",
                    reason="The request does not describe a topology shape that can be safely converted into TopologySpec.",
                    options=["three-vlan office", "two-router ospf", "guest isolation"],
                ),
            ],
            warnings=warnings,
        )

    def interpret_change(self, prompt: str, *, context: dict[str, Any] | None = None) -> ProviderResult:
        lowered = prompt.casefold()
        topology = context.get("topology", {}) if context else {}
        if "trunk" in lowered and ("kaldır" in lowered or "remove" in lowered):
            vlan_keyword = None
            for candidate in ("guest", "student", "admin"):
                if candidate in lowered:
                    vlan_keyword = candidate
                    break
            if vlan_keyword is None:
                return ProviderResult(
                    clarifications=[
                        ClarificationItem(
                            field="vlan_id",
                            question="Which VLAN should be removed from the trunk?",
                            reason="The request identifies a trunk change but not a unique VLAN target.",
                        ),
                    ],
                )
            vlan_id = _resolve_vlan_id(vlan_keyword, topology)
            if vlan_id is None:
                return ProviderResult(
                    clarifications=[
                        ClarificationItem(
                            field="vlan_id",
                            question=f"{vlan_keyword.title()} VLAN topology context is missing. Which VLAN should be removed from the trunk?",
                            reason="The current topology does not contain a VLAN matching the natural-language request.",
                        ),
                    ],
                )
            return ProviderResult(
                payload={
                    "command": {
                        "type": "REMOVE_VLAN_FROM_TRUNK",
                        "device": "sw1",
                        "interface": "GigabitEthernet0/1",
                        "vlan_id": vlan_id,
                    },
                },
                warnings=["Review the selected trunk interface before simulation or apply."],
            )
        if "shutdown" in lowered and "interface" in lowered:
            interface_match = re.search(r"(gigabitethernet[\d/\.]+)", lowered)
            device_match = re.search(r"\b(r\d+|sw\d+)\b", lowered)
            if interface_match and device_match:
                return ProviderResult(
                    payload={
                        "command": {
                            "type": "SHUTDOWN_INTERFACE",
                            "device": device_match.group(1),
                            "interface": interface_match.group(1).replace("gigabitethernet", "GigabitEthernet"),
                        },
                    },
                )
            return ProviderResult(
                clarifications=[
                    ClarificationItem(
                        field="interface",
                        question="Which device and interface should be shut down?",
                        reason="The request mentions interface shutdown but does not identify a unique target.",
                    ),
                ],
            )
        if "gateway" in lowered and ("change" in lowered or "değiş" in lowered or "degis" in lowered):
            gateway_match = re.search(r"(\d+\.\d+\.\d+\.\d+)", lowered)
            vlan_match = re.search(r"vlan\s*(\d+)", lowered)
            if gateway_match and vlan_match:
                return ProviderResult(
                    payload={
                        "command": {
                            "type": "CHANGE_GATEWAY",
                            "vlan_id": int(vlan_match.group(1)),
                            "gateway": str(IPv4Address(gateway_match.group(1))),
                        },
                    },
                )
        return ProviderResult(
            clarifications=[
                ClarificationItem(
                    field="change_request",
                    question="Which exact device, interface, VLAN, route, or ACL object should be changed?",
                    reason="The change request is ambiguous and could map to multiple command types.",
                ),
            ],
        )

    def explain_result(self, payload: dict[str, Any]) -> ProviderResult:
        summary = "Deterministic analysis completed."
        bullets: list[str] = []
        if "simulation" in payload:
            simulation = payload["simulation"]
            bullets.append(f"Simulation command type: {simulation.get('command_type', 'unknown')}")
            bullets.append(f"Direct impacts: {len(simulation.get('direct_impacts', []))}")
            bullets.append(f"Indirect impacts: {len(simulation.get('indirect_impacts', []))}")
        if "risk" in payload:
            risk = payload["risk"]
            bullets.append(f"Risk score: {risk.get('total_score', 'n/a')}")
            bullets.append(f"Risk level: {risk.get('level', 'n/a')}")
        if "validations" in payload:
            validations = payload["validations"]
            bullets.append(f"Validation results reviewed: {len(validations)}")
        return ProviderResult(
            payload={
                "summary": summary,
                "bullets": bullets,
                "warnings": ["This explanation is descriptive only and does not override deterministic engine outputs."],
                "next_actions": ["Review the preview", "Run simulation or validation", "Approve only after manual review"],
            },
        )


def _resolve_vlan_id(name: str, topology: dict[str, Any]) -> int | None:
    for vlan in topology.get("vlans", []):
        vlan_name = str(vlan.get("name", "")).casefold()
        if name in vlan_name:
            return int(vlan["vlan_id"])
    return None
