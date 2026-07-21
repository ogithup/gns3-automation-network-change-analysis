import { useMemo } from "react";
import ReactFlow, {
  Background,
  Controls,
  Edge,
  MiniMap,
  Node,
} from "reactflow";
import "reactflow/dist/style.css";

import {
  ChangeRecordResponse,
  DeploymentRecordResponse,
  DeviceSpec,
  TopologySpec,
} from "../types/workflow";

type TopologyCanvasProps = {
  topology: TopologySpec;
  deployment?: DeploymentRecordResponse | null;
  change?: ChangeRecordResponse | null;
  mode?: "draft" | "current" | "impact";
};

type ImpactVisualState = {
  directDevices: Set<string>;
  endpointDevices: Set<string>;
  transitDevices: Set<string>;
  brokenEdges: Set<string>;
  affectedEdges: Set<string>;
};

function buildDevicePositions(devices: DeviceSpec[]) {
  const rows: Array<{ type: DeviceSpec["type"]; y: number }> = [
    { type: "router", y: 100 },
    { type: "switch", y: 300 },
    { type: "endpoint", y: 520 },
  ];
  const minimumX = 120;
  const baseSpacing = 260;
  const positions = new Map<string, { x: number; y: number }>();

  rows.forEach(({ type, y }) => {
    const rowDevices = devices
      .filter((device) => device.type === type)
      .sort((left, right) => left.hostname.localeCompare(right.hostname));

    if (rowDevices.length === 0) {
      return;
    }

    const rowWidth = Math.max((rowDevices.length - 1) * baseSpacing, 0);
    const startX = Math.max(minimumX, 420 - (rowWidth / 2));

    rowDevices.forEach((device, index) => {
      positions.set(device.id, {
        x: startX + (index * baseSpacing),
        y,
      });
    });
  });

  devices
    .filter((device) => !positions.has(device.id))
    .sort((left, right) => left.hostname.localeCompare(right.hostname))
    .forEach((device, index) => {
      positions.set(device.id, {
        x: minimumX + (index * baseSpacing),
        y: 300,
      });
    });

  return positions;
}

function buildEdgeId(sourceDevice: string, sourceInterface: string, targetDevice: string, index: number) {
  return `${sourceDevice}-${sourceInterface}-${targetDevice}-${index}`;
}

function buildImpactVisualState(topology: TopologySpec, change?: ChangeRecordResponse | null): ImpactVisualState {
  const visualState: ImpactVisualState = {
    directDevices: new Set<string>(),
    endpointDevices: new Set<string>(),
    transitDevices: new Set<string>(),
    brokenEdges: new Set<string>(),
    affectedEdges: new Set<string>(),
  };

  const simulation = change?.simulation;
  if (!simulation) {
    return visualState;
  }

  const endpointDeviceById = new Map(topology.endpoints.map((endpoint) => [endpoint.id, endpoint.device_id]));
  const deviceById = new Map(topology.devices.map((device) => [device.id, device]));

  const registerEndpoint = (endpointId: string) => {
    const deviceId = endpointDeviceById.get(endpointId);
    if (!deviceId) {
      return;
    }

    visualState.endpointDevices.add(deviceId);

    topology.links.forEach((link, index) => {
      const touchesEndpoint = link.source_device === deviceId || link.target_device === deviceId;
      if (!touchesEndpoint) {
        return;
      }

      visualState.affectedEdges.add(
        buildEdgeId(link.source_device, link.source_interface, link.target_device, index),
      );

      const neighborId = link.source_device === deviceId ? link.target_device : link.source_device;
      const neighbor = deviceById.get(neighborId);
      if (neighbor && neighbor.type !== "endpoint") {
        visualState.transitDevices.add(neighborId);
      }
    });
  };

  const registerBrokenInterface = (deviceId: string, interfaceName: string) => {
    visualState.directDevices.add(deviceId);

    topology.links.forEach((link, index) => {
      const matchesSource = link.source_device === deviceId && link.source_interface === interfaceName;
      const matchesTarget = link.target_device === deviceId && link.target_interface === interfaceName;
      if (!matchesSource && !matchesTarget) {
        return;
      }

      visualState.brokenEdges.add(
        buildEdgeId(link.source_device, link.source_interface, link.target_device, index),
      );

      const neighborId = link.source_device === deviceId ? link.target_device : link.source_device;
      const neighbor = deviceById.get(neighborId);
      if (neighbor && neighbor.type !== "endpoint") {
        visualState.transitDevices.add(neighborId);
      }
    });
  };

  [...simulation.direct_impacts, ...simulation.indirect_impacts].forEach((impact) => {
    if (impact.startsWith("endpoint:")) {
      registerEndpoint(impact.slice("endpoint:".length));
      return;
    }

    if (impact.startsWith("interface:")) {
      const [, deviceId, interfaceName] = impact.split(":");
      if (deviceId && interfaceName) {
        registerBrokenInterface(deviceId, interfaceName);
      }
    }
  });

  simulation.after_results
    .filter((result) => result.predicted_reachable === false)
    .forEach((result) => {
      (result.path ?? []).forEach((step) => {
        if (step.startsWith("endpoint:")) {
          registerEndpoint(step.slice("endpoint:".length));
          return;
        }

        if (step.startsWith("trunk:")) {
          const trunkInterface = step.slice("trunk:".length);
          topology.links.forEach((link, index) => {
            if (link.source_interface !== trunkInterface && link.target_interface !== trunkInterface) {
              return;
            }

            visualState.brokenEdges.add(
              buildEdgeId(link.source_device, link.source_interface, link.target_device, index),
            );

            [link.source_device, link.target_device].forEach((deviceId) => {
              const device = deviceById.get(deviceId);
              if (device && device.type !== "endpoint") {
                visualState.transitDevices.add(deviceId);
              }
            });
          });
        }
      });
    });

  simulation.impact.lost_reachability_paths.forEach((path) => {
    path.forEach((step) => {
      if (step.startsWith("endpoint:")) {
        registerEndpoint(step.slice("endpoint:".length));
      } else {
        registerEndpoint(step);
      }
    });
  });

  topology.links.forEach((link, index) => {
    const edgeId = buildEdgeId(link.source_device, link.source_interface, link.target_device, index);
    if (visualState.brokenEdges.has(edgeId)) {
      return;
    }

    const sourceAffected = visualState.endpointDevices.has(link.source_device) || visualState.transitDevices.has(link.source_device);
    const targetAffected = visualState.endpointDevices.has(link.target_device) || visualState.transitDevices.has(link.target_device);
    if (sourceAffected && targetAffected) {
      visualState.affectedEdges.add(edgeId);
    }
  });

  return visualState;
}

function toneForDevice(
  device: DeviceSpec,
  visualState: ImpactVisualState,
  deployment?: DeploymentRecordResponse | null,
  mode: "draft" | "current" | "impact" = "draft",
) {
  if (mode === "impact") {
    if (visualState.endpointDevices.has(device.id)) {
      return "device-node--impact-endpoint";
    }
    if (visualState.directDevices.has(device.id)) {
      return "device-node--direct";
    }
    if (visualState.transitDevices.has(device.id)) {
      return "device-node--impact-transit";
    }
  }

  const discovered = deployment?.discovered_state?.device_snapshots.find((item) => item.device_id === device.id);
  if (mode !== "draft" && discovered) {
    const hasDownInterface = discovered.discovered_state.interfaces.some((item) => item.status !== "up");
    return hasDownInterface ? "device-node--unreachable" : "device-node--current";
  }

  return mode === "draft" ? "device-node--draft" : "device-node--proposed";
}

function edgeTone(
  edgeId: string,
  sourceDeviceId: string,
  targetDeviceId: string,
  visualState: ImpactVisualState,
  deployment?: DeploymentRecordResponse | null,
  mode: "draft" | "current" | "impact" = "draft",
) {
  if (mode === "draft") {
    return "topology-edge--draft";
  }

  if (mode === "impact") {
    if (visualState.brokenEdges.has(edgeId)) {
      return "topology-edge--impact-broken";
    }
    if (visualState.affectedEdges.has(edgeId)) {
      return "topology-edge--impact-path";
    }
    return "topology-edge--impact-normal";
  }

  const source = deployment?.discovered_state?.device_snapshots.find((item) => item.device_id === sourceDeviceId);
  const target = deployment?.discovered_state?.device_snapshots.find((item) => item.device_id === targetDeviceId);
  if (!source || !target) {
    return "topology-edge--draft";
  }

  const sourceUp = source.discovered_state.interfaces.some((item) => item.status === "up");
  const targetUp = target.discovered_state.interfaces.some((item) => item.status === "up");
  return sourceUp && targetUp ? "topology-edge--up" : "topology-edge--down";
}

export function TopologyCanvas(props: TopologyCanvasProps) {
  const impactVisualState = useMemo(
    () => buildImpactVisualState(props.topology, props.change),
    [props.change, props.topology],
  );

  const devicePositions = useMemo(
    () => buildDevicePositions(props.topology.devices),
    [props.topology.devices],
  );

  const nodes = useMemo<Node[]>(
    () => props.topology.devices.map((device) => ({
      id: device.id,
      position: devicePositions.get(device.id) ?? { x: 120, y: 300 },
      data: {
        label: (
          <div className="device-node__content">
            <strong>{device.hostname}</strong>
            <span>{device.platform}</span>
            <small>{device.interfaces.length} interfaces</small>
          </div>
        ),
      },
      className: `device-node ${toneForDevice(device, impactVisualState, props.deployment, props.mode)}`,
    })),
    [devicePositions, impactVisualState, props.deployment, props.mode, props.topology.devices],
  );

  const edges = useMemo<Edge[]>(
    () => props.topology.links.map((link, index) => {
      const edgeId = buildEdgeId(link.source_device, link.source_interface, link.target_device, index);
      const isImpactEdge =
        props.mode === "impact"
        && (impactVisualState.brokenEdges.has(edgeId) || impactVisualState.affectedEdges.has(edgeId));

      return {
        id: edgeId,
        source: link.source_device,
        target: link.target_device,
        label: props.mode === "impact"
          ? `${link.source_interface} / ${link.target_interface}`
          : `${link.source_interface} -> ${link.target_interface}`,
        className: edgeTone(
          edgeId,
          link.source_device,
          link.target_device,
          impactVisualState,
          props.deployment,
          props.mode,
        ),
        style: {
          strokeWidth: 2.4,
          stroke: props.mode === "current" ? "#3aa35c" : "#7a8ea4",
        },
        labelStyle: {
          fill: "#435a70",
          fontSize: 11,
          fontWeight: 600,
        },
        animated: props.mode === "current" || isImpactEdge,
      };
    }),
    [impactVisualState, props.deployment, props.mode, props.topology.links],
  );

  return (
    <div className="topology-canvas">
      <ReactFlow fitView nodes={nodes} edges={edges}>
        <MiniMap />
        <Controls />
        <Background gap={18} size={1} />
      </ReactFlow>
    </div>
  );
}
