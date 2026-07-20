"""Provider-independent structured LLM interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass
import json
from ipaddress import IPv4Address
from pathlib import Path
import re
from typing import Any

import httpx

from app.ai.models import ClarificationItem, ProviderResult
from app.topology.service import TopologyService


class LLMProvider(ABC):
    """Abstract provider for structured AI tasks."""

    @abstractmethod
    def interpret_topology(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> ProviderResult:
        raise NotImplementedError

    @abstractmethod
    def interpret_change(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> ProviderResult:
        raise NotImplementedError

    @abstractmethod
    def explain_result(self, payload: dict[str, Any]) -> ProviderResult:
        raise NotImplementedError


class GeminiLLMProvider(LLMProvider):
    """Gemini REST provider using structured JSON output."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gemini-3.5-flash",
        base_url: str = "https://generativelanguage.googleapis.com",
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=timeout, transport=transport)

    def interpret_topology(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> ProviderResult:
        instruction = (
            "You translate natural-language network requirements into a strict "
            "vendor-neutral topology JSON object. Return JSON with keys: "
            "topology, clarifications, warnings. If the prompt is sufficiently "
            "specific, return a complete topology object in topology. If the "
            "prompt is ambiguous, set topology to null and return clarifications. "
            "Never call tools, never mention policy, never add markdown."
        )
        response_schema = {
            "type": "OBJECT",
            "properties": {
                "topology": {"type": "OBJECT", "nullable": True},
                "clarifications": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "field": {"type": "STRING"},
                            "question": {"type": "STRING"},
                            "reason": {"type": "STRING"},
                            "options": {"type": "ARRAY", "items": {"type": "STRING"}},
                        },
                        "required": ["field", "question", "reason"],
                    },
                },
                "warnings": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["topology", "clarifications", "warnings"],
        }
        prompt_payload = {
            "prompt": prompt,
            "context": context or {},
            "requirements": {
                "independent_from_gns3": True,
                "include_links": True,
                "include_endpoints": True,
                "include_validation_tests": True,
            },
        }
        payload = self._generate_structured_json(
            prompt=json.dumps(prompt_payload, ensure_ascii=False),
            instruction=instruction,
            response_schema=response_schema,
        )
        return _provider_result_from_payload(payload)

    def interpret_change(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> ProviderResult:
        instruction = (
            "You convert a natural-language network change request into one "
            "typed change command JSON object. Return JSON with keys: command, "
            "clarifications, warnings. If the request is ambiguous, set "
            "command to null and return clarifications. Allowed command types: "
            "DELETE_VLAN, CHANGE_ACCESS_VLAN, ADD_VLAN_TO_TRUNK, "
            "REMOVE_VLAN_FROM_TRUNK, SHUTDOWN_INTERFACE, ENABLE_INTERFACE, "
            "CHANGE_GATEWAY, ADD_STATIC_ROUTE, REMOVE_STATIC_ROUTE, "
            "ADD_ACL_RULE, REMOVE_ACL_RULE. "
            "Never add markdown."
        )
        response_schema = {
            "type": "OBJECT",
            "properties": {
                "command": {"type": "OBJECT", "nullable": True},
                "clarifications": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "field": {"type": "STRING"},
                            "question": {"type": "STRING"},
                            "reason": {"type": "STRING"},
                            "options": {"type": "ARRAY", "items": {"type": "STRING"}},
                        },
                        "required": ["field", "question", "reason"],
                    },
                },
                "warnings": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["command", "clarifications", "warnings"],
        }
        prompt_payload = {
            "prompt": prompt,
            "context": context or {},
        }
        payload = self._generate_structured_json(
            prompt=json.dumps(prompt_payload, ensure_ascii=False),
            instruction=instruction,
            response_schema=response_schema,
        )
        return _provider_result_from_payload(payload)

    def explain_result(self, payload: dict[str, Any]) -> ProviderResult:
        instruction = (
            "You explain deterministic networking outputs in concise operator language. "
            "Return JSON with keys: summary, bullets, warnings, next_actions. "
            "Do not change the technical outcome, do not invent metrics, do not add markdown."
        )
        response_schema = {
            "type": "OBJECT",
            "properties": {
                "summary": {"type": "STRING"},
                "bullets": {"type": "ARRAY", "items": {"type": "STRING"}},
                "warnings": {"type": "ARRAY", "items": {"type": "STRING"}},
                "next_actions": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["summary", "bullets", "warnings", "next_actions"],
        }
        response_payload = self._generate_structured_json(
            prompt=json.dumps(payload, ensure_ascii=False),
            instruction=instruction,
            response_schema=response_schema,
        )
        return ProviderResult(payload=response_payload)

    def _generate_structured_json(
        self,
        *,
        prompt: str,
        instruction: str,
        response_schema: dict[str, Any],
    ) -> dict[str, Any]:
        response = self.client.post(
            f"{self.base_url}/v1beta/models/{self.model}:generateContent",
            params={"key": self.api_key},
            json={
                "system_instruction": {
                    "parts": [{"text": instruction}],
                },
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": prompt}],
                    },
                ],
                "generationConfig": {
                    "temperature": 0.1,
                    "responseMimeType": "application/json",
                    "responseSchema": response_schema,
                },
            },
        )
        response.raise_for_status()
        data = response.json()
        text = _extract_gemini_text(data)
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError("Gemini returned invalid JSON content.") from error


class HeuristicLLMProvider(LLMProvider):
    """A deterministic provider-like adapter used until a real LLM is configured."""

    def __init__(
        self,
        *,
        topology_service: TopologyService | None = None,
    ) -> None:
        self.topology_service = topology_service or TopologyService()

    def interpret_topology(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> ProviderResult:
        lowered = _normalize_text(prompt)
        warnings = [
            "Heuristic provider in use. Review the interpreted topology before deployment.",
        ]

        if any(
            token in lowered
            for token in ("three vlan", "uc vlan", "uc vlanli", "3 vlan")
        ):
            topology = _load_example_topology("three-vlan-office.yaml", self.topology_service)
            topology = _apply_project_metadata(topology, prompt, "ai-three-vlan-office")
            if _wants_guest_block(lowered):
                warnings.append("Guest-to-admin isolation was inferred from the prompt.")
            return ProviderResult(
                payload={"topology": topology},
                warnings=[
                    *warnings,
                    "Topology, links, VLANs, endpoints, and validation tests were auto-generated.",
                ],
            )

        if any(
            token in lowered
            for token in ("guest isolation", "guest segment", "guest network", "guest vlan")
        ) and _wants_guest_block(lowered):
            topology = _load_example_topology("guest-isolation.yaml", self.topology_service)
            topology = _apply_project_metadata(topology, prompt, "ai-guest-isolation")
            return ProviderResult(
                payload={"topology": topology},
                warnings=[*warnings, "A guest-isolation topology was selected and fully expanded."],
            )

        if any(
            token in lowered
            for token in ("ospf", "two router", "2 router", "branch", "hq")
        ):
            topology = _load_example_topology("two-router-ospf.yaml", self.topology_service)
            topology = _apply_project_metadata(topology, prompt, "ai-two-router-ospf")
            return ProviderResult(
                payload={"topology": topology},
                warnings=[
                    *warnings,
                    (
                        "An OSPF branch topology was generated with complete "
                        "inter-router and endpoint links."
                    ),
                ],
            )

        if any(
            token in lowered
            for token in (
                "simple office",
                "small office",
                "office topology",
                "one router",
                "1 router",
                "one switch",
                "1 switch",
                "endpoint",
                "endpoints",
            )
        ):
            router_count = _extract_count(lowered, "router", default=1)
            switch_count = _extract_count(lowered, "switch", default=1)
            endpoint_count = _extract_count(lowered, "endpoint", default=2)
            topology = _build_office_topology(
                prompt,
                router_count=router_count,
                switch_count=switch_count,
                endpoint_count=endpoint_count,
                project_name="ai-simple-office",
            )
            return ProviderResult(
                payload={"topology": topology},
                warnings=[
                    *warnings,
                    (
                        "An office topology was generated from the prompt and "
                        "expanded into devices, links, and addressing placeholders."
                    ),
                ],
            )

        topology = _build_office_topology(
            prompt,
            router_count=_extract_count(lowered, "router", default=1),
            switch_count=_extract_count(lowered, "switch", default=1),
            endpoint_count=_extract_count(lowered, "endpoint", default=2),
            project_name="ai-default-office",
        )
        return ProviderResult(
            payload={"topology": topology},
            warnings=[
                *warnings,
                (
                    "The prompt was mapped to a default office topology because it did not "
                    "match a more specific blueprint."
                ),
                "Review device names, links, and VLAN design before deployment.",
            ],
        )

    def interpret_change(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> ProviderResult:
        lowered = _normalize_text(prompt)
        topology = context.get("topology", {}) if context else {}
        if "trunk" in lowered and any(
            token in lowered for token in ("kaldir", "remove")
        ):
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
                            reason=(
                                "The request identifies a trunk change but not "
                                "a unique VLAN target."
                            ),
                        ),
                    ],
                )
            vlan_id = _resolve_vlan_id(vlan_keyword, topology)
            if vlan_id is None:
                return ProviderResult(
                    clarifications=[
                        ClarificationItem(
                            field="vlan_id",
                            question=(
                                f"{vlan_keyword.title()} VLAN topology context is missing. "
                                "Which VLAN should be removed from the trunk?"
                            ),
                            reason=(
                                "The current topology does not contain a VLAN matching the "
                                "natural-language request."
                            ),
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
                warnings=[
                    "Review the selected trunk interface before simulation or apply.",
                ],
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
                            "interface": interface_match.group(1).replace(
                                "gigabitethernet",
                                "GigabitEthernet",
                            ),
                        },
                    },
                )
            return ProviderResult(
                clarifications=[
                    ClarificationItem(
                        field="interface",
                        question="Which device and interface should be shut down?",
                        reason=(
                            "The request mentions interface shutdown but does "
                            "not identify a unique target."
                        ),
                    ),
                ],
            )
        if "gateway" in lowered and any(
            token in lowered for token in ("change", "degis", "degisik")
        ):
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
                    question=(
                        "Which exact device, interface, VLAN, route, or ACL "
                        "object should be changed?"
                    ),
                    reason=(
                        "The change request is ambiguous and could map to multiple command types."
                    ),
                ),
            ],
        )

    def explain_result(self, payload: dict[str, Any]) -> ProviderResult:
        summary = "Deterministic analysis completed."
        bullets: list[str] = []
        if "simulation" in payload:
            simulation = payload["simulation"]
            bullets.append(
                f"Simulation command type: {simulation.get('command_type', 'unknown')}"
            )
            bullets.append(f"Direct impacts: {len(simulation.get('direct_impacts', []))}")
            bullets.append(
                f"Indirect impacts: {len(simulation.get('indirect_impacts', []))}"
            )
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
                "warnings": [
                    (
                        "This explanation is descriptive only and does not "
                        "override deterministic engine outputs."
                    ),
                ],
                "next_actions": [
                    "Review the preview",
                    "Run simulation or validation",
                    "Approve only after manual review",
                ],
            },
        )


def _provider_result_from_payload(payload: dict[str, Any]) -> ProviderResult:
    return ProviderResult(
        payload={
            key: value
            for key, value in payload.items()
            if key not in {"clarifications", "warnings"}
        },
        clarifications=[
            ClarificationItem.model_validate(item)
            for item in payload.get("clarifications", [])
        ],
        warnings=[str(item) for item in payload.get("warnings", [])],
    )


def _extract_gemini_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        raise ValueError("Gemini response did not include any candidates.")
    parts = candidates[0].get("content", {}).get("parts", [])
    for part in parts:
        if "text" in part:
            return str(part["text"])
    raise ValueError("Gemini response did not include a text part.")


def _normalize_text(value: str) -> str:
    replacements = {
        "ü": "u",
        "ı": "i",
        "ş": "s",
        "ğ": "g",
        "ö": "o",
        "ç": "c",
    }
    normalized = value.casefold()
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized


def _examples_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "examples"


def _load_example_topology(
    name: str,
    topology_service: TopologyService,
) -> dict[str, Any]:
    topology = topology_service.load_file(_examples_dir() / name)
    return topology.model_dump(mode="json", exclude_none=True)


def _apply_project_metadata(
    topology: dict[str, Any],
    prompt: str,
    project_name: str,
) -> dict[str, Any]:
    updated = deepcopy(topology)
    updated["project"]["name"] = project_name
    updated["project"]["description"] = prompt.strip()
    return updated


def _wants_guest_block(lowered_prompt: str) -> bool:
    return "guest" in lowered_prompt and "admin" in lowered_prompt and any(
        token in lowered_prompt
        for token in ("erisemesin", "cannot access", "must not access", "blocked")
    )


@dataclass(slots=True)
class TopologyIntent:
    router_count: int
    switch_count: int
    endpoint_count: int
    vlan_count: int
    requires_ospf: bool
    guest_isolation: bool
    project_name: str
    site_names: list[str]


def build_topology_from_prompt(prompt: str) -> dict[str, Any]:
    lowered = _normalize_text(prompt)
    intent = _extract_topology_intent(lowered)
    return _build_topology_from_intent(prompt, intent)


def _extract_topology_intent(lowered_prompt: str) -> TopologyIntent:
    router_count = _extract_count(lowered_prompt, "router", default=1)
    switch_count = _extract_count(lowered_prompt, "switch", default=1)
    endpoint_count = max(
        _extract_count(lowered_prompt, "endpoint", default=0),
        _extract_count(lowered_prompt, "pc", default=0),
        _extract_count(lowered_prompt, "client", default=0),
        _extract_count(lowered_prompt, "istemci", default=0),
        2,
    )
    vlan_count = max(_extract_count(lowered_prompt, "vlan", default=0), 1)
    requires_ospf = "ospf" in lowered_prompt
    guest_isolation = _wants_guest_block(lowered_prompt)

    if requires_ospf and router_count < 2:
        router_count = 2
    if guest_isolation and vlan_count < 3:
        vlan_count = 3

    site_names = ["Headquarters", "Branch"] if "hq" in lowered_prompt and "branch" in lowered_prompt else ["Headquarters"]
    project_name = "ai-generated-topology"
    if requires_ospf:
        project_name = "ai-two-router-ospf"
    elif vlan_count >= 3:
        project_name = "ai-three-vlan-office"
    elif guest_isolation:
        project_name = "ai-guest-isolation"

    return TopologyIntent(
        router_count=router_count,
        switch_count=switch_count,
        endpoint_count=endpoint_count,
        vlan_count=vlan_count,
        requires_ospf=requires_ospf,
        guest_isolation=guest_isolation,
        project_name=project_name,
        site_names=site_names,
    )


def _build_topology_from_intent(
    prompt: str,
    intent: TopologyIntent,
) -> dict[str, Any]:
    vlan_profiles = _build_vlan_profiles(intent.vlan_count, intent.guest_isolation)
    sites = [
        {"id": _slugify(site_name) or f"site-{index + 1}", "name": site_name}
        for index, site_name in enumerate(intent.site_names)
    ]
    devices: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    vlans: list[dict[str, Any]] = []
    subnets: list[dict[str, Any]] = []
    endpoints: list[dict[str, Any]] = []
    services: list[dict[str, Any]] = []
    connectivity_requirements: list[dict[str, Any]] = []
    validation_tests: list[dict[str, Any]] = []
    protocols: list[dict[str, Any]] = []
    acls: list[dict[str, Any]] = []

    for profile in vlan_profiles:
        vlan_id = profile["vlan_id"]
        network = f"192.168.{vlan_id}.0/24"
        gateway = f"192.168.{vlan_id}.1"
        vlans.append(
            {
                "vlan_id": vlan_id,
                "name": profile["name"],
                "subnet": network,
                "gateway": gateway,
                "endpoint_ids": [],
            }
        )
        subnets.append(
            {
                "id": f"vlan{vlan_id}-subnet",
                "name": f"{profile['name']} subnet",
                "network": network,
                "gateway": gateway,
                "vlan_id": vlan_id,
            }
        )

    for router_index in range(intent.router_count):
        router_interfaces = [{"name": "GigabitEthernet0/0", "enabled": True}]
        if intent.router_count > 1:
            router_interfaces.append({"name": "GigabitEthernet0/1", "enabled": True})
        devices.append(
            {
                "id": f"r{router_index + 1}",
                "hostname": f"R{router_index + 1}",
                "type": "router",
                "platform": "iosv",
                "site_id": sites[min(router_index, len(sites) - 1)]["id"],
                "interfaces": router_interfaces,
            }
        )

    for switch_index in range(intent.switch_count):
        switch_interfaces = [
            {
                "name": "GigabitEthernet0/1",
                "enabled": True,
                "trunk_vlans": [profile["vlan_id"] for profile in vlan_profiles],
            }
        ]
        for endpoint_index in range(intent.endpoint_count):
            switch_interfaces.append(
                {
                    "name": f"GigabitEthernet0/{endpoint_index + 2}",
                    "enabled": True,
                }
            )
        devices.append(
            {
                "id": f"sw{switch_index + 1}",
                "hostname": f"SW{switch_index + 1}",
                "type": "switch",
                "platform": "iosvl2",
                "site_id": sites[min(switch_index, len(sites) - 1)]["id"],
                "interfaces": switch_interfaces,
            }
        )

    for endpoint_index in range(intent.endpoint_count):
        profile = vlan_profiles[endpoint_index % len(vlan_profiles)]
        vlan_id = profile["vlan_id"]
        hostname = _endpoint_hostname(profile["name"], endpoint_index + 1)
        endpoint_id = f"pc{endpoint_index + 1}-endpoint"
        endpoint = {
            "id": endpoint_id,
            "device_id": f"pc{endpoint_index + 1}",
            "hostname": hostname,
            "ip_address": f"192.168.{vlan_id}.{10 + endpoint_index}",
            "vlan_id": vlan_id,
            "subnet_id": f"vlan{vlan_id}-subnet",
            "default_gateway": f"192.168.{vlan_id}.1",
        }
        endpoints.append(endpoint)
        devices.append(
            {
                "id": f"pc{endpoint_index + 1}",
                "hostname": hostname,
                "type": "endpoint",
                "platform": "vpcs",
                "site_id": sites[min(endpoint_index % len(sites), len(sites) - 1)]["id"],
                "interfaces": [{"name": "Ethernet0", "enabled": True}],
            }
        )
        services.append(
            {
                "id": f"pc{endpoint_index + 1}-access",
                "name": f"{hostname} access",
                "kind": "workstation",
                "endpoint_id": endpoint_id,
            }
        )
        for vlan in vlans:
            if vlan["vlan_id"] == vlan_id:
                vlan["endpoint_ids"].append(endpoint_id)
                break

    for switch_index in range(intent.switch_count):
        router_id = f"r{min(switch_index + 1, intent.router_count)}"
        links.append(
            {
                "source_device": router_id,
                "source_interface": "GigabitEthernet0/0",
                "target_device": f"sw{switch_index + 1}",
                "target_interface": "GigabitEthernet0/1",
            }
        )

    if intent.router_count > 1:
        for router_index in range(intent.router_count - 1):
            links.append(
                {
                    "source_device": f"r{router_index + 1}",
                    "source_interface": "GigabitEthernet0/1",
                    "target_device": f"r{router_index + 2}",
                    "target_interface": "GigabitEthernet0/1",
                }
            )
            subnets.append(
                {
                    "id": f"wan-{router_index + 1}",
                    "name": f"WAN {router_index + 1}",
                    "network": f"10.0.{router_index}.0/30",
                    "gateway": None,
                }
            )

    primary_switch_ports = [index + 2 for index in range(intent.endpoint_count)]
    for endpoint_index in range(intent.endpoint_count):
        vlan_id = vlan_profiles[endpoint_index % len(vlan_profiles)]["vlan_id"]
        switch_id = f"sw{(endpoint_index % intent.switch_count) + 1}"
        switch_port = primary_switch_ports[endpoint_index]
        links.append(
            {
                "source_device": switch_id,
                "source_interface": f"GigabitEthernet0/{switch_port}",
                "target_device": f"pc{endpoint_index + 1}",
                "target_interface": "Ethernet0",
            }
        )
        switch_device = next(device for device in devices if device["id"] == switch_id)
        interface = next(item for item in switch_device["interfaces"] if item["name"] == f"GigabitEthernet0/{switch_port}")
        interface["access_vlan"] = vlan_id

    primary_router = next(device for device in devices if device["id"] == "r1")
    primary_router["interfaces"] = [
        *primary_router["interfaces"],
        *[
            {
                "name": f"GigabitEthernet0/0.{vlan['vlan_id']}",
                "enabled": True,
                "ipv4_address": f"{vlan['gateway']}/24",
            }
            for vlan in vlans
        ],
    ]

    if intent.requires_ospf:
        for router_index in range(intent.router_count):
            protocols.append(
                {
                    "id": f"ospf-r{router_index + 1}",
                    "device_id": f"r{router_index + 1}",
                    "protocol": "ospf",
                    "process_id": 1,
                    "networks": [subnet["network"] for subnet in subnets],
                }
            )

    if intent.guest_isolation and len(vlans) >= 2:
        admin_vlan = next((vlan for vlan in vlans if "ADMIN" in vlan["name"]), vlans[0])
        guest_vlan = next((vlan for vlan in vlans if "GUEST" in vlan["name"]), vlans[-1])
        acls.append(
            {
                "id": "guest-to-admin",
                "name": "guest-to-admin",
                "type": "extended",
                "device_id": "r1",
                "rules": [
                    {
                        "id": "guest-deny-admin",
                        "action": "deny",
                        "protocol": "ip",
                        "source": str(guest_vlan["subnet"]),
                        "destination": str(admin_vlan["subnet"]),
                    },
                    {
                        "id": "guest-permit-any",
                        "action": "permit",
                        "protocol": "ip",
                        "source": "any",
                        "destination": "any",
                    },
                ],
            }
        )

    if len(endpoints) >= 2:
        for source_index in range(len(endpoints)):
            for target_index in range(source_index + 1, len(endpoints)):
                source = endpoints[source_index]
                target = endpoints[target_index]
                expected = "reachable"
                if intent.guest_isolation and 30 in {source["vlan_id"], target["vlan_id"]} and source["vlan_id"] != target["vlan_id"]:
                    expected = "blocked"
                connectivity_requirements.append(
                    {
                        "id": f"auto-{source['id']}-to-{target['id']}",
                        "source_endpoint_id": source["id"],
                        "target_endpoint_id": target["id"],
                        "protocol": "ping",
                        "expected": expected,
                    }
                )
                validation_tests.append(
                    {
                        "id": f"auto-test-{source['id']}-to-{target['id']}",
                        "name": f"{source['hostname']} to {target['hostname']} ping",
                        "test_type": "ping",
                        "source_endpoint_id": source["id"],
                        "target_endpoint_id": target["id"],
                        "expected_success": expected == "reachable",
                    }
                )

    return {
        "project": {
            "name": intent.project_name,
            "description": prompt.strip(),
        },
        "sites": sites,
        "devices": devices,
        "links": links,
        "vlans": vlans,
        "subnets": subnets,
        "endpoints": endpoints,
        "routes": [],
        "routing_protocols": protocols,
        "acls": acls,
        "services": services,
        "connectivity_requirements": connectivity_requirements,
        "validation_tests": validation_tests,
    }


def _build_vlan_profiles(vlan_count: int, guest_isolation: bool) -> list[dict[str, Any]]:
    names = ["ADMIN", "STAFF", "GUEST"] if guest_isolation else ["USERS", "SERVERS", "VOICE", "GUEST", "MGMT"]
    return [
        {
            "vlan_id": (index + 1) * 10,
            "name": names[index] if index < len(names) else f"SEGMENT-{index + 1}",
        }
        for index in range(vlan_count)
    ]


def _endpoint_hostname(segment_name: str, endpoint_number: int) -> str:
    if segment_name == "USERS":
        return f"PC{endpoint_number}"
    return f"{segment_name}-PC-{endpoint_number}"


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def _build_office_topology(
    prompt: str,
    *,
    router_count: int,
    switch_count: int,
    endpoint_count: int,
    project_name: str,
) -> dict[str, Any]:
    normalized_router_count = max(router_count, 1)
    normalized_switch_count = max(switch_count, 1)
    normalized_endpoint_count = max(endpoint_count, 1)

    vlans = []
    subnets = []
    endpoints = []
    devices: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    services: list[dict[str, Any]] = []
    connectivity_requirements: list[dict[str, Any]] = []
    validation_tests: list[dict[str, Any]] = []

    for router_index in range(normalized_router_count):
        router_id = f"r{router_index + 1}"
        router_interfaces = [{"name": "GigabitEthernet0/0", "enabled": True}]
        if normalized_router_count > 1:
            router_interfaces.append({"name": "GigabitEthernet0/1", "enabled": True})
        devices.append(
            {
                "id": router_id,
                "hostname": f"R{router_index + 1}",
                "type": "router",
                "platform": "iosv",
                "site_id": "hq",
                "interfaces": router_interfaces,
            }
        )

    for switch_index in range(normalized_switch_count):
        switch_id = f"sw{switch_index + 1}"
        switch_interfaces = [
            {
                "name": "GigabitEthernet0/1",
                "enabled": True,
                "trunk_vlans": list(range(10, 10 + (normalized_endpoint_count * 10), 10)),
            }
        ]
        for endpoint_index in range(normalized_endpoint_count):
            switch_interfaces.append(
                {
                    "name": f"GigabitEthernet0/{endpoint_index + 2}",
                    "enabled": True,
                    "access_vlan": (endpoint_index + 1) * 10,
                }
            )
        devices.append(
            {
                "id": switch_id,
                "hostname": f"SW{switch_index + 1}",
                "type": "switch",
                "platform": "iosvl2",
                "site_id": "hq",
                "interfaces": switch_interfaces,
            }
        )

    for endpoint_index in range(normalized_endpoint_count):
        vlan_id = (endpoint_index + 1) * 10
        endpoint_device_id = f"pc{endpoint_index + 1}"
        endpoint_id = f"{endpoint_device_id}-endpoint"
        subnet_id = f"vlan{vlan_id}-subnet"
        subnet_network = f"192.168.{vlan_id}.0/24"
        gateway = f"192.168.{vlan_id}.1"
        endpoint_ip = f"192.168.{vlan_id}.10"
        vlans.append(
            {
                "vlan_id": vlan_id,
                "name": f"USERS-{endpoint_index + 1}",
                "subnet": subnet_network,
                "gateway": gateway,
                "endpoint_ids": [endpoint_id],
            }
        )
        subnets.append(
            {
                "id": subnet_id,
                "name": f"USERS-{endpoint_index + 1} subnet",
                "network": subnet_network,
                "gateway": gateway,
                "vlan_id": vlan_id,
            }
        )
        devices.append(
            {
                "id": endpoint_device_id,
                "hostname": f"PC{endpoint_index + 1}",
                "type": "endpoint",
                "platform": "vpcs",
                "site_id": "hq",
                "interfaces": [{"name": "Ethernet0", "enabled": True}],
            }
        )
        endpoints.append(
            {
                "id": endpoint_id,
                "device_id": endpoint_device_id,
                "hostname": f"PC{endpoint_index + 1}",
                "ip_address": endpoint_ip,
                "vlan_id": vlan_id,
                "subnet_id": subnet_id,
                "default_gateway": gateway,
            }
        )
        services.append(
            {
                "id": f"{endpoint_device_id}-access",
                "name": f"PC{endpoint_index + 1} access",
                "kind": "workstation",
                "endpoint_id": endpoint_id,
            }
        )

    primary_router_id = "r1"
    primary_switch_id = "sw1"
    links.append(
        {
            "source_device": primary_router_id,
            "source_interface": "GigabitEthernet0/0",
            "target_device": primary_switch_id,
            "target_interface": "GigabitEthernet0/1",
        }
    )

    if normalized_router_count > 1:
        for router_index in range(normalized_router_count - 1):
            links.append(
                {
                    "source_device": f"r{router_index + 1}",
                    "source_interface": "GigabitEthernet0/1",
                    "target_device": f"r{router_index + 2}",
                    "target_interface": "GigabitEthernet0/1",
                }
            )

    for endpoint_index in range(normalized_endpoint_count):
        links.append(
            {
                "source_device": primary_switch_id,
                "source_interface": f"GigabitEthernet0/{endpoint_index + 2}",
                "target_device": f"pc{endpoint_index + 1}",
                "target_interface": "Ethernet0",
            }
        )

    router_device = devices[0]
    router_device["interfaces"] = [
        *router_device["interfaces"],
        *[
            {
                "name": f"GigabitEthernet0/0.{vlan['vlan_id']}",
                "enabled": True,
                "ipv4_address": f"{vlan['gateway']}/24",
            }
            for vlan in vlans
        ],
    ]

    if normalized_router_count > 1:
        routing_networks = []
        for router_index in range(normalized_router_count - 1):
            network = f"10.0.{router_index}.0/30"
            routing_networks.append(
                {
                    "id": f"wan-{router_index + 1}",
                    "name": f"WAN {router_index + 1}",
                    "network": network,
                    "gateway": None,
                }
            )
        subnets.extend(routing_networks)
        devices[0]["interfaces"][1]["ipv4_address"] = "10.0.0.1/30"
        devices[1]["interfaces"][1]["ipv4_address"] = "10.0.0.2/30"
        protocols = [
            {
                "device_id": f"r{router_index + 1}",
                "protocol": "ospf",
                "process_id": 1,
                "networks": [subnet["network"] for subnet in subnets],
                "area": "0",
            }
            for router_index in range(normalized_router_count)
        ]
    else:
        protocols = []

    if len(endpoints) >= 2:
        connectivity_requirements.append(
            {
                "id": "auto-endpoint-connectivity",
                "source_endpoint_id": endpoints[0]["id"],
                "target_endpoint_id": endpoints[1]["id"],
                "protocol": "ping",
                "expected": "reachable",
            }
        )
        validation_tests.append(
            {
                "id": "auto-test-endpoint-connectivity",
                "name": f"{endpoints[0]['hostname']} to {endpoints[1]['hostname']} ping",
                "test_type": "ping",
                "source_endpoint_id": endpoints[0]["id"],
                "target_endpoint_id": endpoints[1]["id"],
                "expected_success": True,
            }
        )

    return {
        "project": {
            "name": project_name,
            "description": prompt.strip(),
        },
        "sites": [{"id": "hq", "name": "Headquarters"}],
        "devices": devices,
        "links": links,
        "vlans": vlans,
        "subnets": subnets,
        "endpoints": endpoints,
        "routes": [],
        "routing_protocols": protocols,
        "acls": [],
        "services": services,
        "connectivity_requirements": connectivity_requirements,
        "validation_tests": validation_tests,
    }


def _extract_count(lowered_prompt: str, noun: str, *, default: int) -> int:
    word_map = {
        "one": 1,
        "iki": 2,
        "two": 2,
        "uc": 3,
        "three": 3,
        "four": 4,
        "dort": 4,
        "bes": 5,
        "five": 5,
    }
    patterns = [
        rf"(\d+)\s+{noun}s?",
        rf"(one|two|three|four|five|iki|uc|dort|bes)\s+{noun}s?",
    ]
    for pattern in patterns:
        match = re.search(pattern, lowered_prompt)
        if not match:
            continue
        token = match.group(1)
        if token.isdigit():
            return max(int(token), 1)
        return max(word_map.get(token, default), 1)
    return default


def _resolve_vlan_id(name: str, topology: dict[str, Any]) -> int | None:
    for vlan in topology.get("vlans", []):
        vlan_name = str(vlan.get("name", "")).casefold()
        if name in vlan_name:
            return int(vlan["vlan_id"])
    return None
