"""Models for approved change deployment and rollback workflows."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.discovery.models import DiscoveredNetworkState
from app.risk.models import RiskAssessment
from app.simulation.models import ChangeSimulationResult
from app.validation.models import CombinedValidationResult


ChangeState = Literal[
    "Draft",
    "Simulated",
    "UnderReview",
    "Approved",
    "Applying",
    "Verifying",
    "Completed",
    "Failed",
    "RollingBack",
    "RolledBack",
]

RollbackStrategy = Literal[
    "inverse_commands",
    "saved_running_config",
    "project_reset",
]


class ApprovalRecord(BaseModel):
    """Approval metadata for a proposed change."""

    approved: bool
    reviewer: str | None = None
    note: str | None = None


class ConfigurationBackup(BaseModel):
    """Pre-change backup captured from a device."""

    device_id: str
    hostname: str
    content: str


class ChangeCommandPlan(BaseModel):
    """Minimal commands and rollback commands for one device."""

    device_id: str
    commands: list[str] = Field(default_factory=list)
    inverse_commands: list[str] = Field(default_factory=list)
    backup_restore_commands: list[str] = Field(default_factory=list)


class CommandOutputRecord(BaseModel):
    """Executed command and raw device output."""

    device_id: str
    command: str
    output: str
    success: bool = True


class ChangeAuditEntry(BaseModel):
    """Structured audit trail for the workflow."""

    state: ChangeState
    message: str
    device_id: str | None = None
    command: str | None = None
    output: str | None = None


class ValidationComparison(BaseModel):
    """Comparison between simulated and actual post-change behavior."""

    requirement_id: str
    predicted_reachable: bool
    actual_reachable: bool | None = None
    state: str
    suspected_reason: str | None = None
    technical_explanation: str


class ChangeDeploymentResult(BaseModel):
    """End-to-end Sprint 12 execution result."""

    change_id: str
    project_id: str
    project_name: str
    state: ChangeState
    command_type: str
    command_summary: str
    risk_assessment: RiskAssessment
    simulation_result: ChangeSimulationResult
    approval: ApprovalRecord
    backups: list[ConfigurationBackup] = Field(default_factory=list)
    command_plans: list[ChangeCommandPlan] = Field(default_factory=list)
    command_outputs: list[CommandOutputRecord] = Field(default_factory=list)
    audit_history: list[ChangeAuditEntry] = Field(default_factory=list)
    discovered_state_before: DiscoveredNetworkState | None = None
    discovered_state_after: DiscoveredNetworkState | None = None
    post_change_validations: list[CombinedValidationResult] = Field(default_factory=list)
    validation_comparisons: list[ValidationComparison] = Field(default_factory=list)
    rollback_strategy_used: RollbackStrategy | None = None
    rollback_executed: bool = False

