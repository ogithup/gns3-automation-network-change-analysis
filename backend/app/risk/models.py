"""Risk scoring models for simulated network changes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


RiskLevel = Literal["Low", "Medium", "High", "Critical"]
RiskRecommendation = Literal[
    "Safe to apply",
    "Apply during maintenance window",
    "Manual review required",
    "Do not apply",
]


class RiskWeights(BaseModel):
    """Configurable factor weights contributing to the final score."""

    affected_endpoints: int = 20
    affected_devices: int = 10
    affected_critical_services: int = 25
    lost_reachability_paths: int = 15
    affected_sites: int = 10
    absence_of_redundancy: int = 15
    change_complexity: int = 5
    rollback_difficulty: int = 10


class RiskFactorScore(BaseModel):
    """Explainable contribution of a single risk factor."""

    factor: str
    weight: int
    raw_value: int | bool | str
    normalized_score: float
    contribution: float
    explanation: str


class RiskAssessment(BaseModel):
    """Deterministic and explainable risk assessment result."""

    total_score: int
    risk_level: RiskLevel
    factor_scores: list[RiskFactorScore] = Field(default_factory=list)
    direct_impacts: list[str] = Field(default_factory=list)
    indirect_impacts: list[str] = Field(default_factory=list)
    explanation: list[str] = Field(default_factory=list)
    recommendation: RiskRecommendation
    suggested_maintenance_requirement: str
    suggested_rollback_readiness: str

