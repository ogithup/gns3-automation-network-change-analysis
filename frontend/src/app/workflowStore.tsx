import {
  PropsWithChildren,
  createContext,
  useContext,
  useEffect,
  useMemo,
  useReducer,
} from "react";

import { defaultTopology } from "./defaultTopology";
import {
  AddressingPlan,
  AddressingRequest,
  ChangeRecordResponse,
  DeploymentRecordResponse,
  DeviceType,
  SavedTopologyRecord,
  TopologySpec,
  WorkflowProgressEvent,
} from "../types/workflow";

type WorkflowState = {
  topologyDraft: TopologySpec;
  history: TopologySpec[];
  future: TopologySpec[];
  addressRequest: AddressingRequest;
  addressPlan: AddressingPlan | null;
  activeDeployment: DeploymentRecordResponse | null;
  deployments: DeploymentRecordResponse[];
  savedTopologies: SavedTopologyRecord[];
  activeTopologyId: string | null;
  activeChange: ChangeRecordResponse | null;
  changes: ChangeRecordResponse[];
  progressEvents: Record<string, WorkflowProgressEvent[]>;
  selectedWorkflowId: string | null;
};

type WorkflowStore = WorkflowState & {
  setTopologyDraft: (topology: TopologySpec) => void;
  updateProjectName: (name: string) => void;
  updateDeviceHostname: (deviceId: string, hostname: string) => void;
  addDevice: (deviceType: DeviceType) => void;
  addLink: (sourceDeviceId: string, sourceInterface: string, targetDeviceId: string, targetInterface: string) => void;
  addVlan: () => void;
  undo: () => void;
  redo: () => void;
  setAddressRequest: (request: AddressingRequest) => void;
  setAddressPlan: (plan: AddressingPlan | null) => void;
  setActiveDeployment: (deployment: DeploymentRecordResponse | null) => void;
  upsertDeployment: (deployment: DeploymentRecordResponse) => void;
  saveTopology: (name?: string) => void;
  loadSavedTopology: (topologyId: string) => void;
  deleteSavedTopology: (topologyId: string) => void;
  resetDraftToDefault: () => void;
  setActiveChange: (change: ChangeRecordResponse | null) => void;
  upsertChange: (change: ChangeRecordResponse) => void;
  appendProgressEvent: (workflowId: string, event: WorkflowProgressEvent) => void;
  selectWorkflow: (workflowId: string | null) => void;
  resetWorkflow: () => void;
};

type Action =
  | { type: "SET_TOPOLOGY"; topology: TopologySpec }
  | { type: "UNDO" }
  | { type: "REDO" }
  | { type: "SET_ADDRESS_REQUEST"; request: AddressingRequest }
  | { type: "SET_ADDRESS_PLAN"; plan: AddressingPlan | null }
  | { type: "UPSERT_DEPLOYMENT"; deployment: DeploymentRecordResponse }
  | { type: "SET_ACTIVE_DEPLOYMENT"; deployment: DeploymentRecordResponse | null }
  | { type: "SAVE_TOPOLOGY"; record: SavedTopologyRecord }
  | { type: "LOAD_SAVED_TOPOLOGY"; topologyId: string }
  | { type: "DELETE_SAVED_TOPOLOGY"; topologyId: string }
  | { type: "UPSERT_CHANGE"; change: ChangeRecordResponse }
  | { type: "SET_ACTIVE_CHANGE"; change: ChangeRecordResponse | null }
  | { type: "APPEND_PROGRESS"; workflowId: string; event: WorkflowProgressEvent }
  | { type: "SELECT_WORKFLOW"; workflowId: string | null }
  | { type: "RESET" };

const STORAGE_KEY = "nettwin-ai-sprint15";

function normalizeTopology(topology: TopologySpec): TopologySpec {
  const endpointsByDeviceId = new Map(
    topology.endpoints.map((endpoint) => [endpoint.device_id, endpoint]),
  );
  const firstVlan = topology.vlans[0];
  const firstSubnet = topology.subnets.find((subnet) => subnet.vlan_id === firstVlan?.vlan_id);
  const synthesizedEndpoints = topology.devices
    .filter((device) => device.type === "endpoint" && !endpointsByDeviceId.has(device.id))
    .map((device, index) => ({
      id: `${device.id}-endpoint`,
      device_id: device.id,
      hostname: device.hostname,
      ip_address: firstVlan ? `192.168.${firstVlan.vlan_id}.${10 + topology.endpoints.length + index}` : `192.168.1.${10 + topology.endpoints.length + index}`,
      vlan_id: firstVlan?.vlan_id,
      subnet_id: firstSubnet?.id,
      default_gateway: firstVlan?.gateway,
    }));

  if (synthesizedEndpoints.length === 0) {
    return topology;
  }

  const endpointIds = new Set(topology.endpoints.map((endpoint) => endpoint.id));
  return {
    ...topology,
    endpoints: [...topology.endpoints, ...synthesizedEndpoints],
    vlans: topology.vlans.map((vlan, vlanIndex) => (
      vlanIndex === 0
        ? {
          ...vlan,
          endpoint_ids: [
            ...(vlan.endpoint_ids ?? []),
            ...synthesizedEndpoints
              .map((endpoint) => endpoint.id)
              .filter((endpointId) => !endpointIds.has(endpointId)),
          ],
        }
        : vlan
    )),
  };
}

const initialState: WorkflowState = {
  topologyDraft: defaultTopology,
  history: [],
  future: [],
  addressRequest: {
    base_network: "10.10.0.0/16",
    segments: [
      { name: "ADMIN", host_count: 40 },
      { name: "STUDENT", host_count: 200 },
      { name: "GUEST", host_count: 100 },
    ],
  },
  addressPlan: null,
  activeDeployment: null,
  deployments: [],
  savedTopologies: [
    {
      id: "three-vlan-office",
      name: defaultTopology.project.name,
      topology: defaultTopology,
      updated_at: new Date("2026-07-18T00:00:00.000Z").toISOString(),
    },
  ],
  activeTopologyId: "three-vlan-office",
  activeChange: null,
  changes: [],
  progressEvents: {},
  selectedWorkflowId: null,
};

function reducer(state: WorkflowState, action: Action): WorkflowState {
  switch (action.type) {
    case "SET_TOPOLOGY":
      return {
        ...state,
        history: [...state.history, state.topologyDraft],
        future: [],
        topologyDraft: action.topology,
      };
    case "UNDO": {
      const previous = state.history[state.history.length - 1];
      if (!previous) {
        return state;
      }
      return {
        ...state,
        topologyDraft: previous,
        history: state.history.slice(0, -1),
        future: [state.topologyDraft, ...state.future],
      };
    }
    case "REDO": {
      const next = state.future[0];
      if (!next) {
        return state;
      }
      return {
        ...state,
        topologyDraft: next,
        history: [...state.history, state.topologyDraft],
        future: state.future.slice(1),
      };
    }
    case "SET_ADDRESS_REQUEST":
      return { ...state, addressRequest: action.request };
    case "SET_ADDRESS_PLAN":
      return { ...state, addressPlan: action.plan };
    case "UPSERT_DEPLOYMENT": {
      const deployments = [
        action.deployment,
        ...state.deployments.filter((item) => item.id !== action.deployment.id),
      ];
      return {
        ...state,
        deployments,
        activeDeployment: action.deployment,
        selectedWorkflowId: action.deployment.id,
      };
    }
    case "SAVE_TOPOLOGY": {
      const savedTopologies = [
        action.record,
        ...state.savedTopologies.filter((item) => item.id !== action.record.id),
      ];
      return {
        ...state,
        savedTopologies,
        activeTopologyId: action.record.id,
      };
    }
    case "SET_ACTIVE_DEPLOYMENT":
      return {
        ...state,
        activeDeployment: action.deployment,
        selectedWorkflowId: action.deployment?.id ?? state.selectedWorkflowId,
      };
    case "UPSERT_CHANGE": {
      const changes = [
        action.change,
        ...state.changes.filter((item) => item.id !== action.change.id),
      ];
      return {
        ...state,
        changes,
        activeChange: action.change,
        selectedWorkflowId: action.change.id,
      };
    }
    case "SET_ACTIVE_CHANGE":
      return {
        ...state,
        activeChange: action.change,
        selectedWorkflowId: action.change?.id ?? state.selectedWorkflowId,
      };
    case "LOAD_SAVED_TOPOLOGY": {
      const selected = state.savedTopologies.find((item) => item.id === action.topologyId);
      if (!selected) {
        return state;
      }
      return {
        ...state,
        history: [...state.history, state.topologyDraft],
        future: [],
        topologyDraft: selected.topology,
        activeTopologyId: selected.id,
      };
    }
    case "DELETE_SAVED_TOPOLOGY": {
      const savedTopologies = state.savedTopologies.filter((item) => item.id !== action.topologyId);
      const nextActiveTopology = savedTopologies[0] ?? null;
      return {
        ...state,
        savedTopologies,
        activeTopologyId: state.activeTopologyId === action.topologyId ? nextActiveTopology?.id ?? null : state.activeTopologyId,
        topologyDraft: state.activeTopologyId === action.topologyId ? nextActiveTopology?.topology ?? defaultTopology : state.topologyDraft,
      };
    }
    case "APPEND_PROGRESS": {
      const existing = state.progressEvents[action.workflowId] ?? [];
      const duplicate = existing.find((item) => item.status === action.event.status && item.timestamp === action.event.timestamp);
      if (duplicate) {
        return state;
      }
      const nextEvents = [...existing, action.event].slice(-12);
      return {
        ...state,
        progressEvents: {
          ...state.progressEvents,
          [action.workflowId]: nextEvents,
        },
      };
    }
    case "SELECT_WORKFLOW":
      return { ...state, selectedWorkflowId: action.workflowId };
    case "RESET":
      return initialState;
    default:
      return state;
  }
}

function parseStoredState(raw: string | null): WorkflowState | null {
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as Partial<WorkflowState>;
    return {
      ...initialState,
      ...parsed,
      topologyDraft: normalizeTopology(parsed.topologyDraft ?? initialState.topologyDraft),
      history: (parsed.history ?? initialState.history).map(normalizeTopology),
      future: (parsed.future ?? initialState.future).map(normalizeTopology),
      addressRequest: parsed.addressRequest ?? initialState.addressRequest,
      addressPlan: parsed.addressPlan ?? initialState.addressPlan,
      activeDeployment: parsed.activeDeployment ?? initialState.activeDeployment,
      deployments: parsed.deployments ?? initialState.deployments,
      savedTopologies: (parsed.savedTopologies ?? initialState.savedTopologies).map((record) => ({
        ...record,
        topology: normalizeTopology(record.topology),
      })),
      activeTopologyId: parsed.activeTopologyId ?? initialState.activeTopologyId,
      activeChange: parsed.activeChange ?? initialState.activeChange,
      changes: parsed.changes ?? initialState.changes,
      progressEvents: parsed.progressEvents ?? initialState.progressEvents,
      selectedWorkflowId: parsed.selectedWorkflowId ?? initialState.selectedWorkflowId,
    };
  } catch {
    return null;
  }
}

const WorkflowContext = createContext<WorkflowStore | null>(null);

export function WorkflowStoreProvider(props: PropsWithChildren) {
  const storedState = typeof window === "undefined" ? null : parseStoredState(localStorage.getItem(STORAGE_KEY));
  const [state, dispatch] = useReducer(reducer, storedState ?? initialState);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }, [state]);

  const store = useMemo<WorkflowStore>(() => ({
    ...state,
    setTopologyDraft(topology) {
      dispatch({ type: "SET_TOPOLOGY", topology });
    },
    updateProjectName(name) {
      dispatch({
        type: "SET_TOPOLOGY",
        topology: {
          ...state.topologyDraft,
          project: {
            ...state.topologyDraft.project,
            name,
          },
        },
      });
    },
    updateDeviceHostname(deviceId, hostname) {
      dispatch({
        type: "SET_TOPOLOGY",
        topology: {
          ...state.topologyDraft,
          devices: state.topologyDraft.devices.map((device) => device.id === deviceId ? { ...device, hostname } : device),
          endpoints: state.topologyDraft.endpoints.map((endpoint) => endpoint.device_id === deviceId ? { ...endpoint, hostname } : endpoint),
        },
      });
    },
    addDevice(deviceType) {
      const nextIndex = state.topologyDraft.devices.length + 1;
      const idPrefix = deviceType === "router" ? "r" : deviceType === "switch" ? "sw" : "ep";
      const platform = deviceType === "router" ? "iosv" : deviceType === "switch" ? "iosvl2" : "vpcs";
      const interfaces = deviceType === "endpoint"
        ? [{ name: "Ethernet0", enabled: true }]
        : Array.from({ length: 4 }, (_, index) => ({
          name: `GigabitEthernet0/${index}`,
          enabled: true,
        }));
      const newDevice = {
        id: `${idPrefix}${nextIndex}`,
        hostname: `${deviceType.toUpperCase()}-${nextIndex}`,
        type: deviceType,
        platform,
        site_id: state.topologyDraft.sites[0]?.id,
        interfaces,
      };
      const firstVlan = state.topologyDraft.vlans[0];
      const firstSubnet = state.topologyDraft.subnets.find((subnet) => subnet.vlan_id === firstVlan?.vlan_id);
      const newEndpoint = deviceType === "endpoint"
        ? {
          id: `${newDevice.id}-endpoint`,
          device_id: newDevice.id,
          hostname: newDevice.hostname,
          ip_address: firstVlan ? `192.168.${firstVlan.vlan_id}.${10 + state.topologyDraft.endpoints.length}` : `192.168.1.${10 + state.topologyDraft.endpoints.length}`,
          vlan_id: firstVlan?.vlan_id,
          subnet_id: firstSubnet?.id,
          default_gateway: firstVlan?.gateway,
        }
        : null;
      dispatch({
        type: "SET_TOPOLOGY",
        topology: {
          ...state.topologyDraft,
          devices: [...state.topologyDraft.devices, newDevice],
          endpoints: newEndpoint
            ? [...state.topologyDraft.endpoints, newEndpoint]
            : state.topologyDraft.endpoints,
          vlans: newEndpoint && firstVlan
            ? state.topologyDraft.vlans.map((vlan) => (
              vlan.vlan_id === firstVlan.vlan_id
                ? {
                  ...vlan,
                  endpoint_ids: [...(vlan.endpoint_ids ?? []), newEndpoint.id],
                }
                : vlan
            ))
            : state.topologyDraft.vlans,
        },
      });
    },
    addLink(sourceDeviceId, sourceInterface, targetDeviceId, targetInterface) {
      if (!sourceDeviceId || !sourceInterface || !targetDeviceId || !targetInterface || sourceDeviceId === targetDeviceId) {
        return;
      }
      const exists = state.topologyDraft.links.some((link) =>
        link.source_device === sourceDeviceId
        && link.source_interface === sourceInterface
        && link.target_device === targetDeviceId
        && link.target_interface === targetInterface,
      );
      if (exists) {
        return;
      }
      dispatch({
        type: "SET_TOPOLOGY",
        topology: {
          ...state.topologyDraft,
          links: [
            ...state.topologyDraft.links,
            {
              source_device: sourceDeviceId,
              source_interface: sourceInterface,
              target_device: targetDeviceId,
              target_interface: targetInterface,
            },
          ],
        },
      });
    },
    addVlan() {
      const lastVlan = state.topologyDraft.vlans[state.topologyDraft.vlans.length - 1]?.vlan_id ?? 0;
      const vlanId = lastVlan + 10;
      dispatch({
        type: "SET_TOPOLOGY",
        topology: {
          ...state.topologyDraft,
          vlans: [
            ...state.topologyDraft.vlans,
            {
              vlan_id: vlanId,
              name: `VLAN${vlanId}`,
              subnet: `192.168.${vlanId}.0/24`,
              gateway: `192.168.${vlanId}.1`,
              endpoint_ids: [],
            },
          ],
        },
      });
    },
    undo() {
      dispatch({ type: "UNDO" });
    },
    redo() {
      dispatch({ type: "REDO" });
    },
    setAddressRequest(request) {
      dispatch({ type: "SET_ADDRESS_REQUEST", request });
    },
    setAddressPlan(plan) {
      dispatch({ type: "SET_ADDRESS_PLAN", plan });
    },
    setActiveDeployment(deployment) {
      dispatch({ type: "SET_ACTIVE_DEPLOYMENT", deployment });
    },
    upsertDeployment(deployment) {
      dispatch({ type: "UPSERT_DEPLOYMENT", deployment });
    },
    saveTopology(name) {
      const topologyName = (name ?? state.topologyDraft.project.name).trim() || "untitled-topology";
      const record: SavedTopologyRecord = {
        id: topologyName.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
        name: topologyName,
        topology: {
          ...state.topologyDraft,
          project: {
            ...state.topologyDraft.project,
            name: topologyName,
          },
        },
        updated_at: new Date().toISOString(),
      };
      dispatch({ type: "SAVE_TOPOLOGY", record });
    },
    loadSavedTopology(topologyId) {
      dispatch({ type: "LOAD_SAVED_TOPOLOGY", topologyId });
    },
    deleteSavedTopology(topologyId) {
      dispatch({ type: "DELETE_SAVED_TOPOLOGY", topologyId });
    },
    resetDraftToDefault() {
      dispatch({ type: "SET_TOPOLOGY", topology: defaultTopology });
    },
    setActiveChange(change) {
      dispatch({ type: "SET_ACTIVE_CHANGE", change });
    },
    upsertChange(change) {
      dispatch({ type: "UPSERT_CHANGE", change });
    },
    appendProgressEvent(workflowId, event) {
      dispatch({ type: "APPEND_PROGRESS", workflowId, event });
    },
    selectWorkflow(workflowId) {
      dispatch({ type: "SELECT_WORKFLOW", workflowId });
    },
    resetWorkflow() {
      dispatch({ type: "RESET" });
    },
  }), [state]);

  return (
    <WorkflowContext.Provider value={store}>
      {props.children}
    </WorkflowContext.Provider>
  );
}

export function useWorkflowStore() {
  const context = useContext(WorkflowContext);
  if (!context) {
    throw new Error("WorkflowStoreProvider is missing");
  }
  return context;
}
