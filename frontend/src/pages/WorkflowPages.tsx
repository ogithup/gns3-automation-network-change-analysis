import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { workflowClient, fetchHealth } from "../api/client";
import { useWorkflowStore } from "../app/workflowStore";
import { EmptyState, JsonPanel, MetricTile, SectionCard, StatusPill } from "../components/Cards";
import { TopologyCanvas } from "../components/TopologyCanvas";
import { useWorkflowProgress } from "../hooks/useWorkflowProgress";
import {
  AddressingRequest,
  ChangeCommandPayload,
  DeterministicExplanation,
  GeneratedReport,
  RootCauseAnalysisResult,
  TopologySpec,
  WorkflowProgressEvent,
} from "../types/workflow";

function progressTone(status: string): "neutral" | "success" | "warning" | "danger" | "info" {
  const lowered = status.toLowerCase();
  if (lowered.includes("failed") || lowered.includes("rollback")) {
    return "danger";
  }
  if (lowered.includes("completed") || lowered.includes("validated") || lowered.includes("approved")) {
    return "success";
  }
  if (lowered.includes("creating") || lowered.includes("applying") || lowered.includes("simulating")) {
    return "warning";
  }
  return "info";
}

function deviceOptions(topology: TopologySpec) {
  return topology.devices.map((device) => ({ label: `${device.hostname} (${device.id})`, value: device.id }));
}

function endpointOptions(topology: TopologySpec) {
  return topology.endpoints.map((endpoint) => ({ label: `${endpoint.hostname} (${endpoint.id})`, value: endpoint.id }));
}

function latestWorkflowEvents(progressEvents: Record<string, WorkflowProgressEvent[]>, workflowId: string | null) {
  if (!workflowId) {
    return [];
  }
  return progressEvents[workflowId] ?? [];
}

function topologySummary(topology: TopologySpec) {
  return [
    { label: "Devices", value: topology.devices.length },
    { label: "Links", value: topology.links.length },
    { label: "VLANs", value: topology.vlans.length },
    { label: "Endpoints", value: topology.endpoints.length },
  ];
}

function validationLabel(topology: TopologySpec, index: number) {
  const requirement = topology.connectivity_requirements[index];
  if (!requirement) {
    return `Validation ${index + 1}`;
  }
  return `${requirement.source_endpoint_id} -> ${requirement.target_endpoint_id}`;
}

export function OverviewPage() {
  const { topologyDraft, activeDeployment, activeChange, progressEvents, selectedWorkflowId } = useWorkflowStore();
  const events = latestWorkflowEvents(progressEvents, selectedWorkflowId);

  return (
    <div className="page-grid">
      <SectionCard title="Workflow Snapshot" subtitle="Current draft, deployment, and change state.">
        <div className="metric-grid">
          {topologySummary(topologyDraft).map((item) => (
            <MetricTile key={item.label} label={item.label} value={item.value} tone="accent" />
          ))}
          <MetricTile label="Deployment state" value={activeDeployment?.status ?? "Not created"} tone="default" />
          <MetricTile label="Change state" value={activeChange?.status ?? "No draft change"} tone="default" />
        </div>
      </SectionCard>

      <SectionCard title="Topology Storyboard" subtitle="Draft topology and impact-ready visual language.">
        <TopologyCanvas topology={topologyDraft} deployment={activeDeployment} change={activeChange} mode="draft" />
      </SectionCard>

      <SectionCard title="Latest Workflow Events" subtitle="Live deployment or change application events replay here.">
        {events.length === 0 ? (
          <EmptyState title="No workflow yet" description="Create a deployment or change to start collecting progress events." />
        ) : (
          <div className="timeline">
            {events.map((event, index) => (
              <div key={`${event.status}-${index}`} className="timeline__item">
                <StatusPill value={event.status} tone={progressTone(event.status)} />
              </div>
            ))}
          </div>
        )}
      </SectionCard>
    </div>
  );
}

export function ConnectionPage() {
  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
  });
  const connectivityQuery = useQuery({
    queryKey: ["gns3-connectivity"],
    queryFn: workflowClient.checkGns3Connectivity,
  });

  return (
    <div className="page-grid">
      <SectionCard
        title="GNS3 Server Connection"
        subtitle="Checks backend availability and GNS3 REST reachability."
        actions={<button className="button button--secondary" onClick={() => void connectivityQuery.refetch()}>Reconnect</button>}
      >
        <div className="metric-grid">
          <MetricTile label="Backend health" value={healthQuery.data?.status ?? "Loading"} tone="success" />
          <MetricTile label="Service" value={healthQuery.data?.service ?? "NetTwin AI"} />
          <MetricTile label="Environment" value={healthQuery.data?.environment ?? "development"} />
          <MetricTile label="GNS3 reachable" value={connectivityQuery.data?.reachable ? "Yes" : "No"} tone={connectivityQuery.data?.reachable ? "success" : "danger"} />
        </div>
        <p className="inline-note">{connectivityQuery.data?.detail ?? "Waiting for GNS3 connectivity check."}</p>
      </SectionCard>

      <SectionCard title="Version Check" subtitle="Sprint 15 uses the workflow API already built in Sprint 14.">
        {connectivityQuery.data?.version ? (
          <div className="metric-grid">
            <MetricTile label="Version" value={connectivityQuery.data.version.version} tone="accent" />
            <MetricTile label="Local server" value={String(connectivityQuery.data.version.local)} />
          </div>
        ) : (
          <EmptyState title="No version payload" description="When GNS3 is reachable, the server version will appear here." />
        )}
      </SectionCard>
    </div>
  );
}

export function ProjectsPage() {
  const { deployments, activeDeployment, topologyDraft, upsertDeployment, setActiveDeployment } = useWorkflowStore();
  const createDeploymentMutation = useMutation({
    mutationFn: () => workflowClient.createDeployment(topologyDraft.project.name, topologyDraft),
    onSuccess: (deployment) => {
      upsertDeployment(deployment);
    },
  });

  return (
    <div className="page-grid">
      <SectionCard
        title="Network Project List"
        subtitle="Current workflow stores created deployments locally and on the backend workflow API."
        actions={<button className="button" onClick={() => createDeploymentMutation.mutate()}>Create Project</button>}
      >
        {deployments.length === 0 ? (
          <EmptyState title="No deployment records" description="Create a deployment from the current topology draft to seed the operator workflow." />
        ) : (
          <div className="list-grid">
            {deployments.map((deployment) => (
              <button
                key={deployment.id}
                className={`list-card ${activeDeployment?.id === deployment.id ? "list-card--active" : ""}`}
                onClick={() => setActiveDeployment(deployment)}
                type="button"
              >
                <strong>{deployment.project_name}</strong>
                <span>{deployment.id}</span>
                <StatusPill value={deployment.status} tone="info" />
              </button>
            ))}
          </div>
        )}
      </SectionCard>

      <SectionCard title="Project Metadata" subtitle="The full GNS3 project CRUD API is still limited, but deployment planning is live.">
        {activeDeployment ? <JsonPanel value={activeDeployment} /> : <EmptyState title="No project selected" description="Pick or create a deployment record." />}
      </SectionCard>
    </div>
  );
}

export function TopologyBuilderPage() {
  const store = useWorkflowStore();
  const [projectName, setProjectName] = useState(store.topologyDraft.project.name);
  const [prompt, setPrompt] = useState("Üç VLAN'lı küçük ofis ağı kur. Guest ağı Admin ağına erişemesin.");
  const interpretTopologyMutation = useMutation({
    mutationFn: (inputPrompt: string) =>
      workflowClient.interpretTopology(inputPrompt, {
        current_topology: store.topologyDraft,
      }),
    onSuccess: (response) => {
      if (response.interpretation.topology) {
        store.setTopologyDraft(response.interpretation.topology);
        setProjectName(response.interpretation.topology.project.name);
      }
    },
  });

  const saveName = () => {
    store.updateProjectName(projectName);
  };

  return (
    <div className="page-grid">
      <SectionCard
        title="Visual Topology Builder"
        subtitle="Undo, redo, autosave, and draft/current separation are handled locally."
        actions={(
          <div className="button-row">
            <button className="button button--secondary" onClick={store.undo}>Undo</button>
            <button className="button button--secondary" onClick={store.redo}>Redo</button>
          </div>
        )}
      >
        <div className="builder-toolbar">
          <label className="field">
            <span>Project name</span>
            <input value={projectName} onChange={(event) => setProjectName(event.target.value)} />
          </label>
          <button className="button" onClick={saveName}>Save Topology</button>
          <button className="button button--secondary" onClick={() => store.addDevice("router")}>Add Router</button>
          <button className="button button--secondary" onClick={() => store.addDevice("switch")}>Add Switch</button>
          <button className="button button--secondary" onClick={() => store.addDevice("endpoint")}>Add Endpoint</button>
          <button className="button button--secondary" onClick={() => store.addVlan()}>Add VLAN</button>
        </div>
        <TopologyCanvas topology={store.topologyDraft} deployment={store.activeDeployment} change={store.activeChange} mode="draft" />
      </SectionCard>

      <SectionCard title="Validation-safe Draft JSON" subtitle="The UI edits a vendor-neutral topology specification that can be sent directly to the backend.">
        <JsonPanel value={store.topologyDraft} />
      </SectionCard>

      <SectionCard
        title="Natural Language Topology"
        subtitle="Sprint 16 converts natural-language requirements into a validated TopologySpec preview."
        actions={<button className="button" onClick={() => interpretTopologyMutation.mutate(prompt)}>Interpret Requirement</button>}
      >
        <label className="field">
          <span>Requirement prompt</span>
          <textarea className="textarea" value={prompt} onChange={(event) => setPrompt(event.target.value)} />
        </label>
        {interpretTopologyMutation.data ? <JsonPanel value={interpretTopologyMutation.data.interpretation} /> : <EmptyState title="No AI interpretation yet" description="Submit a topology prompt to see the structured preview, clarifications, and warnings." />}
      </SectionCard>
    </div>
  );
}

export function AddressingPage() {
  const store = useWorkflowStore();
  const [request, setRequest] = useState<AddressingRequest>(store.addressRequest);
  const createPlanMutation = useMutation({
    mutationFn: (payload: AddressingRequest) => workflowClient.createIpPlan(payload),
    onSuccess: (plan) => {
      store.setAddressRequest(request);
      store.setAddressPlan(plan);
    },
  });

  const updateSegment = (index: number, field: "name" | "host_count", value: string) => {
    const nextSegments = request.segments.map((segment, segmentIndex) => (
      segmentIndex === index
        ? {
          ...segment,
          [field]: field === "host_count" ? Number(value) : value,
        }
        : segment
    ));
    setRequest({ ...request, segments: nextSegments });
  };

  return (
    <div className="page-grid">
      <SectionCard
        title="IP Address Plan"
        subtitle="Uses the Sprint 2 VLSM engine through the backend API."
        actions={<button className="button" onClick={() => createPlanMutation.mutate(request)}>Generate Address Plan</button>}
      >
        <div className="form-grid">
          <label className="field">
            <span>Base network</span>
            <input value={request.base_network} onChange={(event) => setRequest({ ...request, base_network: event.target.value })} />
          </label>
          {request.segments.map((segment, index) => (
            <div className="field-row" key={`${segment.name}-${index}`}>
              <label className="field">
                <span>Segment</span>
                <input value={segment.name} onChange={(event) => updateSegment(index, "name", event.target.value)} />
              </label>
              <label className="field">
                <span>Hosts</span>
                <input type="number" value={segment.host_count} onChange={(event) => updateSegment(index, "host_count", event.target.value)} />
              </label>
            </div>
          ))}
        </div>
      </SectionCard>

      <SectionCard title="Generated VLSM Output" subtitle="Gateway assignment and subnet exhaustion errors surface here.">
        {store.addressPlan ? <JsonPanel value={store.addressPlan} /> : <EmptyState title="No address plan yet" description="Run the planner to see deterministic subnet allocation." />}
      </SectionCard>
    </div>
  );
}

export function ConfigurationPage() {
  const store = useWorkflowStore();
  const activeDeployment = store.activeDeployment;
  const configureMutation = useMutation({
    mutationFn: (deploymentId: string) => workflowClient.configureDeployment(deploymentId),
    onSuccess: (deployment) => {
      store.upsertDeployment(deployment);
    },
  });

  return (
    <div className="page-grid">
      <SectionCard
        title="Configuration Preview"
        subtitle="Device-by-device rendered configs and hashes from Sprint 5."
        actions={activeDeployment ? <button className="button" onClick={() => configureMutation.mutate(activeDeployment.id)}>Generate Configurations</button> : undefined}
      >
        {!activeDeployment ? (
          <EmptyState title="No deployment selected" description="Create a deployment first so the backend can render the topology configuration preview." />
        ) : activeDeployment.configuration_preview ? (
          <div className="stack">
            {activeDeployment.configuration_preview.rendered_configurations.map((rendered) => (
              <article key={rendered.device_id} className="config-card">
                <div className="config-card__header">
                  <strong>{rendered.device_hostname}</strong>
                  <StatusPill value={rendered.content_hash.slice(0, 12)} tone="info" />
                </div>
                <pre>{rendered.content}</pre>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState title="No configuration preview yet" description="Use Generate Configurations to render IOSv, IOSvL2, and VPCS output." />
        )}
      </SectionCard>
    </div>
  );
}

export function DeploymentPage() {
  const store = useWorkflowStore();
  const activeDeployment = store.activeDeployment;
  useWorkflowProgress(activeDeployment?.id);

  const createDeploymentMutation = useMutation({
    mutationFn: () => workflowClient.createDeployment(store.topologyDraft.project.name, store.topologyDraft),
    onSuccess: (deployment) => {
      store.upsertDeployment(deployment);
    },
  });
  const configureMutation = useMutation({
    mutationFn: (deploymentId: string) => workflowClient.configureDeployment(deploymentId),
    onSuccess: (deployment) => {
      store.upsertDeployment(deployment);
    },
  });
  const discoverMutation = useMutation({
    mutationFn: (deploymentId: string) => workflowClient.discoverDeployment(deploymentId),
    onSuccess: (deployment) => {
      store.upsertDeployment(deployment);
    },
  });
  const validateMutation = useMutation({
    mutationFn: (deploymentId: string) => workflowClient.validateDeployment(deploymentId),
    onSuccess: (deployment) => {
      store.upsertDeployment(deployment);
    },
  });

  const events = latestWorkflowEvents(store.progressEvents, activeDeployment?.id ?? null);

  return (
    <div className="page-grid">
      <SectionCard
        title="Deployment Progress"
        subtitle="WebSocket-backed workflow status for create, configure, discover, and validate steps."
        actions={(
          <div className="button-row">
            <button className="button" onClick={() => createDeploymentMutation.mutate()}>Deploy</button>
            <button className="button button--secondary" disabled={!activeDeployment} onClick={() => activeDeployment && configureMutation.mutate(activeDeployment.id)}>Configure</button>
            <button className="button button--secondary" disabled={!activeDeployment} onClick={() => activeDeployment && discoverMutation.mutate(activeDeployment.id)}>Discover</button>
            <button className="button button--secondary" disabled={!activeDeployment} onClick={() => activeDeployment && validateMutation.mutate(activeDeployment.id)}>Run Validation</button>
          </div>
        )}
      >
        {activeDeployment ? (
          <div className="stack">
            <div className="metric-grid">
              <MetricTile label="Project" value={activeDeployment.project_name} tone="accent" />
              <MetricTile label="Status" value={activeDeployment.status} />
              <MetricTile label="Dry-run nodes" value={activeDeployment.dry_run_plan?.node_requests?.length ?? 0} />
              <MetricTile label="Dry-run links" value={activeDeployment.dry_run_plan?.link_requests?.length ?? 0} />
            </div>
            <div className="timeline">
              {events.map((event, index) => (
                <div key={`${event.status}-${index}`} className="timeline__item">
                  <StatusPill value={event.status} tone={progressTone(event.status)} />
                </div>
              ))}
            </div>
          </div>
        ) : (
          <EmptyState title="No deployment workflow" description="Press Deploy to create a backend workflow record and dry-run GNS3 plan." />
        )}
      </SectionCard>

      <SectionCard title="Dry-Run Plan" subtitle="Deterministic node placement and interface mapping from Sprint 4.">
        {activeDeployment?.dry_run_plan ? <JsonPanel value={activeDeployment.dry_run_plan} /> : <EmptyState title="No plan yet" description="Create a deployment to inspect the dry-run GNS3 resource plan." />}
      </SectionCard>
    </div>
  );
}

export function LiveTopologyPage() {
  const { activeDeployment, activeChange } = useWorkflowStore();

  return (
    <div className="page-grid">
      <SectionCard title="Live Network Topology" subtitle="Discovered state visualization with status-aware node styling.">
        {activeDeployment ? (
          <TopologyCanvas topology={activeDeployment.topology ?? defaultTopologyFallback()} deployment={activeDeployment} change={activeChange} mode="current" />
        ) : (
          <EmptyState title="No deployment selected" description="Run the deployment workflow through discover to visualize discovered state." />
        )}
      </SectionCard>

      <SectionCard title="Discovered State Details" subtitle="Interface state, VLAN, trunk, route, and ACL visibility.">
        {activeDeployment?.discovered_state ? <JsonPanel value={activeDeployment.discovered_state} /> : <EmptyState title="No discovered state" description="Discovery output will appear here after the Discover action." />}
      </SectionCard>
    </div>
  );
}

export function ValidationPage() {
  const { activeDeployment } = useWorkflowStore();
  return (
    <div className="page-grid">
      <SectionCard title="Validation Results" subtitle="Model and runtime-style reachability output from Sprint 8.">
        {!activeDeployment?.validations?.length ? (
          <EmptyState title="No validation results" description="Use Run Validation in the deployment flow to populate this screen." />
        ) : (
          <div className="list-grid">
            {activeDeployment.validations.map((validation, index) => (
              <article key={`${validation.state}-${index}`} className="list-card list-card--static">
                <strong>{validationLabel(activeDeployment.topology ?? defaultTopologyFallback(), index)}</strong>
                <StatusPill value={validation.predicted_reachable ? "Reachable" : "Blocked"} tone={validation.predicted_reachable ? "success" : "danger"} />
                <span>{validation.failure_stage ?? validation.state ?? "validated"}</span>
                <small>{validation.technical_explanation ?? validation.suspected_reason ?? "No explanation."}</small>
              </article>
            ))}
          </div>
        )}
      </SectionCard>
    </div>
  );
}

export function ChangeBuilderPage() {
  const store = useWorkflowStore();
  const topology = store.activeDeployment?.topology ?? store.topologyDraft;
  const [commandType, setCommandType] = useState("REMOVE_VLAN_FROM_TRUNK");
  const [device, setDevice] = useState(topology.devices.find((item) => item.type === "switch")?.id ?? topology.devices[0]?.id ?? "");
  const [iface, setIface] = useState("GigabitEthernet0/1");
  const [vlanId, setVlanId] = useState("20");
  const [reviewerSource, setReviewerSource] = useState(topology.endpoints[0]?.id ?? "");
  const [reviewerTarget, setReviewerTarget] = useState(topology.endpoints[1]?.id ?? "");
  const [naturalLanguagePrompt, setNaturalLanguagePrompt] = useState("STUDENT VLAN'ını trunk bağlantısından kaldır.");
  const [explanation, setExplanation] = useState<DeterministicExplanation | null>(null);

  const createChangeMutation = useMutation({
    mutationFn: ({ deploymentId, payload }: { deploymentId: string; payload: ChangeCommandPayload }) =>
      workflowClient.createChange(deploymentId, payload),
    onSuccess: (change) => {
      store.upsertChange(change);
    },
  });
  const simulateChangeMutation = useMutation({
    mutationFn: (changeId: string) => workflowClient.simulateChange(changeId),
    onSuccess: (change) => {
      store.upsertChange(change);
    },
  });
  const analyzeRootCauseMutation = useMutation({
    mutationFn: ({ changeId, source, target }: { changeId: string; source: string; target: string }) =>
      workflowClient.analyzeRootCause(changeId, source, target),
    onSuccess: (change) => {
      store.upsertChange(change);
    },
  });
  const interpretChangeMutation = useMutation({
    mutationFn: (prompt: string) =>
      workflowClient.interpretChange(prompt, {
        deploymentId: store.activeDeployment?.id,
        specification: store.activeDeployment ? undefined : topology,
      }),
    onSuccess: (response) => {
      const command = response.interpretation.command;
      if (command?.type) {
        setCommandType(String(command.type));
        if (typeof command.device === "string") {
          setDevice(command.device);
        }
        if (typeof command.interface === "string") {
          setIface(command.interface);
        }
        if (typeof command.vlan_id === "number" || typeof command.vlan_id === "string") {
          setVlanId(String(command.vlan_id));
        }
      }
    },
  });
  const explainMutation = useMutation({
    mutationFn: () =>
      workflowClient.explainDeterministicResults({
        simulation: store.activeChange?.simulation as Record<string, unknown> | undefined,
        risk: store.activeChange?.risk as Record<string, unknown> | undefined,
        validations: (store.activeDeployment?.validations ?? []) as Array<Record<string, unknown>>,
      }),
    onSuccess: (response) => {
      setExplanation(response.explanation);
    },
  });

  const commandPayload = useMemo<ChangeCommandPayload>(() => {
    switch (commandType) {
      case "SHUTDOWN_INTERFACE":
      case "ENABLE_INTERFACE":
        return { type: commandType, device, interface: iface };
      case "DELETE_VLAN":
        return { type: commandType, vlan_id: Number(vlanId) };
      default:
        return { type: commandType, device, interface: iface, vlan_id: Number(vlanId) };
    }
  }, [commandType, device, iface, vlanId]);

  return (
    <div className="page-grid">
      <SectionCard
        title="Change Builder"
        subtitle="Typed command construction backed by Sprint 9 command models."
        actions={(
          <div className="button-row">
            <button
              className="button"
              disabled={!store.activeDeployment}
              onClick={() => store.activeDeployment && createChangeMutation.mutate({ deploymentId: store.activeDeployment.id, payload: commandPayload })}
            >
              Build Change
            </button>
            <button
              className="button button--secondary"
              disabled={!store.activeChange}
              onClick={() => store.activeChange && simulateChangeMutation.mutate(store.activeChange.id)}
            >
              Simulate
            </button>
          </div>
        )}
      >
        <div className="form-grid">
          <label className="field">
            <span>Change type</span>
            <select value={commandType} onChange={(event) => setCommandType(event.target.value)}>
              <option value="REMOVE_VLAN_FROM_TRUNK">Remove VLAN from trunk</option>
              <option value="ADD_VLAN_TO_TRUNK">Add VLAN to trunk</option>
              <option value="SHUTDOWN_INTERFACE">Shutdown interface</option>
              <option value="ENABLE_INTERFACE">Enable interface</option>
              <option value="DELETE_VLAN">Delete VLAN</option>
            </select>
          </label>
          <label className="field">
            <span>Device</span>
            <select value={device} onChange={(event) => setDevice(event.target.value)}>
              {deviceOptions(topology).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Interface</span>
            <input value={iface} onChange={(event) => setIface(event.target.value)} />
          </label>
          <label className="field">
            <span>VLAN</span>
            <input value={vlanId} onChange={(event) => setVlanId(event.target.value)} />
          </label>
        </div>
        <JsonPanel value={commandPayload} />
      </SectionCard>

      <SectionCard
        title="Root Cause Probe"
        subtitle="On-demand deterministic diagnosis for a selected failed path."
        actions={store.activeChange ? (
          <button
            className="button button--secondary"
            onClick={() => analyzeRootCauseMutation.mutate({ changeId: store.activeChange!.id, source: reviewerSource, target: reviewerTarget })}
          >
            Analyze Root Cause
          </button>
        ) : undefined}
      >
        <div className="field-row">
          <label className="field">
            <span>Source endpoint</span>
            <select value={reviewerSource} onChange={(event) => setReviewerSource(event.target.value)}>
              {endpointOptions(topology).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Target endpoint</span>
            <select value={reviewerTarget} onChange={(event) => setReviewerTarget(event.target.value)}>
              {endpointOptions(topology).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
        </div>
        {store.activeChange?.root_causes?.length ? <JsonPanel value={store.activeChange.root_causes} /> : <EmptyState title="No root-cause analysis yet" description="Run Analyze Root Cause after a simulated or applied change." />}
      </SectionCard>

      <SectionCard
        title="Natural Language Change"
        subtitle="Sprint 16 converts natural-language change requests into typed NetworkChangeCommand previews."
        actions={(
          <div className="button-row">
            <button className="button" onClick={() => interpretChangeMutation.mutate(naturalLanguagePrompt)}>Interpret Change</button>
            <button className="button button--secondary" disabled={!store.activeChange?.simulation} onClick={() => explainMutation.mutate()}>Explain Result</button>
          </div>
        )}
      >
        <label className="field">
          <span>Change request</span>
          <textarea className="textarea" value={naturalLanguagePrompt} onChange={(event) => setNaturalLanguagePrompt(event.target.value)} />
        </label>
        {interpretChangeMutation.data ? <JsonPanel value={interpretChangeMutation.data.interpretation} /> : <EmptyState title="No interpreted change yet" description="Write a natural-language change request to populate the typed command preview." />}
        {explanation ? <JsonPanel value={explanation} /> : null}
      </SectionCard>
    </div>
  );
}

export function ComparisonPage() {
  const { activeDeployment, activeChange } = useWorkflowStore();

  return (
    <div className="page-grid">
      <SectionCard title="Before / After Comparison" subtitle="Simulation output and affected object deltas.">
        {activeChange?.simulation ? (
          <div className="comparison-grid">
            <div>
              <h3>Before</h3>
              <JsonPanel value={activeChange.simulation.before_results} />
            </div>
            <div>
              <h3>After</h3>
              <JsonPanel value={activeChange.simulation.after_results} />
            </div>
          </div>
        ) : (
          <EmptyState title="No simulation results" description="Simulate a change to unlock before/after reachability and impact views." />
        )}
      </SectionCard>

      <SectionCard title="Impact Topology" subtitle="Direct and indirect impacts are highlighted visually.">
        {activeDeployment?.topology ? (
          <TopologyCanvas topology={activeDeployment.topology} deployment={activeDeployment} change={activeChange} mode="impact" />
        ) : (
          <EmptyState title="No deployment topology" description="Create a deployment first." />
        )}
      </SectionCard>
    </div>
  );
}

export function RiskPage() {
  const { activeChange } = useWorkflowStore();
  const risk = activeChange?.risk;

  return (
    <div className="page-grid">
      <SectionCard title="Impact and Risk Report" subtitle="Explainable scoring from Sprint 11.">
        {risk ? (
          <>
            <div className="metric-grid">
              <MetricTile label="Risk score" value={risk.total_score} tone="danger" />
              <MetricTile label="Level" value={risk.risk_level} tone="accent" />
              <MetricTile label="Recommendation" value={risk.recommendation} tone="accent" />
              <MetricTile label="Maintenance" value={risk.suggested_maintenance_requirement} />
            </div>
            <JsonPanel value={risk} />
          </>
        ) : (
          <EmptyState title="No risk result" description="Simulate a change to calculate risk." />
        )}
      </SectionCard>
    </div>
  );
}

export function ApprovalPage() {
  const store = useWorkflowStore();
  const [reviewer, setReviewer] = useState("operator");
  const [note, setNote] = useState("Simulation reviewed.");
  useWorkflowProgress(store.activeChange?.id);

  const approveMutation = useMutation({
    mutationFn: ({ changeId, approved }: { changeId: string; approved: boolean }) =>
      workflowClient.approveChange(changeId, { reviewer, approved, note }),
    onSuccess: (change) => {
      store.upsertChange(change);
    },
  });
  const applyMutation = useMutation({
    mutationFn: (changeId: string) => workflowClient.applyChange(changeId),
    onSuccess: (change) => {
      store.upsertChange(change);
      if (store.activeDeployment) {
        workflowClient.getDeployment(store.activeDeployment.id).then((deployment) => store.upsertDeployment(deployment)).catch(() => undefined);
      }
    },
  });

  return (
    <div className="page-grid">
      <SectionCard
        title="Change Approval"
        subtitle="Approval gating before apply. The current backend workflow API enforces simulation and approval first."
        actions={store.activeChange ? (
          <div className="button-row">
            <button className="button" onClick={() => approveMutation.mutate({ changeId: store.activeChange!.id, approved: true })}>Approve</button>
            <button className="button button--danger" onClick={() => approveMutation.mutate({ changeId: store.activeChange!.id, approved: false })}>Reject</button>
            <button className="button button--secondary" onClick={() => applyMutation.mutate(store.activeChange!.id)}>Apply Change</button>
          </div>
        ) : undefined}
      >
        <div className="field-row">
          <label className="field">
            <span>Reviewer</span>
            <input value={reviewer} onChange={(event) => setReviewer(event.target.value)} />
          </label>
          <label className="field">
            <span>Note</span>
            <input value={note} onChange={(event) => setNote(event.target.value)} />
          </label>
        </div>
        {store.activeChange ? <JsonPanel value={store.activeChange} /> : <EmptyState title="No change selected" description="Build and simulate a change before approval." />}
      </SectionCard>
    </div>
  );
}

export function RollbackPage() {
  const store = useWorkflowStore();
  const rollbackMutation = useMutation({
    mutationFn: (changeId: string) => workflowClient.rollbackChange(changeId),
    onSuccess: (change) => {
      store.upsertChange(change);
      if (store.activeDeployment) {
        workflowClient.getDeployment(store.activeDeployment.id).then((deployment) => store.upsertDeployment(deployment)).catch(() => undefined);
      }
    },
  });

  return (
    <div className="page-grid">
      <SectionCard
        title="Rollback"
        subtitle="Inverse command strategy is already exposed by the backend."
        actions={store.activeChange ? <button className="button button--danger" onClick={() => rollbackMutation.mutate(store.activeChange!.id)}>Rollback</button> : undefined}
      >
        {store.activeChange ? (
          <div className="stack">
            <p className="inline-note">Available strategy in the current workflow API: inverse-command rollback on the active change record.</p>
            <JsonPanel value={store.activeChange} />
          </div>
        ) : (
          <EmptyState title="No active change" description="Run an apply workflow before triggering rollback." />
        )}
      </SectionCard>
    </div>
  );
}

export function AuditPage() {
  const { activeDeployment, activeChange, progressEvents, addressPlan } = useWorkflowStore();
  const deploymentEvents = activeDeployment ? progressEvents[activeDeployment.id] ?? [] : [];
  const changeEvents = activeChange ? progressEvents[activeChange.id] ?? [] : [];
  const [generatedReport, setGeneratedReport] = useState<GeneratedReport | null>(null);
  const generateReportMutation = useMutation({
    mutationFn: () =>
      workflowClient.generateReport({
        deploymentId: activeDeployment?.id,
        changeId: activeChange?.id,
        addressPlan,
        userRequirements: [activeDeployment?.project_name ?? "workflow report"],
      }),
    onSuccess: (response) => {
      setGeneratedReport(response.report);
    },
  });

  return (
    <div className="page-grid">
      <SectionCard title="Audit History" subtitle="Workflow events, state transitions, and command outcomes.">
        <div className="comparison-grid">
          <div>
            <h3>Deployment events</h3>
            {deploymentEvents.length ? deploymentEvents.map((event, index) => (
              <div key={`${event.status}-${index}`} className="timeline__item">
                <StatusPill value={event.status} tone={progressTone(event.status)} />
              </div>
            )) : <EmptyState title="No deployment events" description="Run deployment actions to populate this timeline." />}
          </div>
          <div>
            <h3>Change events</h3>
            {changeEvents.length ? changeEvents.map((event, index) => (
              <div key={`${event.status}-${index}`} className="timeline__item">
                <StatusPill value={event.status} tone={progressTone(event.status)} />
              </div>
            )) : <EmptyState title="No change events" description="Run change simulation or apply to populate this timeline." />}
          </div>
        </div>
      </SectionCard>

      <SectionCard title="Latest Root-Cause Evidence" subtitle="Any post-change failed validations and RCA output stay visible here.">
        {activeChange?.root_causes?.length ? <RootCauseView rootCauses={activeChange.root_causes} /> : <EmptyState title="No RCA output" description="Root-cause results will show up after the analysis step." />}
      </SectionCard>

      <SectionCard
        title="Generated Report"
        subtitle="Sprint 17 creates HTML and PDF-ready report artifacts from topology, change, validation, and risk state."
        actions={<button className="button" disabled={!activeDeployment} onClick={() => generateReportMutation.mutate()}>Generate Report</button>}
      >
        {generatedReport ? (
          <div className="stack">
            <div className="metric-grid">
              <MetricTile label="Report title" value={generatedReport.title} tone="accent" />
              <MetricTile label="Sections" value={generatedReport.sections.length} />
            </div>
            <div className="report-preview" dangerouslySetInnerHTML={{ __html: generatedReport.html_content }} />
            <a
              className="button button--secondary"
              download={`${generatedReport.id}.pdf`}
              href={`data:application/pdf;base64,${generatedReport.pdf_base64}`}
            >
              Download PDF
            </a>
          </div>
        ) : (
          <EmptyState title="No report generated" description="Generate a report after deployment and change analysis to preview the release-style artifact." />
        )}
      </SectionCard>
    </div>
  );
}

function RootCauseView(props: { rootCauses: RootCauseAnalysisResult[] }) {
  return (
    <div className="stack">
      {props.rootCauses.map((rootCause, index) => (
        <article key={`${rootCause.source_endpoint_id}-${rootCause.target_endpoint_id}-${index}`} className="list-card list-card--static">
          <strong>{rootCause.source_endpoint_id} {"->"} {rootCause.target_endpoint_id}</strong>
          {rootCause.findings.map((finding, findingIndex) => (
            <div key={`${finding.suspected_root_cause}-${findingIndex}`} className="stack">
              <StatusPill value={`${finding.osi_layer} ${Math.round(finding.confidence_score * 100)}%`} tone="warning" />
              <span>{finding.suspected_root_cause}</span>
              <small>{finding.recommended_remediation}</small>
            </div>
          ))}
        </article>
      ))}
    </div>
  );
}

function defaultTopologyFallback(): TopologySpec {
  return {
    project: { name: "draft" },
    sites: [],
    devices: [],
    links: [],
    vlans: [],
    subnets: [],
    endpoints: [],
    routes: [],
    routing_protocols: [],
    acls: [],
    services: [],
    connectivity_requirements: [],
    validation_tests: [],
  };
}
