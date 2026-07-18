import { useMemo } from "react";
import ReactFlow, {
  Background,
  Controls,
  Edge,
  MarkerType,
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

function positionForDevice(device: DeviceSpec, index: number) {
  const typeOrder = {
    router: 120,
    switch: 320,
    endpoint: 540,
  };
  const x = 80 + (index % 3) * 260;
  const y = typeOrder[device.type] ?? 320;
  return { x, y };
}

function toneForDevice(
  deviceId: string,
  deployment?: DeploymentRecordResponse | null,
  change?: ChangeRecordResponse | null,
  mode: "draft" | "current" | "impact" = "draft",
) {
  if (mode === "impact" && change?.simulation) {
    if (change.simulation.direct_impacts.some((item) => item.includes(deviceId))) {
      return "device-node--direct";
    }
    if (change.simulation.indirect_impacts.some((item) => item.includes(deviceId))) {
      return "device-node--indirect";
    }
  }

  const discovered = deployment?.discovered_state?.device_snapshots.find((item) => item.device_id === deviceId);
  if (mode !== "draft" && discovered) {
    const hasDownInterface = discovered.discovered_state.interfaces.some((item) => item.status !== "up");
    return hasDownInterface ? "device-node--unreachable" : "device-node--current";
  }

  return mode === "draft" ? "device-node--draft" : "device-node--proposed";
}

function edgeTone(
  sourceDeviceId: string,
  targetDeviceId: string,
  deployment?: DeploymentRecordResponse | null,
  mode: "draft" | "current" | "impact" = "draft",
) {
  if (mode === "draft") {
    return "topology-edge--draft";
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
  const nodes = useMemo<Node[]>(() => props.topology.devices.map((device, index) => ({
    id: device.id,
    position: positionForDevice(device, index),
    data: {
      label: (
        <div className="device-node__content">
          <strong>{device.hostname}</strong>
          <span>{device.platform}</span>
          <small>{device.interfaces.length} interfaces</small>
        </div>
      ),
    },
    className: `device-node ${toneForDevice(device.id, props.deployment, props.change, props.mode)}`,
  })), [props.change, props.deployment, props.mode, props.topology.devices]);

  const edges = useMemo<Edge[]>(() => props.topology.links.map((link, index) => ({
    id: `${link.source_device}-${link.source_interface}-${link.target_device}-${index}`,
    source: link.source_device,
    target: link.target_device,
    label: `${link.source_interface} -> ${link.target_interface}`,
    className: edgeTone(link.source_device, link.target_device, props.deployment, props.mode),
    style: {
      strokeWidth: 2.4,
      stroke: props.mode === "current" ? "#3aa35c" : "#7a8ea4",
    },
    labelStyle: {
      fill: "#435a70",
      fontSize: 11,
      fontWeight: 600,
    },
    markerEnd: {
      type: MarkerType.ArrowClosed,
      color: props.mode === "current" ? "#3aa35c" : "#7a8ea4",
    },
    animated: props.mode === "impact" || props.mode === "current",
  })), [props.deployment, props.mode, props.topology.links]);

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
