"""Simulation models for change impact analysis."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.validation.models import CombinedValidationResult


class NetworkSnapshot(BaseModel):
    """Immutable simulation snapshot."""

    name: str
    topology_yaml: str


class ImpactSummary(BaseModel):
    """Calculated direct and indirect impact of a change."""

    affected_devices: list[str] = Field(default_factory=list)
    affected_interfaces: list[str] = Field(default_factory=list)
    affected_vlans: list[str] = Field(default_factory=list)
    affected_subnets: list[str] = Field(default_factory=list)
    affected_endpoints: list[str] = Field(default_factory=list)
    affected_services: list[str] = Field(default_factory=list)
    lost_reachability_paths: list[list[str]] = Field(default_factory=list)
    changed_validation_tests: list[str] = Field(default_factory=list)
    redundancy_available: bool | None = None


class ChangeSimulationResult(BaseModel):
    """Before/after simulation result for a proposed change."""

    snapshot: NetworkSnapshot
    command_type: str
    command_summary: str
    before_results: list[CombinedValidationResult] = Field(default_factory=list)
    after_results: list[CombinedValidationResult] = Field(default_factory=list)
    impact: ImpactSummary
    direct_impacts: list[str] = Field(default_factory=list)
    indirect_impacts: list[str] = Field(default_factory=list)
