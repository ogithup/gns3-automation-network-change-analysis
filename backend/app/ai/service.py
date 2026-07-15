"""Structured natural-language AI service."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from app.ai.models import DeterministicExplanation, InterpretedChangePlan, InterpretedTopologyPlan
from app.ai.providers import HeuristicLLMProvider, LLMProvider
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
        self.provider = provider or HeuristicLLMProvider()
        self.topology_service = topology_service or TopologyService()

    def interpret_topology_request(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> InterpretedTopologyPlan:
        prompt_result = sanitize_prompt(prompt)
        sanitized_context, context_findings = sanitize_context(context or {})
        safety_findings = [*prompt_result.safety_findings, *context_findings]
        blocked = any(finding.severity == "high" for finding in safety_findings)
        if blocked:
            return InterpretedTopologyPlan(
                blocked=True,
                warnings=["Unsafe instructions detected. The request was blocked before provider execution."],
                safety_findings=safety_findings,
            )

        provider_result = self.provider.interpret_topology(
            prompt_result.sanitized_text,
            context=sanitized_context,
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
            return InterpretedTopologyPlan(
                blocked=False,
                warnings=[*provider_result.warnings, "Provider output failed TopologySpec validation."],
                safety_findings=safety_findings,
                preview={"validation_errors": error.errors()},
            )

        preview = {
            "project": topology.project.name,
            "device_count": len(topology.devices),
            "vlan_count": len(topology.vlans),
            "connectivity_requirements": [item.model_dump(mode="json") for item in topology.connectivity_requirements],
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
                warnings=["Unsafe change instructions detected. The request was blocked before provider execution."],
                safety_findings=safety_findings,
            )

        provider_result = self.provider.interpret_change(
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
                warnings=[*provider_result.warnings, f"Interpreted command could not be validated: {error}"],
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
                "config_diff": command.config_diff(topology, after_topology).model_dump(mode="json"),
                "affected_objects": command.affected_objects(),
            },
        )

    def explain_deterministic_results(self, *, payload: dict[str, Any]) -> DeterministicExplanation:
        provider_result = self.provider.explain_result(payload)
        return DeterministicExplanation.model_validate(provider_result.payload)


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
