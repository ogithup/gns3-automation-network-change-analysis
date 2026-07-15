import {
  AddressingPlan,
  AddressingRequest,
  ApprovalRecord,
  ChangeRecordResponse,
  DeploymentRecordResponse,
  Gns3ConnectivityResponse,
  ReportResponse,
  RootCauseAnalysisResult,
  SpecificationValidateResponse,
  TopologySpec,
  WorkflowProgressEvent,
} from "../types/workflow";

export const apiBaseUrl = "http://127.0.0.1:8000";
export const workflowApiBaseUrl = `${apiBaseUrl}/api/v1`;

function buildHeaders() {
  return {
    "Content-Type": "application/json",
    "X-Correlation-ID": crypto.randomUUID(),
  };
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${workflowApiBaseUrl}${path}`, {
    ...init,
    headers: {
      ...buildHeaders(),
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `API request failed for ${path}`);
  }

  return response.json() as Promise<T>;
}

export async function fetchHealth() {
  const response = await fetch(`${apiBaseUrl}/health`);

  if (!response.ok) {
    throw new Error("Backend health request failed");
  }

  return response.json() as Promise<{
    status: string;
    service: string;
    environment: string;
  }>;
}

export const workflowClient = {
  checkGns3Connectivity() {
    return requestJson<Gns3ConnectivityResponse>("/gns3/connectivity");
  },

  validateSpecification(specification: TopologySpec) {
    return requestJson<SpecificationValidateResponse>("/specifications/validate", {
      method: "POST",
      body: JSON.stringify({ specification }),
    });
  },

  createIpPlan(request: AddressingRequest) {
    return requestJson<AddressingPlan>("/ip-plans", {
      method: "POST",
      body: JSON.stringify(request),
    });
  },

  createDeployment(projectName: string, specification: TopologySpec) {
    return requestJson<DeploymentRecordResponse>("/deployments", {
      method: "POST",
      body: JSON.stringify({ project_name: projectName, specification }),
    });
  },

  getDeployment(deploymentId: string) {
    return requestJson<DeploymentRecordResponse>(`/deployments/${deploymentId}`);
  },

  configureDeployment(deploymentId: string) {
    return requestJson<DeploymentRecordResponse>(`/deployments/${deploymentId}/configure`, {
      method: "POST",
    });
  },

  discoverDeployment(deploymentId: string) {
    return requestJson<DeploymentRecordResponse>(`/deployments/${deploymentId}/discover`, {
      method: "POST",
    });
  },

  validateDeployment(deploymentId: string) {
    return requestJson<DeploymentRecordResponse>(`/deployments/${deploymentId}/validate`, {
      method: "POST",
    });
  },

  createChange(deploymentId: string, command: Record<string, unknown>) {
    return requestJson<ChangeRecordResponse>("/changes", {
      method: "POST",
      body: JSON.stringify({ deployment_id: deploymentId, command }),
    });
  },

  simulateChange(changeId: string) {
    return requestJson<ChangeRecordResponse>(`/changes/${changeId}/simulate`, {
      method: "POST",
    });
  },

  approveChange(changeId: string, approval: ApprovalRecord) {
    return requestJson<ChangeRecordResponse>(`/changes/${changeId}/approve`, {
      method: "POST",
      body: JSON.stringify(approval),
    });
  },

  applyChange(changeId: string) {
    return requestJson<ChangeRecordResponse>(`/changes/${changeId}/apply`, {
      method: "POST",
    });
  },

  rollbackChange(changeId: string) {
    return requestJson<ChangeRecordResponse>(`/changes/${changeId}/rollback`, {
      method: "POST",
    });
  },

  analyzeRootCause(changeId: string, sourceEndpointId: string, targetEndpointId: string) {
    return requestJson<ChangeRecordResponse>(`/changes/${changeId}/root-cause`, {
      method: "POST",
      body: JSON.stringify({
        source_endpoint_id: sourceEndpointId,
        target_endpoint_id: targetEndpointId,
      }),
    });
  },

  getReport(reportId: string) {
    return requestJson<ReportResponse>(`/reports/${reportId}`);
  },
};

export function createWorkflowSocket(
  workflowId: string,
  handlers: {
    onMessage: (event: WorkflowProgressEvent) => void;
    onError?: () => void;
  },
) {
  const socketUrl = `${workflowApiBaseUrl.replace("http://", "ws://").replace("https://", "wss://")}/ws/workflows/${workflowId}`;
  const socket = new WebSocket(socketUrl);
  socket.onmessage = (message) => {
    handlers.onMessage(JSON.parse(message.data) as WorkflowProgressEvent);
  };
  socket.onerror = () => {
    handlers.onError?.();
  };
  return socket;
}

export type RootCauseRequestPayload = {
  source_endpoint_id: string;
  target_endpoint_id: string;
};

export type RootCauseResponse = ChangeRecordResponse & {
  root_causes: RootCauseAnalysisResult[];
};
