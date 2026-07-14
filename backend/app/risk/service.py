"""Explainable risk scoring service for simulated network changes."""

from __future__ import annotations

from collections.abc import Iterable

from app.domain.models import Service, TopologySpec
from app.risk.models import RiskAssessment, RiskFactorScore, RiskLevel, RiskRecommendation, RiskWeights
from app.simulation.models import ChangeSimulationResult


class RiskScoringService:
    """Score simulated network changes using deterministic weighted factors."""

    def __init__(self, weights: RiskWeights | None = None) -> None:
        self.weights = weights or RiskWeights()

    def assess_change(
        self,
        topology: TopologySpec,
        simulation_result: ChangeSimulationResult,
    ) -> RiskAssessment:
        impacted_service_ids = self._collect_impacted_service_ids(topology, simulation_result)
        impacted_services = [
            service for service in topology.services if service.id in impacted_service_ids
        ]
        impacted_sites = self._collect_impacted_sites(topology, simulation_result)

        factors = [
            self._factor_score(
                factor="affected_endpoints",
                weight=self.weights.affected_endpoints,
                raw_value=len(simulation_result.impact.affected_endpoints),
                normalized_score=self._normalize_count(
                    len(simulation_result.impact.affected_endpoints),
                    threshold=2,
                ),
                explanation=(
                    f"{len(simulation_result.impact.affected_endpoints)} endpoint(s) are affected."
                ),
            ),
            self._factor_score(
                factor="affected_devices",
                weight=self.weights.affected_devices,
                raw_value=len(simulation_result.impact.affected_devices),
                normalized_score=self._normalize_count(
                    len(simulation_result.impact.affected_devices),
                    threshold=2,
                ),
                explanation=(
                    f"{len(simulation_result.impact.affected_devices)} device(s) are directly affected."
                ),
            ),
            self._factor_score(
                factor="affected_critical_services",
                weight=self.weights.affected_critical_services,
                raw_value=sum(1 for service in impacted_services if service.critical),
                normalized_score=self._normalize_count(
                    sum(1 for service in impacted_services if service.critical),
                    threshold=1,
                ),
                explanation=(
                    f"{sum(1 for service in impacted_services if service.critical)} critical service(s) are affected."
                ),
            ),
            self._factor_score(
                factor="lost_reachability_paths",
                weight=self.weights.lost_reachability_paths,
                raw_value=len(simulation_result.impact.lost_reachability_paths),
                normalized_score=self._normalize_count(
                    len(simulation_result.impact.lost_reachability_paths),
                    threshold=1,
                ),
                explanation=(
                    f"{len(simulation_result.impact.lost_reachability_paths)} reachability path(s) are lost."
                ),
            ),
            self._factor_score(
                factor="affected_sites",
                weight=self.weights.affected_sites,
                raw_value=len(impacted_sites),
                normalized_score=self._normalize_count(len(impacted_sites), threshold=1),
                explanation=f"{len(impacted_sites)} site(s) are affected.",
            ),
            self._factor_score(
                factor="absence_of_redundancy",
                weight=self.weights.absence_of_redundancy,
                raw_value=simulation_result.impact.redundancy_available is False,
                normalized_score=1.0 if simulation_result.impact.redundancy_available is False else 0.0,
                explanation=(
                    "No redundant path remains after the change."
                    if simulation_result.impact.redundancy_available is False
                    else "Redundancy remains available after the change."
                ),
            ),
            self._factor_score(
                factor="change_complexity",
                weight=self.weights.change_complexity,
                raw_value=simulation_result.command_type,
                normalized_score=self._complexity_score(simulation_result.command_type),
                explanation=(
                    f"Command type '{simulation_result.command_type}' has "
                    f"{self._complexity_label(simulation_result.command_type)} complexity."
                ),
            ),
            self._factor_score(
                factor="rollback_difficulty",
                weight=self.weights.rollback_difficulty,
                raw_value=simulation_result.command_type,
                normalized_score=self._rollback_score(simulation_result.command_type),
                explanation=(
                    f"Rollback for '{simulation_result.command_type}' is "
                    f"{self._rollback_label(simulation_result.command_type)}."
                ),
            ),
        ]

        total_score = min(100, round(sum(factor.contribution for factor in factors)))
        risk_level = self._risk_level(total_score)
        recommendation = self._recommendation(risk_level)

        return RiskAssessment(
            total_score=total_score,
            risk_level=risk_level,
            factor_scores=factors,
            direct_impacts=simulation_result.direct_impacts,
            indirect_impacts=simulation_result.indirect_impacts,
            explanation=self._build_explanations(
                factors,
                impacted_services,
                simulation_result,
            ),
            recommendation=recommendation,
            suggested_maintenance_requirement=self._maintenance_requirement(risk_level),
            suggested_rollback_readiness=self._rollback_readiness(risk_level),
        )

    def _collect_impacted_service_ids(
        self,
        topology: TopologySpec,
        simulation_result: ChangeSimulationResult,
    ) -> set[str]:
        direct_and_indirect = set(simulation_result.direct_impacts) | set(simulation_result.indirect_impacts)
        affected_vlan_ids = {
            int(item.split(":", maxsplit=1)[1])
            for item in simulation_result.impact.affected_vlans
        }
        affected_subnet_ids = {
            item.split(":", maxsplit=1)[1]
            for item in simulation_result.impact.affected_subnets
        }
        affected_endpoint_ids = {
            item.split(":", maxsplit=1)[1]
            for item in simulation_result.impact.affected_endpoints
        }
        affected_device_ids = set(simulation_result.impact.affected_devices)

        impacted: set[str] = set()
        for service in topology.services:
            if f"service:{service.id}" in direct_and_indirect:
                impacted.add(service.id)
                continue
            if service.vlan_id is not None and service.vlan_id in affected_vlan_ids:
                impacted.add(service.id)
                continue
            if service.subnet_id is not None and service.subnet_id in affected_subnet_ids:
                impacted.add(service.id)
                continue
            if service.endpoint_id is not None and service.endpoint_id in affected_endpoint_ids:
                impacted.add(service.id)
                continue
            if service.device_id is not None and service.device_id in affected_device_ids:
                impacted.add(service.id)
        return impacted

    def _collect_impacted_sites(
        self,
        topology: TopologySpec,
        simulation_result: ChangeSimulationResult,
    ) -> list[str]:
        device_map = {device.id: device for device in topology.devices}
        endpoint_map = {endpoint.id: endpoint for endpoint in topology.endpoints}
        impacted_sites: set[str] = set()

        for device_id in simulation_result.impact.affected_devices:
            device = device_map.get(device_id)
            if device and device.site_id:
                impacted_sites.add(device.site_id)

        for endpoint_ref in simulation_result.impact.affected_endpoints:
            endpoint_id = endpoint_ref.split(":", maxsplit=1)[1]
            endpoint = endpoint_map.get(endpoint_id)
            if endpoint is None:
                continue
            device = device_map.get(endpoint.device_id)
            if device and device.site_id:
                impacted_sites.add(device.site_id)

        return sorted(impacted_sites)

    def _build_explanations(
        self,
        factors: Iterable[RiskFactorScore],
        impacted_services: list[Service],
        simulation_result: ChangeSimulationResult,
    ) -> list[str]:
        explanations: list[str] = []

        for factor in sorted(factors, key=lambda item: item.contribution, reverse=True):
            if factor.contribution <= 0:
                continue
            explanations.append(factor.explanation)

        for service in impacted_services:
            if service.critical:
                explanations.append(f"Critical service '{service.name}' is affected.")

        for path in simulation_result.impact.lost_reachability_paths:
            if path:
                explanations.append(f"Reachability path lost: {' -> '.join(path)}")

        if not explanations:
            explanations.append("No material risk factors were triggered by the simulation.")

        return explanations

    def _factor_score(
        self,
        *,
        factor: str,
        weight: int,
        raw_value: int | bool | str,
        normalized_score: float,
        explanation: str,
    ) -> RiskFactorScore:
        return RiskFactorScore(
            factor=factor,
            weight=weight,
            raw_value=raw_value,
            normalized_score=round(normalized_score, 4),
            contribution=round(weight * normalized_score, 2),
            explanation=explanation,
        )

    @staticmethod
    def _normalize_count(value: int, *, threshold: int) -> float:
        if value <= 0:
            return 0.0
        return min(1.0, value / threshold)

    @staticmethod
    def _complexity_score(command_type: str) -> float:
        scores = {
            "ENABLE_INTERFACE": 0.2,
            "ADD_VLAN_TO_TRUNK": 0.3,
            "ADD_STATIC_ROUTE": 0.3,
            "ADD_ACL_RULE": 0.4,
            "CHANGE_ACCESS_VLAN": 0.5,
            "CHANGE_GATEWAY": 0.6,
            "REMOVE_ACL_RULE": 0.7,
            "REMOVE_STATIC_ROUTE": 0.7,
            "REMOVE_VLAN_FROM_TRUNK": 0.8,
            "SHUTDOWN_INTERFACE": 0.8,
            "DELETE_VLAN": 1.0,
        }
        return scores.get(command_type, 0.5)

    @staticmethod
    def _complexity_label(command_type: str) -> str:
        score = RiskScoringService._complexity_score(command_type)
        if score >= 0.85:
            return "high"
        if score >= 0.6:
            return "moderate"
        return "low"

    @staticmethod
    def _rollback_score(command_type: str) -> float:
        scores = {
            "ENABLE_INTERFACE": 0.1,
            "ADD_VLAN_TO_TRUNK": 0.2,
            "ADD_STATIC_ROUTE": 0.2,
            "ADD_ACL_RULE": 0.3,
            "CHANGE_ACCESS_VLAN": 0.4,
            "CHANGE_GATEWAY": 0.5,
            "REMOVE_ACL_RULE": 0.6,
            "REMOVE_STATIC_ROUTE": 0.6,
            "REMOVE_VLAN_FROM_TRUNK": 0.7,
            "SHUTDOWN_INTERFACE": 0.7,
            "DELETE_VLAN": 0.9,
        }
        return scores.get(command_type, 0.5)

    @staticmethod
    def _rollback_label(command_type: str) -> str:
        score = RiskScoringService._rollback_score(command_type)
        if score >= 0.8:
            return "difficult"
        if score >= 0.5:
            return "moderately difficult"
        return "straightforward"

    @staticmethod
    def _risk_level(score: int) -> RiskLevel:
        if score >= 75:
            return "Critical"
        if score >= 50:
            return "High"
        if score >= 25:
            return "Medium"
        return "Low"

    @staticmethod
    def _recommendation(level: RiskLevel) -> RiskRecommendation:
        mapping: dict[RiskLevel, RiskRecommendation] = {
            "Low": "Safe to apply",
            "Medium": "Apply during maintenance window",
            "High": "Manual review required",
            "Critical": "Do not apply",
        }
        return mapping[level]

    @staticmethod
    def _maintenance_requirement(level: RiskLevel) -> str:
        mapping: dict[RiskLevel, str] = {
            "Low": "No special maintenance window required.",
            "Medium": "Use a planned maintenance window.",
            "High": "Use a tightly controlled maintenance window with approval.",
            "Critical": "Do not schedule until the risk is reduced and manually reviewed.",
        }
        return mapping[level]

    @staticmethod
    def _rollback_readiness(level: RiskLevel) -> str:
        mapping: dict[RiskLevel, str] = {
            "Low": "Standard rollback notes are sufficient.",
            "Medium": "Prepare tested rollback commands before execution.",
            "High": "Prepare a validated rollback plan and operator checklist.",
            "Critical": "Require a fully rehearsed rollback plan before any approval.",
        }
        return mapping[level]
