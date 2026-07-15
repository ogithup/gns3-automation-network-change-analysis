"""HTML and PDF reporting service."""

from __future__ import annotations

import base64
from html import escape
from uuid import uuid4

from app.addressing.models import AddressingPlan
from app.api.repositories import ChangeRecord, DeploymentRecord, ReportRecord
from app.reporting.models import GeneratedReport, ReportSection


class ReportingService:
    """Generate release-grade topology and change reports."""

    def generate_report(
        self,
        *,
        deployment: DeploymentRecord | None,
        change: ChangeRecord | None = None,
        report_record: ReportRecord | None = None,
        address_plan: AddressingPlan | None = None,
        user_requirements: list[str] | None = None,
    ) -> GeneratedReport:
        title = f"NetTwin AI Report - {deployment.project_name if deployment else 'Workflow'}"
        sections = _build_sections(
            deployment=deployment,
            change=change,
            report_record=report_record,
            address_plan=address_plan,
            user_requirements=user_requirements or [],
        )
        html_content = _render_html_report(title=title, sections=sections)
        pdf_content = _render_minimal_pdf(title=title, sections=sections)
        return GeneratedReport(
            id=str(uuid4()),
            title=title,
            html_content=html_content,
            pdf_base64=base64.b64encode(pdf_content).decode("ascii"),
            summary=f"{len(sections)} sections generated for {deployment.project_name if deployment else 'workflow'}.",
            sections=sections,
        )


def _build_sections(
    *,
    deployment: DeploymentRecord | None,
    change: ChangeRecord | None,
    report_record: ReportRecord | None,
    address_plan: AddressingPlan | None,
    user_requirements: list[str],
) -> list[ReportSection]:
    topology = deployment.topology if deployment else None
    validations = report_record.validations if report_record else []
    root_causes = report_record.root_causes if report_record else []
    sections: list[ReportSection] = []
    sections.append(
        ReportSection(
            title="Project Summary",
            summary="High-level overview of the project and workflow state.",
            data={
                "project_name": deployment.project_name if deployment else None,
                "deployment_status": deployment.status if deployment else None,
                "change_status": change.status if change else None,
                "user_requirements": user_requirements,
            },
        ),
    )
    if topology:
        sections.extend([
            ReportSection(
                title="Topology Diagram",
                summary="Mermaid topology diagram for quick visual review.",
                data={"mermaid": _build_mermaid(topology)},
            ),
            ReportSection(
                title="Device Inventory",
                summary="Vendor-neutral device and interface inventory.",
                data={"devices": [device.model_dump(mode="json", exclude_none=True) for device in topology.devices]},
            ),
            ReportSection(
                title="VLAN Plan",
                summary="VLAN, subnet, and gateway design.",
                data={"vlans": [vlan.model_dump(mode="json", exclude_none=True) for vlan in topology.vlans]},
            ),
            ReportSection(
                title="Routing Design",
                summary="Configured routes and routing protocols.",
                data={
                    "routes": [route.model_dump(mode="json", exclude_none=True) for route in topology.routes],
                    "routing_protocols": [protocol.model_dump(mode="json", exclude_none=True) for protocol in topology.routing_protocols],
                },
            ),
            ReportSection(
                title="ACL Policies",
                summary="Access-control intent in the planned topology.",
                data={"acls": [acl.model_dump(mode="json", exclude_none=True) for acl in topology.acls]},
            ),
        ])
    if address_plan:
        sections.append(
            ReportSection(
                title="IP Plan",
                summary="Allocated subnets and gateway plan.",
                data=address_plan.model_dump(mode="json"),
            ),
        )
    if deployment and deployment.discovered_state is not None:
        sections.append(
            ReportSection(
                title="Pre-change Network State",
                summary="Latest discovered network state snapshot.",
                data=deployment.discovered_state.model_dump(mode="json", exclude_none=True),
            ),
        )
    if change:
        sections.extend([
            ReportSection(
                title="Proposed Change",
                summary="Structured change command and approval context.",
                data={
                    "command_type": change.command_type,
                    "summary": change.summary,
                    "command_payload": change.command_payload,
                    "approval": change.approval.model_dump(mode="json", exclude_none=True) if change.approval else None,
                },
            ),
            ReportSection(
                title="Before/After Comparison",
                summary="Simulation and validation delta view.",
                data=change.simulation.model_dump(mode="json", exclude_none=True) if change.simulation else {},
            ),
            ReportSection(
                title="Impact and Risk",
                summary="Impacted objects and explainable risk assessment.",
                data=change.risk.model_dump(mode="json", exclude_none=True) if change.risk else {},
            ),
            ReportSection(
                title="Approval History",
                summary="Manual approval and reviewer note.",
                data=change.approval.model_dump(mode="json", exclude_none=True) if change.approval else {},
            ),
            ReportSection(
                title="Applied Commands",
                summary="Applied command payload and final status.",
                data={"command_payload": change.command_payload, "status": change.status},
            ),
        ])
    if validations:
        sections.append(
            ReportSection(
                title="Post-change Tests",
                summary="Validation results after deployment or apply.",
                data={"validations": [validation.model_dump(mode="json", exclude_none=True) for validation in validations]},
            ),
        )
    if root_causes:
        sections.append(
            ReportSection(
                title="Root Cause Findings",
                summary="Deterministic root-cause analysis results.",
                data={"root_causes": [root_cause.model_dump(mode="json", exclude_none=True) for root_cause in root_causes]},
            ),
        )
    sections.append(
        ReportSection(
            title="Final Recommendation",
            summary="Final operator recommendation generated from deterministic outputs.",
            data={
                "recommendation": change.risk.recommendation if change and change.risk else "Manual review required.",
                "rollback_status": change.status if change else "Not applicable",
                "final_result": deployment.status if deployment else "Not applicable",
            },
        ),
    )
    return sections


def _build_mermaid(topology) -> str:
    lines = ["graph LR"]
    for device in topology.devices:
        lines.append(f"    {device.id}[{device.hostname}]")
    for link in topology.links:
        lines.append(f"    {link.source_device} --> {link.target_device}")
    return "\n".join(lines)


def _render_html_report(*, title: str, sections: list[ReportSection]) -> str:
    parts = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8' />",
        f"<title>{escape(title)}</title>",
        "<style>body{font-family:Segoe UI,sans-serif;margin:32px;color:#1a2433}h1,h2{color:#11223a}section{margin-bottom:28px;padding:20px;border:1px solid #d8e1ea;border-radius:16px;background:#f8fbfd}pre{white-space:pre-wrap;background:#11223a;color:#e8f2ff;padding:16px;border-radius:12px;overflow:auto}</style>",
        "</head><body>",
        f"<h1>{escape(title)}</h1>",
    ]
    for section in sections:
        parts.append(f"<section><h2>{escape(section.title)}</h2><p>{escape(section.summary)}</p><pre>{escape(str(section.data))}</pre></section>")
    parts.append("</body></html>")
    return "".join(parts)


def _render_minimal_pdf(*, title: str, sections: list[ReportSection]) -> bytes:
    lines = [title, ""]
    for section in sections:
        lines.append(section.title)
        lines.append(section.summary)
        lines.append(str(section.data)[:140])
        lines.append("")
    content_lines = []
    y = 780
    for line in lines[:32]:
        safe_line = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content_lines.append(f"BT /F1 10 Tf 40 {y} Td ({safe_line}) Tj ET")
        y -= 18
        if y < 60:
            break
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Count 1 /Kids [3 0 R] >> endobj\n",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        b"5 0 obj << /Length " + str(len(stream)).encode("ascii") + b" >> stream\n" + stream + b"\nendstream endobj\n",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj)
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer << /Size {len(offsets)} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF"
        ).encode("ascii")
    )
    return bytes(pdf)
