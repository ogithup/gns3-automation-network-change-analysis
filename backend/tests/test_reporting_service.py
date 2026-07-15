"""Sprint 17 reporting tests."""

from __future__ import annotations

from pathlib import Path

from ipaddress import IPv4Address, IPv4Network

from app.addressing.models import AddressingPlan, SegmentAllocation
from app.api.repositories import ChangeRecord, DeploymentRecord, ReportRecord
from app.reporting.service import ReportingService
from app.risk.models import RiskAssessment, RiskFactorScore
from app.rollback.models import ApprovalRecord
from app.simulation.models import ChangeSimulationResult, ImpactSummary, NetworkSnapshot
from app.topology.service import TopologyService
from app.validation.models import CombinedValidationResult


def _load(name: str):
    return TopologyService.load_file(Path("..") / "examples" / name)


def test_reporting_service_generates_html_and_pdf() -> None:
    topology = _load("three-vlan-office.yaml")
    deployment = DeploymentRecord(
        id="dep-1",
        project_name=topology.project.name,
        status="Validated",
        topology=topology,
    )
    change = ChangeRecord(
        id="chg-1",
        deployment_id=deployment.id,
        status="Completed",
        command_type="REMOVE_VLAN_FROM_TRUNK",
        summary="Remove VLAN 30 from SW1 trunk",
        command_payload={
            "type": "REMOVE_VLAN_FROM_TRUNK",
            "device": "sw1",
            "interface": "GigabitEthernet0/1",
            "vlan_id": 30,
        },
        simulation=ChangeSimulationResult(
            snapshot=NetworkSnapshot(name="before-change", topology_yaml="project: demo"),
            command_type="REMOVE_VLAN_FROM_TRUNK",
            command_summary="Remove guest vlan from trunk",
            direct_impacts=["vlan:30"],
            indirect_impacts=["endpoint:guest-endpoint"],
            before_results=[],
            after_results=[],
            impact=ImpactSummary(
                affected_devices=["sw1"],
                affected_interfaces=["sw1:GigabitEthernet0/1"],
                affected_vlans=["vlan:30"],
                affected_subnets=["subnet:vlan30-subnet"],
                affected_endpoints=["endpoint:guest-endpoint"],
                affected_services=["service:guest-dhcp-service"],
                lost_reachability_paths=[["guest-endpoint", "admin-endpoint"]],
                changed_validation_tests=["test-guest-admin"],
                redundancy_available=False,
            ),
        ),
        risk=RiskAssessment(
            total_score=82,
            risk_level="Critical",
            recommendation="Do not apply",
            suggested_maintenance_requirement="Maintenance window required",
            suggested_rollback_readiness="Rollback plan must be ready",
            explanation=["Guest DHCP service is impacted."],
            factor_scores=[
                RiskFactorScore(
                    factor="affected_endpoints",
                    weight=20,
                    raw_value=1,
                    normalized_score=1.0,
                    contribution=20.0,
                    explanation="Guest users lose connectivity.",
                ),
            ],
            direct_impacts=["vlan:30"],
            indirect_impacts=["endpoint:guest-endpoint"],
        ),
        approval=ApprovalRecord(approved=True, reviewer="tester", note="Reviewed"),
    )
    address_plan = AddressingPlan(
        base_network="10.10.0.0/16",
        allocations=[
            SegmentAllocation(
                name="STUDENT",
                kind="segment",
                network=IPv4Network("10.10.0.0/24"),
                prefix_length=24,
                gateway=IPv4Address("10.10.0.1"),
                host_capacity=254,
                requested_hosts=200,
                host_assignments=[],
                explanation=["Largest subnet allocated first."],
            ),
        ],
        reserved_networks=[],
        unallocated_networks=[],
        report="STUDENT -> 10.10.0.0/24",
    )
    report_record = ReportRecord(
        id="rep-1",
        deployment_id=deployment.id,
        change_id=change.id,
        validations=[
            CombinedValidationResult(
                predicted_reachable=True,
                actual_reachable=True,
                state="MATCH",
                technical_explanation="Reachable via router-on-a-stick.",
            ),
        ],
        root_causes=[],
    )

    result = ReportingService().generate_report(
        deployment=deployment,
        change=change,
        report_record=report_record,
        address_plan=address_plan,
        user_requirements=["Guest VLAN impact analysis"],
    )

    assert "<html>" in result.html_content
    assert "Project Summary" in result.html_content
    assert result.pdf_base64
