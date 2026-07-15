"""Structured models for the natural language AI layer."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.domain.models import TopologySpec


class ClarificationItem(BaseModel):
    """A missing or ambiguous detail that requires user confirmation."""

    field: str
    question: str
    reason: str
    options: list[str] = Field(default_factory=list)


class SafetyFinding(BaseModel):
    """A detected prompt-injection or unsafe instruction pattern."""

    source: str
    pattern: str
    detail: str
    severity: str = "warning"


class InterpretedTopologyPlan(BaseModel):
    """Validated topology interpretation preview."""

    topology: TopologySpec | None = None
    clarifications: list[ClarificationItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    safety_findings: list[SafetyFinding] = Field(default_factory=list)
    blocked: bool = False
    preview: dict[str, Any] = Field(default_factory=dict)


class InterpretedChangePlan(BaseModel):
    """Validated change-command interpretation preview."""

    command: dict[str, Any] | None = None
    summary: str | None = None
    clarifications: list[ClarificationItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    safety_findings: list[SafetyFinding] = Field(default_factory=list)
    blocked: bool = False
    preview: dict[str, Any] = Field(default_factory=dict)


class DeterministicExplanation(BaseModel):
    """Human-readable explanation of deterministic outputs."""

    summary: str
    bullets: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class ProviderResult(BaseModel):
    """Low-level structured output returned by a provider."""

    payload: dict[str, Any] = Field(default_factory=dict)
    clarifications: list[ClarificationItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
