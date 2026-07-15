"""Request and response models for the workflow API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.addressing.models import AddressingPlan, AddressingRequest
from app.ai.models import DeterministicExplanation, InterpretedChangePlan, InterpretedTopologyPlan
from app.configuration.models import ConfigurationPreview
from app.discovery.models import DiscoveredNetworkState
from app.gns3.models import GNS3DeploymentPlan, GNS3Version
from app.impact.models import RootCauseAnalysisResult
from app.reporting.models import GeneratedReport
from app.risk.models import RiskAssessment
from app.rollback.models import ApprovalRecord
from app.simulation.models import ChangeSimulationResult
from app.validation.models import CombinedValidationResult


class ErrorResponse(BaseModel):
    """Structured API error payload."""

    error: str
    detail: str
    correlation_id: str | None = None


class SpecificationValidateRequest(BaseModel):
    specification: dict[str, Any] | None = None
    yaml_content: str | None = None
    json_content: str | None = None


class SpecificationValidateResponse(BaseModel):
    valid: bool
    project_name: str
    device_count: int
    vlan_count: int


class DeploymentCreateRequest(SpecificationValidateRequest):
    project_name: str


class DeploymentRecordResponse(BaseModel):
    id: str
    project_name: str
    status: str
    correlation_id: str | None = None
    topology: dict[str, Any] | None = None
    dry_run_plan: GNS3DeploymentPlan | None = None
    configuration_preview: ConfigurationPreview | None = None
    discovered_state: DiscoveredNetworkState | None = None
    validations: list[CombinedValidationResult] = Field(default_factory=list)


class ChangeCreateRequest(BaseModel):
    deployment_id: str
    command: dict[str, Any]


class ChangeRecordResponse(BaseModel):
    id: str
    deployment_id: str
    status: str
    command_type: str
    summary: str
    correlation_id: str | None = None
    simulation: ChangeSimulationResult | None = None
    risk: RiskAssessment | None = None
    approval: ApprovalRecord | None = None
    root_causes: list[RootCauseAnalysisResult] = Field(default_factory=list)


class ApprovalRequest(BaseModel):
    reviewer: str
    approved: bool = True
    note: str | None = None


class RootCauseRequest(BaseModel):
    source_endpoint_id: str
    target_endpoint_id: str


class ReportResponse(BaseModel):
    id: str
    deployment_id: str | None = None
    change_id: str | None = None
    validations: list[CombinedValidationResult] = Field(default_factory=list)
    root_causes: list[RootCauseAnalysisResult] = Field(default_factory=list)


class GNS3ConnectivityResponse(BaseModel):
    reachable: bool
    version: GNS3Version | None = None
    detail: str


class NaturalLanguageTopologyRequest(BaseModel):
    prompt: str
    context: dict[str, Any] | None = None


class NaturalLanguageTopologyResponse(BaseModel):
    interpretation: InterpretedTopologyPlan


class NaturalLanguageChangeRequest(BaseModel):
    prompt: str
    deployment_id: str | None = None
    specification: dict[str, Any] | None = None
    context: dict[str, Any] | None = None


class NaturalLanguageChangeResponse(BaseModel):
    interpretation: InterpretedChangePlan


class AIExplanationRequest(BaseModel):
    simulation: dict[str, Any] | None = None
    risk: dict[str, Any] | None = None
    validations: list[dict[str, Any]] = Field(default_factory=list)


class AIExplanationResponse(BaseModel):
    explanation: DeterministicExplanation


class ReportGenerateRequest(BaseModel):
    deployment_id: str | None = None
    change_id: str | None = None
    address_plan: AddressingPlan | None = None
    user_requirements: list[str] = Field(default_factory=list)


class GeneratedReportResponse(BaseModel):
    report: GeneratedReport


__all__ = [
    "AddressingPlan",
    "AddressingRequest",
    "ApprovalRequest",
    "ChangeCreateRequest",
    "ChangeRecordResponse",
    "DeploymentCreateRequest",
    "DeploymentRecordResponse",
    "ErrorResponse",
    "GeneratedReportResponse",
    "GNS3ConnectivityResponse",
    "AIExplanationRequest",
    "AIExplanationResponse",
    "NaturalLanguageChangeRequest",
    "NaturalLanguageChangeResponse",
    "NaturalLanguageTopologyRequest",
    "NaturalLanguageTopologyResponse",
    "ReportGenerateRequest",
    "ReportResponse",
    "RootCauseRequest",
    "SpecificationValidateRequest",
    "SpecificationValidateResponse",
]
