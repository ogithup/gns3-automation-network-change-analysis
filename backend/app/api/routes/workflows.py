"""Workflow API routes for Sprint 14."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect

from app.addressing.models import AddressingPlan, AddressingRequest
from app.api.models import (
    AIExplanationRequest,
    AIExplanationResponse,
    ApprovalRequest,
    ChangeCreateRequest,
    ChangeRecordResponse,
    DeploymentCreateRequest,
    DeploymentRecordResponse,
    GeneratedReportResponse,
    GNS3ConnectivityResponse,
    NaturalLanguageChangeRequest,
    NaturalLanguageChangeResponse,
    NaturalLanguageTopologyRequest,
    NaturalLanguageTopologyResponse,
    ReportGenerateRequest,
    ReportResponse,
    RootCauseRequest,
    SpecificationValidateRequest,
    SpecificationValidateResponse,
)
from app.api.services import WorkflowService
from app.rollback.models import ApprovalRecord


router = APIRouter(prefix="/api/v1", tags=["workflow"])


def get_workflow_service(request: Request) -> WorkflowService:
    return request.app.state.workflow_service


@router.post("/specifications/validate", response_model=SpecificationValidateResponse)
async def validate_specification(
    payload: SpecificationValidateRequest,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> SpecificationValidateResponse:
    topology = workflow_service.load_topology(
        specification=payload.specification,
        yaml_content=payload.yaml_content,
        json_content=payload.json_content,
    )
    spec = workflow_service.validate_specification(topology)
    return SpecificationValidateResponse(
        valid=True,
        project_name=spec.project.name,
        device_count=len(spec.devices),
        vlan_count=len(spec.vlans),
    )


@router.post("/ip-plans", response_model=AddressingPlan)
async def create_ip_plan(
    request_body: AddressingRequest,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> AddressingPlan:
    return workflow_service.create_ip_plan(request_body)


@router.post("/ai/topology", response_model=NaturalLanguageTopologyResponse)
async def interpret_topology_prompt(
    request_body: NaturalLanguageTopologyRequest,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> NaturalLanguageTopologyResponse:
    return NaturalLanguageTopologyResponse(
        interpretation=workflow_service.interpret_topology_prompt(
            request_body.prompt,
            context=request_body.context,
        ),
    )


@router.post("/ai/change", response_model=NaturalLanguageChangeResponse)
async def interpret_change_prompt(
    request_body: NaturalLanguageChangeRequest,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> NaturalLanguageChangeResponse:
    specification = (
        workflow_service.load_topology(specification=request_body.specification)
        if request_body.specification is not None
        else None
    )
    return NaturalLanguageChangeResponse(
        interpretation=workflow_service.interpret_change_prompt(
            request_body.prompt,
            deployment_id=request_body.deployment_id,
            specification=specification,
            context=request_body.context,
        ),
    )


@router.post("/ai/explain", response_model=AIExplanationResponse)
async def explain_deterministic_results(
    request_body: AIExplanationRequest,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> AIExplanationResponse:
    return AIExplanationResponse(
        explanation=workflow_service.explain_ai_results(request_body.model_dump(mode="json", exclude_none=True)),
    )


@router.post("/deployments", response_model=DeploymentRecordResponse)
async def create_deployment(
    request_body: DeploymentCreateRequest,
    request: Request,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> DeploymentRecordResponse:
    topology = workflow_service.load_topology(
        specification=request_body.specification,
        yaml_content=request_body.yaml_content,
        json_content=request_body.json_content,
    )
    record = await workflow_service.create_deployment(
        project_name=request_body.project_name,
        topology=topology,
        correlation_id=request.state.correlation_id,
    )
    return _to_deployment_response(record)


@router.get("/deployments/{deployment_id}", response_model=DeploymentRecordResponse)
async def get_deployment(
    deployment_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> DeploymentRecordResponse:
    return _to_deployment_response(workflow_service.get_deployment(deployment_id))


@router.post("/deployments/{deployment_id}/configure", response_model=DeploymentRecordResponse)
async def configure_deployment(
    deployment_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> DeploymentRecordResponse:
    return _to_deployment_response(await workflow_service.configure_deployment(deployment_id))


@router.post("/deployments/{deployment_id}/discover", response_model=DeploymentRecordResponse)
async def discover_deployment(
    deployment_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> DeploymentRecordResponse:
    return _to_deployment_response(await workflow_service.discover_deployment(deployment_id))


@router.post("/deployments/{deployment_id}/validate", response_model=DeploymentRecordResponse)
async def validate_deployment(
    deployment_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> DeploymentRecordResponse:
    return _to_deployment_response(await workflow_service.validate_deployment(deployment_id))


@router.post("/deployments/{deployment_id}/cancel", response_model=DeploymentRecordResponse)
async def cancel_deployment(
    deployment_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> DeploymentRecordResponse:
    return _to_deployment_response(await workflow_service.cancel_deployment(deployment_id))


@router.post("/changes", response_model=ChangeRecordResponse)
async def create_change(
    request_body: ChangeCreateRequest,
    request: Request,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> ChangeRecordResponse:
    record = await workflow_service.create_change(
        request_body.deployment_id,
        request_body.command,
        request.state.correlation_id,
    )
    return _to_change_response(record)


@router.post("/changes/{change_id}/simulate", response_model=ChangeRecordResponse)
async def simulate_change(
    change_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> ChangeRecordResponse:
    return _to_change_response(await workflow_service.simulate_change(change_id))


@router.post("/changes/{change_id}/approve", response_model=ChangeRecordResponse)
async def approve_change(
    change_id: str,
    request_body: ApprovalRequest,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> ChangeRecordResponse:
    return _to_change_response(
        await workflow_service.approve_change(
            change_id,
            ApprovalRecord(
                approved=request_body.approved,
                reviewer=request_body.reviewer,
                note=request_body.note,
            ),
        ),
    )


@router.post("/changes/{change_id}/apply", response_model=ChangeRecordResponse)
async def apply_change(
    change_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> ChangeRecordResponse:
    return _to_change_response(await workflow_service.apply_change(change_id))


@router.post("/changes/{change_id}/rollback", response_model=ChangeRecordResponse)
async def rollback_change(
    change_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> ChangeRecordResponse:
    return _to_change_response(await workflow_service.rollback_change(change_id))


@router.post("/changes/{change_id}/cancel", response_model=ChangeRecordResponse)
async def cancel_change(
    change_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> ChangeRecordResponse:
    return _to_change_response(await workflow_service.cancel_change(change_id))


@router.get("/topologies/{deployment_id}")
async def get_topology(
    deployment_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict:
    record = workflow_service.get_deployment(deployment_id)
    return record.topology.model_dump(mode="json", exclude_none=True)


@router.post("/changes/{change_id}/root-cause", response_model=ChangeRecordResponse)
async def analyze_root_cause(
    change_id: str,
    request_body: RootCauseRequest,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> ChangeRecordResponse:
    record = workflow_service.get_change(change_id)
    deployment = workflow_service.get_deployment(record.deployment_id)
    if deployment.discovered_state is not None:
        record.root_causes = [
            workflow_service.root_cause_service.analyze_connectivity_failure(
                topology=deployment.topology,
                discovered_state=deployment.discovered_state,
                source_endpoint_id=request_body.source_endpoint_id,
                target_endpoint_id=request_body.target_endpoint_id,
            ),
        ]
    return _to_change_response(record)


@router.get("/reports/{report_id}", response_model=ReportResponse)
async def get_report(
    report_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> ReportResponse:
    record = workflow_service.get_report(report_id)
    return ReportResponse(
        id=record.id,
        deployment_id=record.deployment_id,
        change_id=record.change_id,
        validations=record.validations,
        root_causes=record.root_causes,
    )


@router.post("/reports/generate", response_model=GeneratedReportResponse)
async def generate_report(
    request_body: ReportGenerateRequest,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> GeneratedReportResponse:
    return GeneratedReportResponse(
        report=workflow_service.generate_report(
            deployment_id=request_body.deployment_id,
            change_id=request_body.change_id,
            address_plan=request_body.address_plan,
            user_requirements=request_body.user_requirements,
        ),
    )


@router.get("/gns3/connectivity", response_model=GNS3ConnectivityResponse)
async def gns3_connectivity(
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> GNS3ConnectivityResponse:
    reachable, version, detail = await workflow_service.check_gns3_connectivity()
    return GNS3ConnectivityResponse(reachable=reachable, version=version, detail=detail)


@router.websocket("/ws/workflows/{workflow_id}")
async def workflow_progress(websocket: WebSocket, workflow_id: str) -> None:
    await websocket.accept()
    service: WorkflowService = websocket.app.state.workflow_service
    for event in service.progress_hub.history(workflow_id):
        await websocket.send_json(event)
    queue = service.progress_hub.subscribe(workflow_id)
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        service.progress_hub.unsubscribe(workflow_id, queue)


def _to_deployment_response(record) -> DeploymentRecordResponse:
    return DeploymentRecordResponse(
        id=record.id,
        project_name=record.project_name,
        status=record.status,
        correlation_id=record.correlation_id,
        topology=record.topology.model_dump(mode="json", exclude_none=True),
        dry_run_plan=record.dry_run_plan,
        configuration_preview=record.configuration_preview,
        discovered_state=record.discovered_state,
        validations=record.validations,
    )


def _to_change_response(record) -> ChangeRecordResponse:
    return ChangeRecordResponse(
        id=record.id,
        deployment_id=record.deployment_id,
        status=record.status,
        command_type=record.command_type,
        summary=record.summary,
        correlation_id=record.correlation_id,
        simulation=record.simulation,
        risk=record.risk,
        approval=record.approval,
        root_causes=record.root_causes,
    )
