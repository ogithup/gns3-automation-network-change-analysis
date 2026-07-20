"""Structured natural-language AI service."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from pydantic import ValidationError

from app.ai.models import (
    DeterministicExplanation,
    InterpretedChangePlan,
    InterpretedTopologyPlan,
)
from app.ai.providers import (
    GeminiLLMProvider,
    HeuristicLLMProvider,
    LLMProvider,
    build_topology_from_prompt,
)
from app.ai.security import sanitize_context, sanitize_prompt
from app.changes.models import (
    AddACLRuleCommand,
    AddStaticRouteCommand,
    AddVLANToTrunkCommand,
    ChangeAccessVLANCommand,
    ChangeGatewayCommand,
    DeleteVLANCommand,
    EnableInterfaceCommand,
    RemoveACLRuleCommand,
    RemoveStaticRouteCommand,
    RemoveVLANFromTrunkCommand,
    ShutdownInterfaceCommand,
)
from app.core.config import get_settings
from app.domain.models import TopologySpec
from app.topology.service import TopologyService


class AIService:
    """Provider-independent AI boundary with strict validation and safety checks."""

    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        topology_service: TopologyService | None = None,
    ) -> None:
        self.provider = provider or _build_default_provider()
        self.fallback_provider = HeuristicLLMProvider()
        self.topology_service = topology_service or TopologyService()

    def interpret_topology_request(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> InterpretedTopologyPlan:
        prompt_result = sanitize_prompt(prompt)
        sanitized_context, context_findings = sanitize_context(context or {})
        provider_context = _context_for_topology_prompt(
            prompt_result.sanitized_text,
            sanitized_context,
        )
        safety_findings = [*prompt_result.safety_findings, *context_findings]
        blocked = any(finding.severity == "high" for finding in safety_findings)
        if blocked:
            return InterpretedTopologyPlan(
                blocked=True,
                warnings=[
                    (
                        "Unsafe instructions detected. The request was blocked "
                        "before provider execution."
                    ),
                ],
                safety_findings=safety_findings,
            )

        if _is_topology_creation_prompt(prompt_result.sanitized_text):
            topology = self.topology_service.load_json(
                json.dumps(build_topology_from_prompt(prompt_result.sanitized_text)),
            )
            preview = {
                "project": topology.project.name,
                "device_count": len(topology.devices),
                "vlan_count": len(topology.vlans),
                "connectivity_requirements": [
                    item.model_dump(mode="json")
                    for item in topology.connectivity_requirements
                ],
            }
            return InterpretedTopologyPlan(
                topology=topology,
                warnings=[
                    (
                        "A deterministic topology generator translated the prompt "
                        "into a canonical TopologySpec before rendering the preview."
                    ),
                ],
                safety_findings=safety_findings,
                preview=preview,
            )

        provider_result = self._interpret_topology_with_fallback(
            prompt_result.sanitized_text,
            context=provider_context,
        )
        topology_payload = provider_result.payload.get("topology")
        if topology_payload is None and not provider_result.clarifications:
            provider_result = self._fallback_topology_result(
                prompt_result.sanitized_text,
                context=provider_context,
                reason="Primary provider returned no topology object.",
            )
            topology_payload = provider_result.payload.get("topology")
        elif topology_payload is None and provider_result.clarifications and _is_topology_creation_prompt(prompt_result.sanitized_text):
            provider_result = self._fallback_topology_result(
                prompt_result.sanitized_text,
                context=provider_context,
                reason="Primary provider requested clarification for a create/build topology prompt.",
            )
            topology_payload = provider_result.payload.get("topology")
        if topology_payload is None:
            return InterpretedTopologyPlan(
                blocked=False,
                clarifications=provider_result.clarifications,
                warnings=provider_result.warnings,
                safety_findings=safety_findings,
            )
        try:
            topology = self.topology_service.load_json(json.dumps(topology_payload))
        except ValidationError as error:
            fallback_result = self._fallback_topology_result(
                prompt_result.sanitized_text,
                context=provider_context,
                reason="Primary provider output failed TopologySpec validation.",
            )
            fallback_payload = fallback_result.payload.get("topology")
            if fallback_payload is not None:
                try:
                    topology = self.topology_service.load_json(json.dumps(fallback_payload))
                except ValidationError:
                    topology = None
                else:
                    preview = {
                        "project": topology.project.name,
                        "device_count": len(topology.devices),
                        "vlan_count": len(topology.vlans),
                        "connectivity_requirements": [
                            item.model_dump(mode="json")
                            for item in topology.connectivity_requirements
                        ],
                        "provider_validation_errors": error.errors(),
                    }
                    return InterpretedTopologyPlan(
                        topology=topology,
                        clarifications=fallback_result.clarifications,
                        warnings=fallback_result.warnings,
                        safety_findings=safety_findings,
                        preview=preview,
                    )
            return InterpretedTopologyPlan(
                blocked=False,
                warnings=[
                    *provider_result.warnings,
                    "Provider output failed TopologySpec validation.",
                ],
                safety_findings=safety_findings,
                preview={"validation_errors": error.errors()},
            )

        prompt_expectations = _extract_topology_expectations(prompt_result.sanitized_text)
        mismatch_reason = _validate_topology_against_prompt(topology, prompt_expectations)
        if mismatch_reason is not None:
            fallback_result = self._fallback_topology_result(
                prompt_result.sanitized_text,
                context=provider_context,
                reason=(
                    "Primary provider topology did not match the requested prompt shape: "
                    f"{mismatch_reason}"
                ),
            )
            fallback_payload = fallback_result.payload.get("topology")
            if fallback_payload is not None:
                try:
                    topology = self.topology_service.load_json(json.dumps(fallback_payload))
                    provider_result = fallback_result
                except ValidationError:
                    pass

        preview = {
            "project": topology.project.name,
            "device_count": len(topology.devices),
            "vlan_count": len(topology.vlans),
            "connectivity_requirements": [
                item.model_dump(mode="json")
                for item in topology.connectivity_requirements
            ],
        }
        return InterpretedTopologyPlan(
            topology=topology,
            clarifications=provider_result.clarifications,
            warnings=provider_result.warnings,
            safety_findings=safety_findings,
            preview=preview,
        )

    def interpret_change_request(
        self,
        prompt: str,
        *,
        topology: TopologySpec,
        context: dict[str, Any] | None = None,
    ) -> InterpretedChangePlan:
        prompt_result = sanitize_prompt(prompt)
        sanitized_context, context_findings = sanitize_context(context or {})
        safety_findings = [*prompt_result.safety_findings, *context_findings]
        blocked = any(finding.severity == "high" for finding in safety_findings)
        if blocked:
            return InterpretedChangePlan(
                blocked=True,
                warnings=[
                    (
                        "Unsafe change instructions detected. The request was "
                        "blocked before provider execution."
                    ),
                ],
                safety_findings=safety_findings,
            )

        provider_result = self._interpret_change_with_fallback(
            prompt_result.sanitized_text,
            context={
                **sanitized_context,
                "topology": topology.model_dump(mode="json", exclude_none=True),
            },
        )
        command_payload = provider_result.payload.get("command")
        if command_payload is None:
            return InterpretedChangePlan(
                blocked=False,
                clarifications=provider_result.clarifications,
                warnings=provider_result.warnings,
                safety_findings=safety_findings,
            )
        try:
            command = _parse_change_command(command_payload)
            command.validate(topology)
            after_topology = command.apply(topology)
        except Exception as error:
            return InterpretedChangePlan(
                blocked=False,
                clarifications=provider_result.clarifications,
                warnings=[
                    *provider_result.warnings,
                    f"Interpreted command could not be validated: {error}",
                ],
                safety_findings=safety_findings,
                preview={"invalid_command": command_payload},
            )
        return InterpretedChangePlan(
            command=command.serialize(),
            summary=command.summary(),
            clarifications=provider_result.clarifications,
            warnings=provider_result.warnings,
            safety_findings=safety_findings,
            preview={
                "summary": command.summary(),
                "config_diff": command.config_diff(
                    topology,
                    after_topology,
                ).model_dump(mode="json"),
                "affected_objects": command.affected_objects(),
            },
        )

    def explain_deterministic_results(
        self,
        *,
        payload: dict[str, Any],
    ) -> DeterministicExplanation:
        provider_result = self._explain_with_fallback(payload)
        return DeterministicExplanation.model_validate(provider_result.payload)

    def _interpret_topology_with_fallback(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | None,
    ):
        try:
            return self.provider.interpret_topology(prompt, context=context)
        except (httpx.HTTPError, ValueError) as error:
            fallback = self.fallback_provider.interpret_topology(prompt, context=context)
            fallback.warnings = [
                f"Primary AI provider failed. Falling back to heuristic interpretation: {error}",
                *fallback.warnings,
            ]
            return fallback

    def _fallback_topology_result(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | None,
        reason: str,
    ):
        fallback = self.fallback_provider.interpret_topology(prompt, context=context)
        fallback.warnings = [
            reason,
            *fallback.warnings,
        ]
        return fallback

    def _interpret_change_with_fallback(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | None,
    ):
        try:
            return self.provider.interpret_change(prompt, context=context)
        except (httpx.HTTPError, ValueError) as error:
            fallback = self.fallback_provider.interpret_change(prompt, context=context)
            fallback.warnings = [
                f"Primary AI provider failed. Falling back to heuristic interpretation: {error}",
                *fallback.warnings,
            ]
            return fallback

    def _explain_with_fallback(self, payload: dict[str, Any]):
        try:
            return self.provider.explain_result(payload)
        except (httpx.HTTPError, ValueError) as error:
            fallback = self.fallback_provider.explain_result(payload)
            fallback.warnings = [
                f"Primary AI provider failed. Falling back to heuristic explanation: {error}",
                *fallback.warnings,
            ]
            return fallback


def _parse_change_command(payload: dict[str, Any]):
    command_type = payload.get("type")
    mapping = {
        "DELETE_VLAN": DeleteVLANCommand,
        "CHANGE_ACCESS_VLAN": ChangeAccessVLANCommand,
        "ADD_VLAN_TO_TRUNK": AddVLANToTrunkCommand,
        "REMOVE_VLAN_FROM_TRUNK": RemoveVLANFromTrunkCommand,
        "SHUTDOWN_INTERFACE": ShutdownInterfaceCommand,
        "ENABLE_INTERFACE": EnableInterfaceCommand,
        "CHANGE_GATEWAY": ChangeGatewayCommand,
        "ADD_STATIC_ROUTE": AddStaticRouteCommand,
        "REMOVE_STATIC_ROUTE": RemoveStaticRouteCommand,
        "ADD_ACL_RULE": AddACLRuleCommand,
        "REMOVE_ACL_RULE": RemoveACLRuleCommand,
    }
    model = mapping[str(command_type)]
    return model.model_validate(payload)


def _build_default_provider() -> LLMProvider:
    settings = get_settings()
    provider_name = settings.ai_provider.casefold()
    gemini_enabled = bool(settings.gemini_api_key)
    if provider_name == "gemini" and gemini_enabled:
        return GeminiLLMProvider(
            api_key=settings.gemini_api_key or "",
            model=settings.gemini_model,
            base_url=settings.gemini_base_url,
            timeout=settings.gemini_request_timeout,
        )
    if provider_name == "auto" and gemini_enabled:
        return GeminiLLMProvider(
            api_key=settings.gemini_api_key or "",
            model=settings.gemini_model,
            base_url=settings.gemini_base_url,
            timeout=settings.gemini_request_timeout,
        )
    return HeuristicLLMProvider()


def _context_for_topology_prompt(
    prompt: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    if not _is_topology_creation_prompt(prompt):
        return context
    return {
        key: value
        for key, value in context.items()
        if key not in {"current_topology", "topology", "existing_topology"}
    }


def _is_topology_creation_prompt(prompt: str) -> bool:
    lowered = prompt.casefold()
    creation_tokens = (
        "create",
        "build",
        "design",
        "generate",
        "kur",
        "olustur",
        "oluştur",
        "hazirla",
        "hazırla",
        "ciz",
        "çiz",
    )
    return any(token in lowered for token in creation_tokens)


def _extract_topology_expectations(prompt: str) -> dict[str, int | bool]:
    lowered = prompt.casefold()
    return {
        "routers": _extract_count_from_prompt(lowered, "router"),
        "switches": _extract_count_from_prompt(lowered, "switch"),
        "endpoints": _extract_count_from_prompt(lowered, "endpoint"),
        "requires_ospf": "ospf" in lowered,
    }


def _validate_topology_against_prompt(
    topology: TopologySpec,
    expectations: dict[str, int | bool],
) -> str | None:
    expected_routers = expectations.get("routers")
    expected_switches = expectations.get("switches")
    expected_endpoints = expectations.get("endpoints")
    requires_ospf = expectations.get("requires_ospf") is True

    router_devices = [device for device in topology.devices if device.type == "router"]
    switch_devices = [device for device in topology.devices if device.type == "switch"]
    endpoint_devices = [device for device in topology.devices if device.type == "endpoint"]

    if isinstance(expected_routers, int) and expected_routers > 0 and len(router_devices) != expected_routers:
        return f"expected {expected_routers} router(s) but received {len(router_devices)}"
    if isinstance(expected_switches, int) and expected_switches > 0 and len(switch_devices) != expected_switches:
        return f"expected {expected_switches} switch(es) but received {len(switch_devices)}"
    if isinstance(expected_endpoints, int) and expected_endpoints > 0 and len(endpoint_devices) != expected_endpoints:
        return f"expected {expected_endpoints} endpoint device(s) but received {len(endpoint_devices)}"
    if isinstance(expected_endpoints, int) and expected_endpoints > 0 and len(topology.endpoints) != expected_endpoints:
        return f"expected {expected_endpoints} endpoint object(s) but received {len(topology.endpoints)}"
    if requires_ospf and not any(protocol.protocol == "ospf" for protocol in topology.routing_protocols):
        return "OSPF was requested but no OSPF routing protocol was defined"

    if (
        isinstance(expected_routers, int)
        and expected_routers == 1
        and isinstance(expected_switches, int)
        and expected_switches == 1
        and isinstance(expected_endpoints, int)
        and expected_endpoints > 0
    ):
        expected_link_count = expected_endpoints + 1
        if len(topology.links) < expected_link_count:
            return f"expected at least {expected_link_count} links but received {len(topology.links)}"

        switch_ids = {device.id for device in switch_devices}
        linked_endpoint_ids = {
            link.source_device if link.source_device in {device.id for device in endpoint_devices} else link.target_device
            for link in topology.links
            if link.source_device in switch_ids or link.target_device in switch_ids
        }
        if len(linked_endpoint_ids) < expected_endpoints:
            return "not every endpoint is connected to the switch in the generated topology"

    return None


def _extract_count_from_prompt(lowered_prompt: str, noun: str) -> int | None:
    word_map = {
        "one": 1,
        "iki": 2,
        "two": 2,
        "uc": 3,
        "three": 3,
        "dort": 4,
        "four": 4,
        "bes": 5,
        "five": 5,
    }
    patterns = [
        rf"(\d+)\s+{noun}s?\b",
        rf"(one|two|three|four|five|iki|uc|dort|bes)\s+{noun}s?\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, lowered_prompt)
        if match is None:
            continue
        token = match.group(1)
        if token.isdigit():
            return max(int(token), 1)
        return max(word_map.get(token, 1), 1)
    return None
