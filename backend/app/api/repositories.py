"""In-memory repositories for Sprint 14 workflow orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.configuration.models import ConfigurationPreview
from app.discovery.models import DiscoveredNetworkState
from app.domain.models import TopologySpec
from app.gns3.models import GNS3DeploymentPlan
from app.impact.models import RootCauseAnalysisResult
from app.reporting.models import GeneratedReport
from app.risk.models import RiskAssessment
from app.rollback.models import ApprovalRecord
from app.simulation.models import ChangeSimulationResult
from app.validation.models import CombinedValidationResult
from app.addressing.models import AddressingPlan


@dataclass
class DeploymentRecord:
    id: str
    project_name: str
    status: str
    topology: TopologySpec
    correlation_id: str | None = None
    dry_run_plan: GNS3DeploymentPlan | None = None
    address_plan: AddressingPlan | None = None
    configuration_preview: ConfigurationPreview | None = None
    discovered_state: DiscoveredNetworkState | None = None
    validations: list[CombinedValidationResult] = field(default_factory=list)


@dataclass
class ChangeRecord:
    id: str
    deployment_id: str
    status: str
    command_type: str
    summary: str
    command_payload: dict[str, Any]
    correlation_id: str | None = None
    simulation: ChangeSimulationResult | None = None
    risk: RiskAssessment | None = None
    approval: ApprovalRecord | None = None
    root_causes: list[RootCauseAnalysisResult] = field(default_factory=list)


@dataclass
class ReportRecord:
    id: str
    deployment_id: str | None = None
    change_id: str | None = None
    validations: list[CombinedValidationResult] = field(default_factory=list)
    root_causes: list[RootCauseAnalysisResult] = field(default_factory=list)
    generated_report: GeneratedReport | None = None


class InMemoryDeploymentRepository:
    def __init__(self) -> None:
        self._items: dict[str, DeploymentRecord] = {}

    def save(self, record: DeploymentRecord) -> DeploymentRecord:
        self._items[record.id] = record
        return record

    def get(self, deployment_id: str) -> DeploymentRecord:
        return self._items[deployment_id]


class InMemoryChangeRepository:
    def __init__(self) -> None:
        self._items: dict[str, ChangeRecord] = {}

    def save(self, record: ChangeRecord) -> ChangeRecord:
        self._items[record.id] = record
        return record

    def get(self, change_id: str) -> ChangeRecord:
        return self._items[change_id]


class InMemoryReportRepository:
    def __init__(self) -> None:
        self._items: dict[str, ReportRecord] = {}

    def save(self, record: ReportRecord) -> ReportRecord:
        self._items[record.id] = record
        return record

    def get(self, report_id: str) -> ReportRecord:
        return self._items[report_id]

    def list(self) -> list[ReportRecord]:
        return list(self._items.values())
