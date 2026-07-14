"""Reachability and validation result models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ValidationStage = Literal[
    "source_active",
    "source_addressing",
    "access_vlan",
    "trunk_propagation",
    "gateway_availability",
    "route_selection",
    "acl_evaluation",
    "destination_availability",
    "runtime_ping",
    "runtime_traceroute",
]

MismatchState = Literal["MATCH", "MODEL_RUNTIME_MISMATCH", "MODEL_ONLY"]


class RouteEvaluation(BaseModel):
    """Route considered during model evaluation."""

    route_type: str
    destination: str
    next_hop: str | None = None
    matched: bool = False


class ACLEvaluation(BaseModel):
    """ACL rule considered during model evaluation."""

    acl_name: str
    action: str
    source: str
    destination: str
    matched: bool = False


class ModelReachabilityResult(BaseModel):
    """Deterministic reachability result from desired-state analysis."""

    reachable: bool
    path: list[str] = Field(default_factory=list)
    evaluated_routes: list[RouteEvaluation] = Field(default_factory=list)
    evaluated_acls: list[ACLEvaluation] = Field(default_factory=list)
    failure_stage: ValidationStage | None = None
    technical_explanation: str


class RuntimeValidationResult(BaseModel):
    """Runtime reachability result against live devices."""

    reachable: bool | None = None
    traceroute_path: list[str] = Field(default_factory=list)
    interface_checks: list[str] = Field(default_factory=list)
    vlan_checks: list[str] = Field(default_factory=list)
    trunk_checks: list[str] = Field(default_factory=list)
    route_checks: list[str] = Field(default_factory=list)
    ospf_neighbor_checks: list[str] = Field(default_factory=list)
    acl_attachment_checks: list[str] = Field(default_factory=list)
    technical_explanation: str = "Runtime validation not executed."


class CombinedValidationResult(BaseModel):
    """Combined model/runtime validation output."""

    predicted_reachable: bool
    actual_reachable: bool | None = None
    state: MismatchState
    path: list[str] = Field(default_factory=list)
    evaluated_routes: list[RouteEvaluation] = Field(default_factory=list)
    evaluated_acls: list[ACLEvaluation] = Field(default_factory=list)
    failure_stage: ValidationStage | None = None
    technical_explanation: str
    suspected_reason: str | None = None
    runtime: RuntimeValidationResult | None = None

