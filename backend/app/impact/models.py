"""Deterministic root cause analysis models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


OSILayer = Literal["Layer1", "Layer2", "Layer3", "Layer4"]


class RootCauseFinding(BaseModel):
    """Single rule-engine finding for a failed test."""

    suspected_root_cause: str
    confidence_score: float
    osi_layer: OSILayer
    supporting_evidence: list[str] = Field(default_factory=list)
    commands_evaluated: list[str] = Field(default_factory=list)
    failed_checks: list[str] = Field(default_factory=list)
    recommended_remediation: str
    rollback_recommendation: str | None = None


class RootCauseAnalysisResult(BaseModel):
    """Root cause analysis for a failed connectivity scenario."""

    source_endpoint_id: str
    target_endpoint_id: str
    findings: list[RootCauseFinding] = Field(default_factory=list)
