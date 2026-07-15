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
  activeChange: ChangeRecordResponse | null;
  changes: ChangeRecordResponse[];
  progressEvents: Record<string, WorkflowProgressEvent[]>;
  selectedWorkflowId: string | null;
};

type WorkflowStore = WorkflowState & {
  setTopologyDraft: (topology: TopologySpec) => void;
  updateProjectName: (name: string) => void;
  addDevice: (deviceType: DeviceType) => void;
  addVlan: () => void;
  undo: () => void;
  redo: () => void;
  setAddressRequest: (request: AddressingRequest) => void;
  setAddressPlan: (plan: AddressingPlan | null) => void;
  setActiveDeployment: (deployment: DeploymentRecordResponse | null) => void;
  upsertDeployment: (deployment: DeploymentRecordResponse) => void;
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
  | { type: "UPSERT_CHANGE"; change: ChangeRecordResponse }
  | { type: "SET_ACTIVE_CHANGE"; change: ChangeRecordResponse | null }
  | { type: "APPEND_PROGRESS"; workflowId: string; event: WorkflowProgressEvent }
  | { type: "SELECT_WORKFLOW"; workflowId: string | null }
  | { type: "RESET" };

const STORAGE_KEY = "nettwin-ai-sprint15";

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
    case "APPEND_PROGRESS": {
      const existing = state.progressEvents[action.workflowId] ?? [];
      return {
        ...state,
        progressEvents: {
          ...state.progressEvents,
          [action.workflowId]: [...existing, action.event],
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
    return JSON.parse(raw) as WorkflowState;
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
    addDevice(deviceType) {
      const nextIndex = state.topologyDraft.devices.length + 1;
      const idPrefix = deviceType === "router" ? "r" : deviceType === "switch" ? "sw" : "ep";
      const platform = deviceType === "router" ? "iosv" : deviceType === "switch" ? "iosvl2" : "vpcs";
      const interfaceName = deviceType === "endpoint" ? "Ethernet0" : "GigabitEthernet0/0";
      const newDevice = {
        id: `${idPrefix}${nextIndex}`,
        hostname: `${deviceType.toUpperCase()}-${nextIndex}`,
        type: deviceType,
        platform,
        site_id: state.topologyDraft.sites[0]?.id,
        interfaces: [{ name: interfaceName, enabled: true }],
      };
      dispatch({
        type: "SET_TOPOLOGY",
        topology: {
          ...state.topologyDraft,
          devices: [...state.topologyDraft.devices, newDevice],
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
