import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";

import { workflowClient, fetchHealth } from "../api/client";
import { useWorkflowStore } from "../app/workflowStore";
import { EmptyState, JsonPanel, MetricTile, SectionCard, StatusPill } from "../components/Cards";
import { TopologyCanvas } from "../components/TopologyCanvas";
import { useWorkflowProgress } from "../hooks/useWorkflowProgress";
import {
  AddressingPlan,
  AddressingRequest,
  ChangeCommandPayload,
  DeterministicExplanation,
  GeneratedReport,
  InterpretedTopologyPlan,
  RootCauseAnalysisResult,
  SavedTopologyRecord,
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

function recommendedBaseNetwork(topology: TopologySpec) {
  const preferredSubnet =
    topology.vlans.find((vlan) => vlan.subnet)?.subnet
    ?? topology.subnets.find((subnet) => !subnet.network.endsWith("/30") && !subnet.network.endsWith("/31"))?.network
    ?? topology.subnets[0]?.network;

  if (!preferredSubnet) {
    return "10.10.0.0/16";
  }

  if (preferredSubnet.startsWith("192.168.")) {
    return "192.168.0.0/16";
  }
  if (preferredSubnet.startsWith("172.16.")) {
    return "172.16.0.0/16";
  }
  if (preferredSubnet.startsWith("10.")) {
    return "10.0.0.0/8";
  }
  return preferredSubnet;
}

function addressRequestFromTopology(topology: TopologySpec): AddressingRequest {
  const baseNetwork = recommendedBaseNetwork(topology);

  const segments = topology.vlans.length > 0
    ? topology.vlans.map((vlan) => ({
      name: vlan.name,
      host_count: Math.max(
        topology.endpoints.filter((endpoint) => endpoint.vlan_id === vlan.vlan_id).length + 10,
        10,
      ),
      fixed_subnet: vlan.subnet,
    }))
    : topology.subnets
      .filter((subnet) => !subnet.network.endsWith("/30") && !subnet.network.endsWith("/31"))
      .map((subnet) => ({
      name: subnet.name.replace(/ subnet$/i, ""),
      host_count: Math.max(
        topology.endpoints.filter((endpoint) => endpoint.subnet_id === subnet.id).length + 10,
        10,
      ),
      fixed_subnet: subnet.network,
    }));

  return {
    base_network: baseNetwork,
    segments,
    reserved_networks: topology.subnets
      .filter((subnet) => subnet.network.endsWith("/30") || subnet.network.endsWith("/31"))
      .map((subnet) => subnet.network),
  };
}

function addressPlanFromTopology(topology: TopologySpec, request: AddressingRequest): AddressingPlan {
  const allocations = request.segments.map((segment, index) => {
    const linkedVlan = topology.vlans[index] ?? topology.vlans.find((vlan) => vlan.name === segment.name);
    const linkedSubnet = linkedVlan
      ? topology.subnets.find((subnet) => subnet.vlan_id === linkedVlan.vlan_id)
      : topology.subnets.find((subnet) => subnet.name.replace(/ subnet$/i, "") === segment.name) ?? topology.subnets[index];
    const linkedEndpoints = linkedVlan
      ? topology.endpoints.filter((endpoint) => endpoint.vlan_id === linkedVlan.vlan_id)
      : linkedSubnet
        ? topology.endpoints.filter((endpoint) => endpoint.subnet_id === linkedSubnet.id)
        : [];
    return {
      name: segment.name,
      network: linkedVlan?.subnet ?? linkedSubnet?.network ?? segment.fixed_subnet ?? "",
      gateway: linkedVlan?.gateway ?? linkedSubnet?.gateway ?? "",
      usable_host_count: segment.host_count,
      allocated_addresses: Object.fromEntries(linkedEndpoints.map((endpoint) => [endpoint.hostname, endpoint.ip_address])),
    };
  });

  return {
    base_network: request.base_network,
    reserved_networks: request.reserved_networks ?? [],
    report: "Topology-derived IP plan suggestion generated from the active topology.",
    allocations,
  };
}

function validationLabel(topology: TopologySpec, index: number) {
  const requirement = topology.connectivity_requirements[index];
  if (!requirement) {
    return `Validation ${index + 1}`;
  }
  const sourceEndpoint = topology.endpoints.find((endpoint) => endpoint.id === requirement.source_endpoint_id);
  const targetEndpoint = topology.endpoints.find((endpoint) => endpoint.id === requirement.target_endpoint_id);
  const sourceSegment = topology.vlans.find((vlan) => vlan.vlan_id === sourceEndpoint?.vlan_id)?.name;
  const targetSegment = topology.vlans.find((vlan) => vlan.vlan_id === targetEndpoint?.vlan_id)?.name;
  const sourceLabel = sourceEndpoint
    ? `${sourceEndpoint.hostname}${sourceSegment ? ` [${sourceSegment}]` : ""}`
    : requirement.source_endpoint_id;
  const targetLabel = targetEndpoint
    ? `${targetEndpoint.hostname}${targetSegment ? ` [${targetSegment}]` : ""}`
    : requirement.target_endpoint_id;
  return `${sourceLabel} -> ${targetLabel}`;
}

function formatTimestamp(value: string) {
  return new Date(value).toLocaleString("tr-TR");
}

function topologyEquals(left: TopologySpec | null | undefined, right: TopologySpec | null | undefined) {
  if (!left || !right) {
    return false;
  }
  return JSON.stringify(left) === JSON.stringify(right);
}

function networkBaseIp(cidr: string) {
  return cidr.split("/")[0] ?? "192.168.1.0";
}

function addIpv4Offset(ipAddress: string, offset: number) {
  const octets = ipAddress.split(".").map((item) => Number(item));
  if (octets.length !== 4 || octets.some((item) => Number.isNaN(item))) {
    return ipAddress;
  }
  let value = (((octets[0] * 256) + octets[1]) * 256 + octets[2]) * 256 + octets[3];
  value += offset;
  return [
    (value >>> 24) & 255,
    (value >>> 16) & 255,
    (value >>> 8) & 255,
    value & 255,
  ].join(".");
}

type BilingualInsight = {
  tone: "neutral" | "success" | "warning" | "danger" | "info";
  titleTr: string;
  titleEn: string;
  detailsTr: string[];
  detailsEn: string[];
};

function ipv4ToInt(ipAddress: string) {
  const octets = ipAddress.split(".").map((item) => Number(item));
  if (octets.length !== 4 || octets.some((item) => Number.isNaN(item) || item < 0 || item > 255)) {
    return null;
  }
  return ((((octets[0] * 256) + octets[1]) * 256) + octets[2]) * 256 + octets[3];
}

function parseCidr(value: string) {
  const [ipAddress, prefixText] = value.split("/");
  const prefix = Number(prefixText);
  const ipValue = ipv4ToInt(ipAddress ?? "");
  if (ipValue === null || !Number.isInteger(prefix) || prefix < 0 || prefix > 32) {
    return null;
  }
  const size = 2 ** (32 - prefix);
  const networkStart = Math.floor(ipValue / size) * size;
  const usableHosts = prefix >= 31 ? 0 : Math.max(size - 2, 0);
  return {
    ipAddress,
    prefix,
    size,
    networkStart,
    usableHosts,
    aligned: ipValue === networkStart,
  };
}

function requiredPrefixForHosts(hostCount: number) {
  if (hostCount <= 0) {
    return null;
  }
  for (let prefix = 30; prefix >= 1; prefix -= 1) {
    const usableHosts = prefix >= 31 ? 0 : Math.max((2 ** (32 - prefix)) - 2, 0);
    if (usableHosts >= hostCount) {
      return prefix;
    }
  }
  return null;
}

function isPrivateIpv4(value: string) {
  const parsed = parseCidr(`${value}/32`);
  if (!parsed) {
    return false;
  }
  const firstOctet = Number(value.split(".")[0] ?? "0");
  const secondOctet = Number(value.split(".")[1] ?? "0");
  return firstOctet === 10
    || (firstOctet === 172 && secondOctet >= 16 && secondOctet <= 31)
    || (firstOctet === 192 && secondOctet === 168);
}

function buildAddressingInsights(topology: TopologySpec, request: AddressingRequest, plan: AddressingPlan | null) {
  const insights: BilingualInsight[] = [];
  const parsedBase = parseCidr(request.base_network);
  const totalAllocationFootprint = request.segments.reduce((total, segment) => {
    const prefix = requiredPrefixForHosts(segment.host_count);
    if (prefix === null) {
      return total;
    }
    return total + (2 ** (32 - prefix));
  }, 0);

  if (!parsedBase) {
    insights.push({
      tone: "danger",
      titleTr: "Base network geçersiz",
      titleEn: "Base network is invalid",
      detailsTr: [
        "CIDR biçimi beklenir. Örnek: 10.10.0.0/16",
        "IP adresi ve prefix birlikte girilmelidir; prefix 0 ile 32 arasında olmalıdır.",
      ],
      detailsEn: [
        "A CIDR format is required. Example: 10.10.0.0/16",
        "The value must include both an IPv4 address and a prefix between 0 and 32.",
      ],
    });
  } else {
    const baseIpPrivate = isPrivateIpv4(parsedBase.ipAddress);
    const networkCapacity = parsedBase.size;
    if (!parsedBase.aligned) {
      insights.push({
        tone: "warning",
        titleTr: "Base network ağ sınırında değil",
        titleEn: "Base network is not aligned to a network boundary",
        detailsTr: [
          `${request.base_network} bir subnet başlangıcı değil. Örneğin /24 için .0 ile başlayan ağ kullanılmalıdır.`,
          "Bu durumda planner beklenmedik sonuç üretebilir veya backend isteği reddedebilir.",
        ],
        detailsEn: [
          `${request.base_network} is not the start of a subnet. For example, a /24 should start at .0.`,
          "In that case the planner may produce unexpected output or the backend may reject the request.",
        ],
      });
    }
    if (!baseIpPrivate) {
      insights.push({
        tone: "warning",
        titleTr: "Özel IPv4 aralığı önerilir",
        titleEn: "A private IPv4 range is recommended",
        detailsTr: [
          "Lab topolojilerinde 10.0.0.0/8, 172.16.0.0/12 veya 192.168.0.0/16 kullanmak daha güvenlidir.",
          "Public aralıklar gerçek ağlarla çakışma veya yorum karmaşası yaratabilir.",
        ],
        detailsEn: [
          "For lab topologies, 10.0.0.0/8, 172.16.0.0/12, or 192.168.0.0/16 is safer.",
          "Public ranges can create conflicts or confusing results in a simulated environment.",
        ],
      });
    }
    if (totalAllocationFootprint > networkCapacity) {
      insights.push({
        tone: "danger",
        titleTr: "Base network kapasitesi yetmiyor",
        titleEn: "Base network capacity is insufficient",
        detailsTr: [
          `İstenen segmentler için yaklaşık ${totalAllocationFootprint} adreslik alan gerekiyor, fakat ${request.base_network} yalnızca ${networkCapacity} adres kapsıyor.`,
          "Daha geniş bir base network seçmeli veya host sayılarını düşürmelisin.",
        ],
        detailsEn: [
          `The requested segments need roughly ${totalAllocationFootprint} addresses, but ${request.base_network} covers only ${networkCapacity}.`,
          "Choose a larger base network or reduce the host counts.",
        ],
      });
    } else {
      insights.push({
        tone: "success",
        titleTr: "Base network kapasitesi uygun görünüyor",
        titleEn: "Base network capacity looks acceptable",
        detailsTr: [
          `${request.base_network} toplam kapasitesi, şu anki segment isteklerini karşılayabilecek seviyede.`,
        ],
        detailsEn: [
          `${request.base_network} appears large enough for the current segment requests.`,
        ],
      });
    }
  }

  request.segments.forEach((segment, index) => {
    const linkedVlan = topology.vlans[index];
    const endpointCount = linkedVlan ? topology.endpoints.filter((endpoint) => endpoint.vlan_id === linkedVlan.vlan_id).length : 0;
    const requiredPrefix = requiredPrefixForHosts(segment.host_count);
    if (segment.host_count <= 0 || Number.isNaN(segment.host_count)) {
      insights.push({
        tone: "danger",
        titleTr: `${segment.name} host değeri geçersiz`,
        titleEn: `${segment.name} host value is invalid`,
        detailsTr: [
          "Host sayısı 1 veya daha büyük olmalıdır.",
          "0 veya negatif değerler ağ planlama açısından uygulanamaz.",
        ],
        detailsEn: [
          "The host count must be at least 1.",
          "Zero or negative values cannot be allocated in a valid network plan.",
        ],
      });
      return;
    }
    if (!requiredPrefix) {
      insights.push({
        tone: "danger",
        titleTr: `${segment.name} çok büyük`,
        titleEn: `${segment.name} is too large`,
        detailsTr: [
          `${segment.host_count} host tek bir standart IPv4 segmentinde karşılanamıyor.`,
        ],
        detailsEn: [
          `${segment.host_count} hosts cannot be satisfied by a single standard IPv4 segment.`,
        ],
      });
      return;
    }

    const detailsTr = [`Bu istek için en küçük uygun subnet yaklaşık /${requiredPrefix} olur.`];
    const detailsEn = [`The smallest practical subnet for this request is about /${requiredPrefix}.`];
    if (endpointCount > segment.host_count) {
      insights.push({
        tone: "danger",
        titleTr: `${segment.name} için host sayısı yetersiz`,
        titleEn: `Host count is too small for ${segment.name}`,
        detailsTr: [
          `Topology içinde bu segmente bağlı en az ${endpointCount} endpoint var, fakat sen ${segment.host_count} host girdin.`,
          "Gateway, switch management veya gelecekteki büyüme için de adres bırakman gerekir.",
          ...detailsTr,
        ],
        detailsEn: [
          `The topology already has at least ${endpointCount} endpoints tied to this segment, but you entered only ${segment.host_count} hosts.`,
          "You should also reserve addresses for the gateway, switch management, or future growth.",
          ...detailsEn,
        ],
      });
      return;
    }
    if (!linkedVlan) {
      insights.push({
        tone: "warning",
        titleTr: `${segment.name} için topology eşleşmesi yok`,
        titleEn: `No topology match found for ${segment.name}`,
        detailsTr: [
          "Bu segment şu an bir VLAN ile eşleşmiyor. IP plan üretilse bile config tarafına doğrudan yansımayabilir.",
        ],
        detailsEn: [
          "This segment does not currently match a VLAN. The IP plan may generate, but it may not map directly into configuration output.",
        ],
      });
      return;
    }
    if (plan && !plan.allocations.find((allocation) => allocation.name.toUpperCase() === segment.name.toUpperCase())) {
      insights.push({
        tone: "warning",
        titleTr: `${segment.name} çıktıda görünmedi`,
        titleEn: `${segment.name} did not appear in the output`,
        detailsTr: [
          "Planner bu segment için allocation döndürmedi. Bu genelde kapasite, isim eşleşmesi veya validation kaynaklıdır.",
        ],
        detailsEn: [
          "The planner did not return an allocation for this segment. That usually points to capacity, name matching, or validation issues.",
        ],
      });
      return;
    }
    insights.push({
      tone: "info",
      titleTr: `${segment.name} segment yorumu`,
      titleEn: `${segment.name} segment interpretation`,
      detailsTr: [
        `${segment.host_count} host isteği topology açısından uygulanabilir görünüyor.`,
        `${endpointCount} endpoint şu an bu segment ile ilişkili.`,
        ...detailsTr,
      ],
      detailsEn: [
        `The ${segment.host_count}-host request looks acceptable for the current topology.`,
        `${endpointCount} endpoints are currently associated with this segment.`,
        ...detailsEn,
      ],
    });
  });

  return insights;
}

function interpretTopologySummary(plan: InterpretedTopologyPlan) {
  if (plan.blocked) {
    return {
      title: "Interpretation blocked",
      lines: [
        "The prompt is ambiguous or contains safety issues.",
        "Review the clarification questions and warnings before using the result.",
      ],
    };
  }
  const topology = plan.topology;
  if (!topology) {
    return {
      title: "Preview only",
      lines: [
        "The interpreter produced a preview but not a full topology object.",
        "Check clarifications and warnings before continuing.",
      ],
    };
  }
  return {
    title: "Interpreted result",
    lines: [
      `Project: ${topology.project.name}`,
      `${topology.devices.length} devices, ${topology.links.length} links, ${topology.vlans.length} VLANs, ${topology.endpoints.length} endpoints`,
      plan.warnings.length > 0 ? `${plan.warnings.length} warnings still need review.` : "No warnings were returned.",
    ],
  };
}

function interfaceExplanation(deviceType: string, interfaceName: string) {
  const lower = interfaceName.toLowerCase();
  if (deviceType === "router" && lower.startsWith("gigabitethernet")) {
    return {
      tr: `${interfaceName} router fiziksel portudur. Router-to-switch uplink için kullanılır; VLAN taşıyacaksan genelde trunk tarafında alt arayüzlerle birlikte çalışır.`,
      en: `${interfaceName} is a physical router port. Use it for router-to-switch uplinks; if VLANs traverse the link, it usually works with router subinterfaces.`,
    };
  }
  if (deviceType === "switch" && lower.startsWith("gigabitethernet")) {
    return {
      tr: `${interfaceName} switch portudur. Endpoint bağlıysa access port, router veya başka switch bağlıysa çoğu durumda trunk/uplink mantığıyla düşünülmelidir.`,
      en: `${interfaceName} is a switch port. Use it as an access port for endpoints; if it connects to a router or another switch, it usually behaves as a trunk/uplink.`,
    };
  }
  if (deviceType === "endpoint") {
    return {
      tr: `${interfaceName} endpoint NIC arayüzüdür. Genelde yalnızca switch access portuna bağlanmalıdır; endpoint-to-endpoint doğrudan bağlantı çoğu senaryoda hedef değildir.`,
      en: `${interfaceName} is an endpoint NIC. It should normally connect to a switch access port; direct endpoint-to-endpoint links are unusual for this workflow.`,
    };
  }
  return {
    tr: `${interfaceName} seçili cihaz arayüzüdür; bağlantı türünü cihaz rolüne göre belirlemelisin.`,
    en: `${interfaceName} belongs to the selected device; choose the link style according to the device role.`,
  };
}

function buildConfigurationTerminalFlow(platform: string, content: string) {
  const lines = content
    .split("\n")
    .map((line) => line.trimEnd())
    .filter((line) => line.trim().length > 0);

  if (platform === "vpcs") {
    return [
      "connect console",
      ...lines,
    ];
  }

  const commandLines = lines.filter((line) => line.trim() !== "!" && line.trim() !== "end");
  return [
    "enable",
    "configure terminal",
    ...commandLines,
    "end",
    "write memory",
  ];
}

function mutationErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return "Unexpected workflow error.";
}

function endpointFriendlyName(topology: TopologySpec, endpointId: string | undefined, fallback: string) {
  const endpoint = topology.endpoints.find((item) => item.id === endpointId);
  if (!endpoint) {
    return fallback;
  }
  const segmentName = topology.vlans.find((vlan) => vlan.vlan_id === endpoint.vlan_id)?.name;
  return segmentName ? `${endpoint.hostname} (${segmentName})` : endpoint.hostname;
}

type ValidationFixGuide = {
  problemTypeTr: string;
  problemTypeEn: string;
  likelyFixTr: string;
  likelyFixEn: string;
  suggestedValuesTr: string[];
  suggestedValuesEn: string[];
  pageLabelTr: string;
  pageLabelEn: string;
  pagePath: string;
  stepsTr: string[];
  stepsEn: string[];
};

function buildValidationFixGuide(topology: TopologySpec, index: number, failureStage: string | null | undefined): ValidationFixGuide {
  const requirement = topology.connectivity_requirements[index];
  const sourceEndpointId = requirement?.source_endpoint_id ?? "source endpoint";
  const targetEndpointId = requirement?.target_endpoint_id ?? "target endpoint";
  const sourceEndpoint = topology.endpoints.find((endpoint) => endpoint.id === requirement?.source_endpoint_id);
  const targetEndpoint = topology.endpoints.find((endpoint) => endpoint.id === requirement?.target_endpoint_id);
  const sourceVlan = topology.vlans.find((vlan) => vlan.vlan_id === sourceEndpoint?.vlan_id);
  const sourceSubnet = topology.subnets.find((subnet) => subnet.id === sourceEndpoint?.subnet_id || subnet.vlan_id === sourceEndpoint?.vlan_id);
  const targetVlan = topology.vlans.find((vlan) => vlan.vlan_id === targetEndpoint?.vlan_id);
  const targetSubnet = topology.subnets.find((subnet) => subnet.id === targetEndpoint?.subnet_id || subnet.vlan_id === targetEndpoint?.vlan_id);
  const recommendedSourceSubnet = sourceVlan?.subnet ?? sourceSubnet?.network ?? "192.168.10.0/24";
  const recommendedSourceGateway = sourceVlan?.gateway ?? sourceSubnet?.gateway ?? "192.168.10.1";
  const recommendedSourceIp = sourceEndpoint?.ip_address ?? addIpv4Offset(networkBaseIp(recommendedSourceSubnet), 10);
  const recommendedTargetSubnet = targetVlan?.subnet ?? targetSubnet?.network ?? "192.168.20.0/24";
  const recommendedTargetGateway = targetVlan?.gateway ?? targetSubnet?.gateway ?? "192.168.20.1";
  const recommendedTargetIp = targetEndpoint?.ip_address ?? addIpv4Offset(networkBaseIp(recommendedTargetSubnet), 10);
  const sourceFriendlyName = endpointFriendlyName(topology, requirement?.source_endpoint_id, sourceEndpointId);
  const targetFriendlyName = endpointFriendlyName(topology, requirement?.target_endpoint_id, targetEndpointId);
  const sourceSegmentName = sourceVlan?.name ?? "Segment not assigned";
  const targetSegmentName = targetVlan?.name ?? "Segment not assigned";

  switch (failureStage) {
    case "source_addressing":
      return {
        problemTypeTr: "Kaynak adresleme eksik veya hatali",
        problemTypeEn: "Source addressing is missing or invalid",
        likelyFixTr: `${sourceFriendlyName} icin segment, subnet, IP ve gateway alanlarini topology mantigina gore doldur.`,
        likelyFixEn: `Fill the segment, subnet, IP, and gateway fields for ${sourceFriendlyName} so they match the topology design.`,
        suggestedValuesTr: [
          `Endpoint cihazi: ${sourceFriendlyName}`,
          `Segment/VLAN: ${sourceSegmentName}`,
          `Subnet alani: ${recommendedSourceSubnet}`,
          `Gateway alani: ${recommendedSourceGateway}`,
          `${sourceEndpoint?.hostname ?? sourceEndpointId} IP alani: ${recommendedSourceIp}`,
          `${sourceEndpoint?.hostname ?? sourceEndpointId} Gateway alani: ${recommendedSourceGateway}`,
        ],
        suggestedValuesEn: [
          `Endpoint device: ${sourceFriendlyName}`,
          `Segment/VLAN: ${sourceSegmentName}`,
          `Subnet field: ${recommendedSourceSubnet}`,
          `Gateway field: ${recommendedSourceGateway}`,
          `${sourceEndpoint?.hostname ?? sourceEndpointId} IP field: ${recommendedSourceIp}`,
          `${sourceEndpoint?.hostname ?? sourceEndpointId} gateway field: ${recommendedSourceGateway}`,
        ],
        pageLabelTr: "IP Address Plan",
        pageLabelEn: "IP Address Plan",
        pagePath: "/addressing",
        stepsTr: [
          `1. /addressing sayfasina git ve ${sourceFriendlyName} satirini veya bagli ${sourceSegmentName} segmentini bul.`,
          `2. Segment name alaninda ${sourceSegmentName} yazdigini kontrol et.`,
          `3. Subnet alanina ${recommendedSourceSubnet}, Gateway alanina ${recommendedSourceGateway} yaz.`,
          `4. ${sourceEndpoint?.hostname ?? sourceEndpointId} icin IP alanina ${recommendedSourceIp}, Gateway alanina ${recommendedSourceGateway} yaz.`,
          "5. Apply Manual IP Plan ile degerleri kaydet.",
          "6. Ardindan /deployment sayfasina donup sirasiyla Configure, Discover ve Run Validation calistir.",
        ],
        stepsEn: [
          `1. Open /addressing and find ${sourceFriendlyName} or the related ${sourceSegmentName} segment.`,
          `2. Confirm that the Segment name field shows ${sourceSegmentName}.`,
          `3. Enter ${recommendedSourceSubnet} in Subnet and ${recommendedSourceGateway} in Gateway.`,
          `4. For ${sourceEndpoint?.hostname ?? sourceEndpointId}, enter ${recommendedSourceIp} as the endpoint IP and ${recommendedSourceGateway} as the endpoint gateway.`,
          "5. Save the values with Apply Manual IP Plan.",
          "6. Then go back to /deployment and run Configure, Discover, and Run Validation in order.",
        ],
      };
    case "access_vlan":
      return {
        problemTypeTr: "Access VLAN eslesmesi bozuk",
        problemTypeEn: "Access VLAN mapping is incorrect",
        likelyFixTr: `${sourceFriendlyName} ve ${targetFriendlyName} icin port-segment eslesmesini ayni topology tasarimina gore hizala.`,
        likelyFixEn: `Align the port-to-segment mapping for ${sourceFriendlyName} and ${targetFriendlyName} with the topology design.`,
        suggestedValuesTr: [
          `${sourceFriendlyName} icin beklenen segment: ${sourceSegmentName}`,
          `${sourceFriendlyName} icin beklenen subnet/gateway: ${recommendedSourceSubnet} / ${recommendedSourceGateway}`,
          `${targetFriendlyName} icin beklenen segment: ${targetSegmentName}`,
          `${targetFriendlyName} icin beklenen subnet/gateway: ${recommendedTargetSubnet} / ${recommendedTargetGateway}`,
          "Switch access portu endpoint'in bagli oldugu segment ile ayni mantikta olmalidir.",
        ],
        suggestedValuesEn: [
          `Expected segment for ${sourceFriendlyName}: ${sourceSegmentName}`,
          `Expected subnet/gateway for ${sourceFriendlyName}: ${recommendedSourceSubnet} / ${recommendedSourceGateway}`,
          `Expected segment for ${targetFriendlyName}: ${targetSegmentName}`,
          `Expected subnet/gateway for ${targetFriendlyName}: ${recommendedTargetSubnet} / ${recommendedTargetGateway}`,
          "The switch access port should match the segment used by the endpoint.",
        ],
        pageLabelTr: "Topology Builder",
        pageLabelEn: "Topology Builder",
        pagePath: "/topology",
        stepsTr: [
          `1. /topology sayfasina git ve ${sourceEndpoint?.hostname ?? sourceEndpointId} ile ${targetEndpoint?.hostname ?? targetEndpointId} baglantilarini incele.`,
          `2. ${sourceEndpoint?.hostname ?? sourceEndpointId} cihazinin ${sourceSegmentName}, ${targetEndpoint?.hostname ?? targetEndpointId} cihazinin ${targetSegmentName} segmentinde durdugundan emin ol.`,
          "3. Endpoint'in bagli oldugu switch portu access mantiginda olmali ve yanlis segmente dusmemeli.",
          "4. Ardindan /addressing sayfasinda subnet/gateway degerlerinin ayni segment isimleriyle uyumlu kaldigini kontrol et.",
          "5. Kaydet, sonra /deployment sayfasinda yeniden Configure, Discover ve Run Validation calistir.",
        ],
        stepsEn: [
          `1. Open /topology and inspect the links for ${sourceEndpoint?.hostname ?? sourceEndpointId} and ${targetEndpoint?.hostname ?? targetEndpointId}.`,
          `2. Make sure ${sourceEndpoint?.hostname ?? sourceEndpointId} belongs to ${sourceSegmentName} and ${targetEndpoint?.hostname ?? targetEndpointId} belongs to ${targetSegmentName}.`,
          "3. The switch port connected to the endpoint should behave like an access port and should not point to the wrong segment.",
          "4. Then confirm on /addressing that subnet and gateway values still match those segment names.",
          "5. Save the topology and rerun Configure, Discover, and Run Validation from /deployment.",
        ],
      };
    case "trunk_propagation":
      return {
        problemTypeTr: "Trunk uzerinden VLAN tasinmiyor",
        problemTypeEn: "The VLAN is not carried across the trunk",
        likelyFixTr: `Switch-router uplink uzerinden ${sourceSegmentName} ve gerekiyorsa ${targetSegmentName} segmentlerini tasiyacak sekilde trunk mantigini duzelt.`,
        likelyFixEn: `Adjust the switch-to-router uplink so the trunk carries ${sourceSegmentName} and, if needed, ${targetSegmentName}.`,
        suggestedValuesTr: [
          `Trunk allowed VLAN listesine eklenmeli: ${sourceEndpoint?.vlan_id ?? targetEndpoint?.vlan_id ?? "ilgili VLAN"}`,
          `Kaynak subnet: ${recommendedSourceSubnet}`,
          `Hedef subnet: ${recommendedTargetSubnet}`,
        ],
        suggestedValuesEn: [
          `Add this VLAN to the trunk allowed list: ${sourceEndpoint?.vlan_id ?? targetEndpoint?.vlan_id ?? "the relevant VLAN"}`,
          `Source subnet: ${recommendedSourceSubnet}`,
          `Target subnet: ${recommendedTargetSubnet}`,
        ],
        pageLabelTr: "Topology Builder",
        pageLabelEn: "Topology Builder",
        pagePath: "/topology",
        stepsTr: [
          "1. /topology sayfasinda switch-router uplink baglantisini bul.",
          "2. Bu baglantinin trunk olarak dusunuldugu VLAN akisini kontrol et.",
          "3. Problemli endpoint'in ait oldugu VLAN'in uplink uzerinden tasinmasi gerektigini dogrula.",
          "4. Kaydet, sonra /configuration ve /deployment akisini tekrar calistir.",
          "5. Discover ve Run Validation ile trunk etkisini yeniden test et.",
        ],
        stepsEn: [
          "1. Open /topology and locate the switch-to-router uplink.",
          "2. Check the intended VLAN flow for that trunk-style link.",
          "3. Verify that the failing endpoint VLAN should be carried over the uplink.",
          "4. Save the draft, then rerun /configuration and /deployment steps.",
          "5. Re-run Discover and Run Validation to test the trunk path again.",
        ],
      };
    case "gateway_availability":
      return {
        problemTypeTr: "Gateway aktif degil veya bulunamadi",
        problemTypeEn: "Gateway is unavailable or missing",
        likelyFixTr: `${sourceFriendlyName} icin gateway degeri router tarafindaki ayni segment gateway'i ile eslesmeli.`,
        likelyFixEn: `The gateway value for ${sourceFriendlyName} should match the router gateway for the same segment.`,
        suggestedValuesTr: [
          `Gateway alani icin onerilen deger: ${recommendedSourceGateway}`,
          `Bagli subnet icin onerilen deger: ${recommendedSourceSubnet}`,
          `Endpoint IP ornegi: ${recommendedSourceIp}`,
        ],
        suggestedValuesEn: [
          `Recommended gateway value: ${recommendedSourceGateway}`,
          `Recommended subnet value: ${recommendedSourceSubnet}`,
          `Example endpoint IP: ${recommendedSourceIp}`,
        ],
        pageLabelTr: "IP Address Plan",
        pageLabelEn: "IP Address Plan",
        pagePath: "/addressing",
        stepsTr: [
          "1. /addressing sayfasinda ilgili segment gateway degerini kontrol et.",
          "2. Router alt arayuzu ile bu gateway adresinin eslesmesi gerektigini dogrula.",
          "3. Gerekirse subnet ve gateway alanlarini birlikte duzelt.",
          "4. Sonra /configuration sayfasinda configleri yeniden uret.",
          "5. /deployment sayfasinda Configure, Discover ve Run Validation adimlarini tekrar calistir.",
        ],
        stepsEn: [
          "1. Check the gateway value for the segment on /addressing.",
          "2. Verify that the router subinterface should match that gateway address.",
          "3. Update the subnet and gateway together if needed.",
          "4. Regenerate configs from /configuration.",
          "5. Then rerun Configure, Discover, and Run Validation on /deployment.",
        ],
      };
    case "route_selection":
      return {
        problemTypeTr: "Hedef ag icin route bulunamadi",
        problemTypeEn: "No route was found for the destination network",
        likelyFixTr: `${sourceFriendlyName} ile ${targetFriendlyName} arasinda hedef segmente giden yol eksik gorunuyor.`,
        likelyFixEn: `The path from ${sourceFriendlyName} to the target segment of ${targetFriendlyName} appears to be missing.`,
        suggestedValuesTr: [
          `Kaynak subnet: ${recommendedSourceSubnet}`,
          `Hedef subnet: ${recommendedTargetSubnet}`,
          `Hedef gateway: ${recommendedTargetGateway}`,
        ],
        suggestedValuesEn: [
          `Source subnet: ${recommendedSourceSubnet}`,
          `Target subnet: ${recommendedTargetSubnet}`,
          `Target gateway: ${recommendedTargetGateway}`,
        ],
        pageLabelTr: "Topology Builder",
        pageLabelEn: "Topology Builder",
        pagePath: "/topology",
        stepsTr: [
          "1. /topology sayfasinda hedef endpoint'in hangi subnet/VLAN icinde oldugunu kontrol et.",
          "2. Router'in bu agi dogrudan bagli mi yoksa route ile mi ogrenmesi gerektigini belirle.",
          "3. Gerekirse topology ve addressing bilgilerini route mantigina uygun duzelt.",
          "4. Ardindan /configuration sayfasinda yeni configleri uret.",
          "5. /deployment sayfasinda Configure, Discover ve Run Validation adimlarini tekrarla.",
        ],
        stepsEn: [
          "1. On /topology, check which subnet/VLAN the destination endpoint belongs to.",
          "2. Decide whether the router should know that network as connected or through a route.",
          "3. Adjust the topology and addressing to match the intended route logic.",
          "4. Regenerate the configs on /configuration.",
          "5. Rerun Configure, Discover, and Run Validation on /deployment.",
        ],
      };
    case "acl_evaluation":
      return {
        problemTypeTr: "ACL trafigi engelliyor",
        problemTypeEn: "An ACL is blocking the traffic",
        likelyFixTr: `${sourceFriendlyName} ile ${targetFriendlyName} arasindaki trafik ACL tarafinda beklenmedik sekilde engelleniyor olabilir.`,
        likelyFixEn: `Traffic between ${sourceFriendlyName} and ${targetFriendlyName} may be blocked unexpectedly by an ACL.`,
        suggestedValuesTr: [
          `Kaynak IP/Subnet: ${recommendedSourceIp} / ${recommendedSourceSubnet}`,
          `Hedef IP/Subnet: ${recommendedTargetIp} / ${recommendedTargetSubnet}`,
          "Bu trafik permit edilmeli mi yoksa block senaryosu mu bekleniyor, bunu kontrol et.",
        ],
        suggestedValuesEn: [
          `Source IP/Subnet: ${recommendedSourceIp} / ${recommendedSourceSubnet}`,
          `Target IP/Subnet: ${recommendedTargetIp} / ${recommendedTargetSubnet}`,
          "Confirm whether this traffic should be permitted or intentionally blocked.",
        ],
        pageLabelTr: "Change Builder",
        pageLabelEn: "Change Builder",
        pagePath: "/changes",
        stepsTr: [
          "1. /changes sayfasina git ve ACL ile ilgili degisikligi incele veya yeni degisiklik taslagi olustur.",
          "2. Kaynak subnet ile hedef subnet arasinda deny kuralinin olup olmadigini kontrol et.",
          "3. Gerekirse permit/deny sirasini ve kapsamını duzelt.",
          "4. Simulasyon sonrasi onizlemeyi tekrar degerlendir.",
          "5. Son olarak /deployment veya change workflow uzerinden yeniden dogrulama yap.",
        ],
        stepsEn: [
          "1. Open /changes and inspect the ACL-related change or create a new ACL adjustment draft.",
          "2. Check whether a deny rule exists between the source and target subnets.",
          "3. Update the permit/deny order and scope if needed.",
          "4. Re-evaluate the simulation and preview.",
          "5. Then run validation again through the deployment or change workflow.",
        ],
      };
    case "destination_availability":
      return {
        problemTypeTr: "Hedef endpoint topolojide hazir degil",
        problemTypeEn: "The destination endpoint is not ready in the topology",
        likelyFixTr: `${targetFriendlyName} icin segment, baglanti veya endpoint adresleme bilgileri eksik olabilir.`,
        likelyFixEn: `${targetFriendlyName} may be missing segment, link, or endpoint addressing details.`,
        suggestedValuesTr: [
          `${targetEndpointId} icin subnet: ${recommendedTargetSubnet}`,
          `${targetEndpointId} icin gateway: ${recommendedTargetGateway}`,
          `${targetEndpointId} icin IP ornegi: ${recommendedTargetIp}`,
        ],
        suggestedValuesEn: [
          `Subnet for ${targetEndpointId}: ${recommendedTargetSubnet}`,
          `Gateway for ${targetEndpointId}: ${recommendedTargetGateway}`,
          `Example IP for ${targetEndpointId}: ${recommendedTargetIp}`,
        ],
        pageLabelTr: "Topology Builder",
        pageLabelEn: "Topology Builder",
        pagePath: "/topology",
        stepsTr: [
          "1. /topology sayfasinda hedef endpoint'in gerçekten switch'e bagli oldugunu kontrol et.",
          "2. Cihazin hostname, link ve interface secimlerinin bos olmadigindan emin ol.",
          "3. Sonra /addressing sayfasinda hedef endpoint icin IP ve gateway bilgilerini kontrol et.",
          "4. Kaydet ve /deployment sayfasinda Discover ile guncel durumu tekrar olustur.",
          "5. Son adimda Run Validation ile sonucu tekrar test et.",
        ],
        stepsEn: [
          "1. On /topology, confirm that the destination endpoint is actually linked to the switch.",
          "2. Make sure the hostname, link, and interface selections are all present.",
          "3. Then check the destination IP and gateway values on /addressing.",
          "4. Save the draft and rerun Discover on /deployment.",
          "5. Finish by running Run Validation again.",
        ],
      };
    default:
      return {
        problemTypeTr: "Genel dogrulama hatasi",
        problemTypeEn: "General validation failure",
        likelyFixTr: "Topology, addressing ve deployment adimlarini birlikte tekrar gozden gecir.",
        likelyFixEn: "Review the topology, addressing, and deployment steps together.",
        suggestedValuesTr: [
          `Kaynak subnet/gateway: ${recommendedSourceSubnet} / ${recommendedSourceGateway}`,
          `Hedef subnet/gateway: ${recommendedTargetSubnet} / ${recommendedTargetGateway}`,
        ],
        suggestedValuesEn: [
          `Source subnet/gateway: ${recommendedSourceSubnet} / ${recommendedSourceGateway}`,
          `Target subnet/gateway: ${recommendedTargetSubnet} / ${recommendedTargetGateway}`,
        ],
        pageLabelTr: "Deployment Progress",
        pageLabelEn: "Deployment Progress",
        pagePath: "/deployment",
        stepsTr: [
          "1. /deployment sayfasina git ve Configure, Discover, Run Validation sirasini koru.",
          "2. /topology ve /addressing sayfalarindaki eksik alanlari kontrol et.",
          "3. Configuration Preview'de olusan komutlarin mantikli oldugunu incele.",
          "4. Live Topology ekraninda cihaz ve link durumlarini karsilastir.",
          "5. Sonra validation sonucunu yeniden uret.",
        ],
        stepsEn: [
          "1. Go to /deployment and keep the Configure, Discover, Run Validation order.",
          "2. Review missing values on /topology and /addressing.",
          "3. Inspect whether the generated commands in Configuration Preview look reasonable.",
          "4. Compare device and link state on Live Topology.",
          "5. Then run validation again.",
        ],
      };
  }
}

function applyAddressPlanToTopology(topology: TopologySpec, plan: AddressingPlan) {
  const nextVlans = plan.allocations.map((allocation, index) => {
    const existingVlan = topology.vlans[index]
      ?? topology.vlans.find((vlan) => vlan.name.toUpperCase() === allocation.name.toUpperCase());
    const vlanId = existingVlan?.vlan_id ?? ((index + 1) * 10);
    return {
      vlan_id: vlanId,
      name: allocation.name,
      subnet: allocation.network,
      gateway: allocation.gateway,
      endpoint_ids: existingVlan?.endpoint_ids ?? [],
    };
  });

  const nextSubnets = nextVlans.map((vlan) => {
    const existingSubnet = topology.subnets.find((subnet) => subnet.vlan_id === vlan.vlan_id);
    return {
      id: existingSubnet?.id ?? `vlan${vlan.vlan_id}-subnet`,
      name: existingSubnet?.name ?? `${vlan.name} subnet`,
      network: vlan.subnet ?? existingSubnet?.network ?? `192.168.${vlan.vlan_id}.0/24`,
      gateway: vlan.gateway ?? existingSubnet?.gateway ?? `192.168.${vlan.vlan_id}.1`,
      vlan_id: vlan.vlan_id,
    };
  });

  const endpointCountByVlan = new Map<number, number>();
  const nextEndpoints = topology.endpoints.map((endpoint, index) => {
    const existingAssignedVlan = nextVlans.find((item) => item.vlan_id === endpoint.vlan_id);
    const fallbackVlan = nextVlans[Math.min(index, Math.max(nextVlans.length - 1, 0))];
    const vlan = existingAssignedVlan ?? fallbackVlan;
    if (!vlan?.subnet) {
      return endpoint;
    }
    const subnet = nextSubnets.find((item) => item.vlan_id === vlan.vlan_id);
    const currentCount = endpointCountByVlan.get(vlan.vlan_id) ?? 0;
    endpointCountByVlan.set(vlan.vlan_id, currentCount + 1);
    const hostOffset = 10 + currentCount;
    const baseIp = networkBaseIp(vlan.subnet);
    return {
      ...endpoint,
      vlan_id: vlan.vlan_id,
      subnet_id: subnet?.id ?? endpoint.subnet_id,
      ip_address: addIpv4Offset(baseIp, hostOffset),
      default_gateway: vlan.gateway ?? endpoint.default_gateway,
    };
  });

  const endpointIdsByVlan = new Map<number, string[]>();
  nextEndpoints.forEach((endpoint) => {
    if (typeof endpoint.vlan_id !== "number") {
      return;
    }
    const existingIds = endpointIdsByVlan.get(endpoint.vlan_id) ?? [];
    endpointIdsByVlan.set(endpoint.vlan_id, [...existingIds, endpoint.id]);
  });

  const finalizedVlans = nextVlans.map((vlan) => ({
    ...vlan,
    endpoint_ids: endpointIdsByVlan.get(vlan.vlan_id) ?? [],
  }));

  const nextTopology = {
    ...topology,
    vlans: finalizedVlans,
    subnets: nextSubnets,
    endpoints: nextEndpoints,
  };
  return synchronizeTopologyAssignments(nextTopology);
}

function synchronizeTopologyAssignments(topology: TopologySpec): TopologySpec {
  const deviceById = new Map(topology.devices.map((device) => [device.id, device]));
  const endpointByDeviceId = new Map(topology.endpoints.map((endpoint) => [endpoint.device_id, endpoint]));
  const uplinkLink = topology.links.find((link) => {
    const source = deviceById.get(link.source_device);
    const target = deviceById.get(link.target_device);
    return (source?.type === "router" && target?.type === "switch")
      || (source?.type === "switch" && target?.type === "router");
  });
  const allVlanIds = topology.vlans.map((vlan) => vlan.vlan_id);

  const nextDevices = topology.devices.map((device) => {
    if (device.type === "switch") {
      return {
        ...device,
        interfaces: device.interfaces.map((iface) => {
          const endpointLink = topology.links.find((link) => (
            (link.source_device === device.id && link.source_interface === iface.name && endpointByDeviceId.has(link.target_device))
            || (link.target_device === device.id && link.target_interface === iface.name && endpointByDeviceId.has(link.source_device))
          ));
          if (endpointLink) {
            const endpointDeviceId = endpointLink.source_device === device.id ? endpointLink.target_device : endpointLink.source_device;
            const endpoint = endpointByDeviceId.get(endpointDeviceId);
            return {
              ...iface,
              access_vlan: endpoint?.vlan_id,
              trunk_vlans: [],
            };
          }
          const isUplink = uplinkLink && (
            (uplinkLink.source_device === device.id && uplinkLink.source_interface === iface.name)
            || (uplinkLink.target_device === device.id && uplinkLink.target_interface === iface.name)
          );
          if (isUplink) {
            return {
              ...iface,
              access_vlan: undefined,
              trunk_vlans: allVlanIds,
            };
          }
          return iface;
        }),
      };
    }

    if (device.type === "router") {
      const baseInterfaces = device.interfaces.filter((iface) => !iface.name.includes("."));
      const existingSubinterfaces = device.interfaces.filter((iface) => iface.name.includes("."));
      const routerUplinkInterface = uplinkLink
        ? (uplinkLink.source_device === device.id ? uplinkLink.source_interface : uplinkLink.target_device === device.id ? uplinkLink.target_interface : null)
        : null;
      const autoSubinterfaces = routerUplinkInterface
        ? topology.vlans.map((vlan) => ({
          name: `${routerUplinkInterface}.${vlan.vlan_id}`,
          enabled: true,
          ipv4_address: vlan.gateway && vlan.subnet ? `${vlan.gateway}/${vlan.subnet.split("/")[1] ?? "24"}` : undefined,
        }))
        : [];
      const preservedSubinterfaces = existingSubinterfaces.filter((iface) => !autoSubinterfaces.some((auto) => auto.name === iface.name));
      return {
        ...device,
        interfaces: [
          ...baseInterfaces,
          ...autoSubinterfaces,
          ...preservedSubinterfaces,
        ],
      };
    }

    return device;
  });

  return {
    ...topology,
    devices: nextDevices,
  };
}

function ensureSegmentTopologyEntry(topology: TopologySpec, segmentName: string, index: number) {
  const existingVlan = topology.vlans[index];
  if (existingVlan) {
    const existingSubnet = topology.subnets.find((subnet) => subnet.vlan_id === existingVlan.vlan_id);
    return {
      vlan: existingVlan,
      subnet: existingSubnet ?? {
        id: `vlan${existingVlan.vlan_id}-subnet`,
        name: `${existingVlan.name} subnet`,
        network: existingVlan.subnet ?? `192.168.${existingVlan.vlan_id}.0/24`,
        gateway: existingVlan.gateway ?? `192.168.${existingVlan.vlan_id}.1`,
        vlan_id: existingVlan.vlan_id,
      },
    };
  }

  const vlanId = (index + 1) * 10;
  return {
    vlan: {
      vlan_id: vlanId,
      name: segmentName || `VLAN${vlanId}`,
      subnet: `192.168.${vlanId}.0/24`,
      gateway: `192.168.${vlanId}.1`,
      endpoint_ids: [],
    },
    subnet: {
      id: `vlan${vlanId}-subnet`,
      name: `${segmentName || `VLAN${vlanId}`} subnet`,
      network: `192.168.${vlanId}.0/24`,
      gateway: `192.168.${vlanId}.1`,
      vlan_id: vlanId,
    },
  };
}

function segmentBindingFromTopology(topology: TopologySpec, segmentName: string, index: number) {
  const vlanByName = topology.vlans.find((vlan) => vlan.name.toUpperCase() === segmentName.toUpperCase());
  const vlan = topology.vlans[index] ?? vlanByName ?? null;
  const subnetByName = topology.subnets.find((subnet) => subnet.name.replace(/ subnet$/i, "").toUpperCase() === segmentName.toUpperCase());
  const subnet = vlan
    ? topology.subnets.find((item) => item.vlan_id === vlan.vlan_id) ?? subnetByName ?? null
    : topology.subnets[index] ?? subnetByName ?? null;
  const endpoints = vlan
    ? topology.endpoints.filter((endpoint) => endpoint.vlan_id === vlan.vlan_id)
    : subnet
      ? topology.endpoints.filter((endpoint) => endpoint.subnet_id === subnet.id)
      : [];
  return { vlan, subnet, endpoints };
}

export function OverviewPage() {
  const { topologyDraft, activeDeployment, activeChange, progressEvents, selectedWorkflowId, savedTopologies, activeTopologyId } = useWorkflowStore();
  const events = latestWorkflowEvents(progressEvents, selectedWorkflowId);
  const activeTopology = savedTopologies.find((item) => item.id === activeTopologyId) ?? null;

  return (
    <div className="page-grid">
      <SectionCard title="Workflow Snapshot" subtitle="Current draft, deployment, and change state.">
        <div className="metric-grid">
          {topologySummary(topologyDraft).map((item) => (
            <MetricTile key={item.label} label={item.label} value={item.value} tone="accent" />
          ))}
          <MetricTile label="Deployment state" value={activeDeployment?.status ?? "Not created"} tone="default" />
          <MetricTile label="Change state" value={activeChange?.status ?? "No draft change"} tone="default" />
          <MetricTile label="Saved topologies" value={savedTopologies.length} tone="default" />
          <MetricTile label="Active topology" value={activeTopology?.name ?? topologyDraft.project.name} tone="accent" />
        </div>
      </SectionCard>

      <SectionCard title="Topology Storyboard" subtitle="The saved or currently edited topology is rendered here for quick verification.">
        <TopologyCanvas topology={topologyDraft} deployment={activeDeployment} change={activeChange} mode="draft" />
        {activeTopology ? <p className="inline-note">Last saved topology: <strong>{activeTopology.name}</strong> • Updated: {formatTimestamp(activeTopology.updated_at)}</p> : null}
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
  const {
    deployments,
    activeDeployment,
    topologyDraft,
    upsertDeployment,
    setActiveDeployment,
    savedTopologies,
    activeTopologyId,
    loadSavedTopology,
    deleteSavedTopology,
  } = useWorkflowStore();
  const createDeploymentMutation = useMutation({
    mutationFn: () => workflowClient.createDeployment(topologyDraft.project.name, topologyDraft),
    onSuccess: (deployment) => {
      upsertDeployment(deployment);
    },
  });

  return (
    <div className="page-grid">
      <SectionCard title="Saved Topologies" subtitle="Locally saved topology drafts appear here and can be reopened or removed.">
        {savedTopologies.length === 0 ? (
          <EmptyState title="No saved topologies" description="Save a topology from the builder page to reuse it here." />
        ) : (
          <div className="list-grid">
            {savedTopologies.map((record: SavedTopologyRecord) => (
              <article key={record.id} className={`list-card list-card--static ${activeTopologyId === record.id ? "list-card--active" : ""}`}>
                <strong>{record.name}</strong>
                <span>{record.id}</span>
                <small>{formatTimestamp(record.updated_at)}</small>
                <div className="button-row">
                  <button className="button button--secondary" onClick={() => loadSavedTopology(record.id)} type="button">Load</button>
                  <button className="button button--danger" onClick={() => deleteSavedTopology(record.id)} type="button">Delete</button>
                </div>
              </article>
            ))}
          </div>
        )}
      </SectionCard>

      <SectionCard
        title="Network Project List"
        subtitle="Backend deployment records created from the selected or edited topology."
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
        const nextTopology = response.interpretation.topology;
        const nextRequest = addressRequestFromTopology(nextTopology);
        store.setTopologyDraft(nextTopology);
        store.setAddressRequest(nextRequest);
        store.setAddressPlan(addressPlanFromTopology(nextTopology, nextRequest));
        setProjectName(nextTopology.project.name);
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
                <div className="stack">
                  <strong>Terminal command flow</strong>
                  <pre>{buildConfigurationTerminalFlow(rendered.platform, rendered.content).join("\n")}</pre>
                </div>
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
    mutationFn: async (deploymentId: string) => {
      await workflowClient.configureDeployment(deploymentId);
      return workflowClient.getDeployment(deploymentId);
    },
    onSuccess: (deployment) => {
      store.upsertDeployment(deployment);
    },
  });
  const discoverMutation = useMutation({
    mutationFn: async (deploymentId: string) => {
      await workflowClient.discoverDeployment(deploymentId);
      return workflowClient.getDeployment(deploymentId);
    },
    onSuccess: (deployment) => {
      store.upsertDeployment(deployment);
    },
  });
  const validateMutation = useMutation({
    mutationFn: async (deploymentId: string) => {
      await workflowClient.validateDeployment(deploymentId);
      return workflowClient.getDeployment(deploymentId);
    },
    onSuccess: (deployment) => {
      store.upsertDeployment(deployment);
    },
  });

  const events = latestWorkflowEvents(store.progressEvents, activeDeployment?.id ?? null);
  const configurationReady = Boolean(activeDeployment?.configuration_preview?.rendered_configurations?.length);
  const discoveryReady = Boolean(activeDeployment?.discovered_state?.device_snapshots?.length);
  const validationReady = Boolean(activeDeployment?.validations?.length);
  const latestError = createDeploymentMutation.error ?? configureMutation.error ?? discoverMutation.error ?? validateMutation.error;

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
        <div className="guide-grid">
          <article className="list-card list-card--static">
            <strong>Turkce aciklama</strong>
            <span>`Deploy` mevcut topology taslagini backend'e gonderir ve dry-run GNS3 plani olusturur.</span>
            <span>`Configure` cihaz konfigürasyon onizlemesini backend tarafinda uretir.</span>
            <span>`Discover` calisan durum bilgisini okumayi, `Run Validation` ise test sonucunu guncellemeyi hedefler.</span>
          </article>
          <article className="list-card list-card--static">
            <strong>English guide</strong>
            <span>`Deploy` sends the current topology draft to the backend and builds a dry-run GNS3 plan.</span>
            <span>`Configure` generates the device configuration preview on the backend.</span>
            <span>`Discover` refreshes runtime state, and `Run Validation` refreshes validation results.</span>
          </article>
        </div>
        {latestError ? (
          <article className="list-card list-card--static">
            <strong>Workflow error</strong>
            <span>{mutationErrorMessage(latestError)}</span>
          </article>
        ) : null}
        {activeDeployment ? (
          <div className="stack">
            <div className="metric-grid">
              <MetricTile label="Project" value={activeDeployment.project_name} tone="accent" />
              <MetricTile label="Status" value={activeDeployment.status} />
              <MetricTile label="Dry-run nodes" value={activeDeployment.dry_run_plan?.node_requests?.length ?? 0} />
              <MetricTile label="Dry-run links" value={activeDeployment.dry_run_plan?.link_requests?.length ?? 0} />
              <MetricTile label="Configure result" value={configurationReady ? "Ready" : "Pending"} tone={configurationReady ? "success" : "default"} />
              <MetricTile label="Discover result" value={discoveryReady ? "Ready" : "Pending"} tone={discoveryReady ? "success" : "default"} />
              <MetricTile label="Validation result" value={validationReady ? "Ready" : "Pending"} tone={validationReady ? "success" : "default"} />
            </div>
            <div className="guide-grid">
              <article className="list-card list-card--static">
                <strong>Configure</strong>
                <span>Purpose: build topology-based device configs from the current project draft.</span>
                <small>Status: {configureMutation.isPending ? "Running" : configurationReady ? "Configuration preview created" : "Not completed yet"}</small>
              </article>
              <article className="list-card list-card--static">
                <strong>Discover</strong>
                <span>Purpose: read back runtime device, interface, VLAN, route, and ACL state.</span>
                <small>Status: {discoverMutation.isPending ? "Running" : discoveryReady ? "Discovered state available" : "Not completed yet"}</small>
              </article>
              <article className="list-card list-card--static">
                <strong>Run Validation</strong>
                <span>Purpose: execute verification and connectivity checks on the current deployment.</span>
                <small>Status: {validateMutation.isPending ? "Running" : validationReady ? "Validation results available" : "Not completed yet"}</small>
              </article>
            </div>
            <div className="timeline">
              {(events.length ? events : [{ status: "Draft" }]).map((event, index) => (
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
                {(() => {
                  const topology = activeDeployment.topology ?? defaultTopologyFallback();
                  const fixGuide = buildValidationFixGuide(topology, index, validation.failure_stage);
                  return (
                    <>
                      <strong>{validationLabel(topology, index)}</strong>
                      <StatusPill value={validation.predicted_reachable ? "Reachable" : "Blocked"} tone={validation.predicted_reachable ? "success" : "danger"} />
                      <span>{validation.failure_stage ?? validation.state ?? "validated"}</span>
                      <small>{validation.technical_explanation ?? validation.suspected_reason ?? "No explanation."}</small>

                      {!validation.predicted_reachable ? (
                        <div className="stack">
                          <article className="list-card list-card--static">
                            <strong>Problem type</strong>
                            <span>{fixGuide.problemTypeTr}</span>
                            <small>{fixGuide.problemTypeEn}</small>
                          </article>
                          <article className="list-card list-card--static">
                            <strong>Likely fix</strong>
                            <span>{fixGuide.likelyFixTr}</span>
                            <small>{fixGuide.likelyFixEn}</small>
                          </article>
                          <div className="comparison-grid">
                            <article className="list-card list-card--static">
                              <strong>Onerilen doldurma degerleri</strong>
                              {fixGuide.suggestedValuesTr.map((item) => <span key={item}>{item}</span>)}
                            </article>
                            <article className="list-card list-card--static">
                              <strong>Suggested field values</strong>
                              {fixGuide.suggestedValuesEn.map((item) => <span key={item}>{item}</span>)}
                            </article>
                          </div>
                          <article className="list-card list-card--static">
                            <strong>Go to</strong>
                            <span>
                              <Link to={fixGuide.pagePath}>{fixGuide.pageLabelTr}</Link>
                              {" / "}
                              <Link to={fixGuide.pagePath}>{fixGuide.pageLabelEn}</Link>
                            </span>
                          </article>
                          <div className="comparison-grid">
                            <article className="list-card list-card--static">
                              <strong>Turkce fix adimlari</strong>
                              {fixGuide.stepsTr.map((step) => <span key={step}>{step}</span>)}
                            </article>
                            <article className="list-card list-card--static">
                              <strong>English fix steps</strong>
                              {fixGuide.stepsEn.map((step) => <span key={step}>{step}</span>)}
                            </article>
                          </div>
                        </div>
                      ) : null}
                    </>
                  );
                })()}
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

export function OverviewPageV2() {
  const { topologyDraft, activeDeployment, activeChange, progressEvents, selectedWorkflowId, savedTopologies, activeTopologyId } = useWorkflowStore();
  const events = latestWorkflowEvents(progressEvents, selectedWorkflowId);
  const activeTopology = savedTopologies.find((item) => item.id === activeTopologyId) ?? null;

  return (
    <div className="page-grid">
      <SectionCard title="Workflow Snapshot" subtitle="Current draft, saved topology, deployment, and change state.">
        <div className="metric-grid">
          {topologySummary(topologyDraft).map((item) => (
            <MetricTile key={item.label} label={item.label} value={item.value} tone="accent" />
          ))}
          <MetricTile label="Saved topologies" value={savedTopologies.length} />
          <MetricTile label="Active topology" value={activeTopology?.name ?? topologyDraft.project.name} tone="accent" />
          <MetricTile label="Deployment state" value={activeDeployment?.status ?? "Not created"} tone="default" />
          <MetricTile label="Change state" value={activeChange?.status ?? "No draft change"} tone="default" />
        </div>
      </SectionCard>

      <SectionCard title="Topology Storyboard" subtitle="The active topology draft is always mirrored here.">
        <TopologyCanvas topology={topologyDraft} deployment={activeDeployment} change={activeChange} mode="draft" />
        {activeTopology ? <p className="inline-note">Saved topology shown in overview: <strong>{activeTopology.name}</strong> • {formatTimestamp(activeTopology.updated_at)}</p> : null}
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

export function ProjectsPageV2() {
  const {
    deployments,
    activeDeployment,
    topologyDraft,
    upsertDeployment,
    setActiveDeployment,
    savedTopologies,
    activeTopologyId,
    loadSavedTopology,
    deleteSavedTopology,
  } = useWorkflowStore();
  const createDeploymentMutation = useMutation({
    mutationFn: () => workflowClient.createDeployment(topologyDraft.project.name, topologyDraft),
    onSuccess: (deployment) => {
      upsertDeployment(deployment);
    },
  });

  return (
    <div className="page-grid">
      <SectionCard title="Saved Topologies" subtitle="Topologies saved from the builder are listed here.">
        {savedTopologies.length === 0 ? (
          <EmptyState title="No saved topologies" description="Save a topology from the builder page to reuse it here." />
        ) : (
          <div className="list-grid">
            {savedTopologies.map((record) => (
              <article key={record.id} className={`list-card list-card--static ${activeTopologyId === record.id ? "list-card--active" : ""}`}>
                <strong>{record.name}</strong>
                <span>{record.id}</span>
                <small>{formatTimestamp(record.updated_at)}</small>
                <div className="button-row">
                  <button className="button button--secondary" type="button" onClick={() => loadSavedTopology(record.id)}>Load</button>
                  <button className="button button--danger" type="button" onClick={() => deleteSavedTopology(record.id)}>Delete</button>
                </div>
              </article>
            ))}
          </div>
        )}
      </SectionCard>

      <SectionCard
        title="Deployment Projects"
        subtitle="Backend deployment records created from the active topology."
        actions={<button className="button" onClick={() => createDeploymentMutation.mutate()}>Create Project</button>}
      >
        {deployments.length === 0 ? (
          <EmptyState title="No deployment records" description="Create a deployment from the current topology draft." />
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
    </div>
  );
}

export function TopologyBuilderPageV2() {
  const store = useWorkflowStore();
  const [projectName, setProjectName] = useState(store.topologyDraft.project.name);
  const [prompt, setPrompt] = useState("Üç VLAN'lı küçük ofis ağı kur. Guest ağı Admin ağına erişemesin.");
  const examplePrompts = [
    "Uc VLAN'li kucuk ofis agi kur. Guest agi Admin agina erisemesin.",
    "Create a two-router branch topology with OSPF between HQ and branch.",
    "Build a simple office topology with one router, one switch, and two endpoints.",
  ];
  const promptTemplates = [
    "Create a topology with [router count] routers, [switch count] switches, and [endpoint count] endpoints. Use [VLAN/OSPF/guest isolation] requirements.",
    "Build an office network for [site name] with [router count] routers, [switch count] switches, and [endpoint count] PCs. Keep [segment name] isolated from [segment name].",
    "Design an HQ and branch topology with [router count] routers, OSPF between sites, and [endpoint count] endpoints. Each site should have its own LAN.",
    "Kurumsal bir topoloji olustur: [router sayisi] router, [switch sayisi] switch, [endpoint sayisi] endpoint olsun. [VLAN/OSPF/guest izolasyonu] gereksinimlerini uygula.",
    "[site adi] icin bir ofis agi kur. [router sayisi] router, [switch sayisi] switch ve [endpoint sayisi] istemci kullan. [segment adi] agi [segment adi] agina erismesin.",
    "Iki lokasyonlu bir ag tasarla: HQ ve Branch arasinda OSPF calissin, toplam [endpoint sayisi] endpoint olsun, gerekiyorsa VLAN 10/20/30 kullan.",
  ];
  const promptPlaceholder = [
    "Create a topology with [router count] routers, [switch count] switches, and [endpoint count] endpoints.",
    "Use [VLAN/OSPF/guest isolation] requirements.",
    "",
    "Ornek / Example:",
    "Build an office network with 1 router, 1 switch, and 3 endpoints. Guest must not access Admin.",
  ].join("\\n");
  const [sourceDeviceId, setSourceDeviceId] = useState(store.topologyDraft.devices[0]?.id ?? "");
  const [targetDeviceId, setTargetDeviceId] = useState(store.topologyDraft.devices[1]?.id ?? "");
  const [sourceInterface, setSourceInterface] = useState(store.topologyDraft.devices[0]?.interfaces[0]?.name ?? "");
  const [targetInterface, setTargetInterface] = useState(store.topologyDraft.devices[1]?.interfaces[0]?.name ?? "");
  const interpretTopologyMutation = useMutation({
    mutationFn: (inputPrompt: string) =>
      workflowClient.interpretTopology(inputPrompt, {
        current_topology: store.topologyDraft,
      }),
    onSuccess: (response) => {
      if (response.interpretation.topology) {
        const nextTopology = response.interpretation.topology;
        const nextRequest = addressRequestFromTopology(nextTopology);
        store.setTopologyDraft(nextTopology);
        store.setAddressRequest(nextRequest);
        store.setAddressPlan(addressPlanFromTopology(nextTopology, nextRequest));
        setProjectName(nextTopology.project.name);
      }
    },
  });

  useEffect(() => {
    if (prompt.startsWith("Ã") || prompt.startsWith("Uc VLAN")) {
      setPrompt("");
    }
  }, [prompt]);

  useEffect(() => {
    setProjectName(store.topologyDraft.project.name);
  }, [store.topologyDraft.project.name]);

  useEffect(() => {
    const sourceDevice = store.topologyDraft.devices.find((device) => device.id === sourceDeviceId) ?? store.topologyDraft.devices[0];
    const targetDevice = store.topologyDraft.devices.find((device) => device.id === targetDeviceId) ?? store.topologyDraft.devices[1] ?? store.topologyDraft.devices[0];
    setSourceDeviceId(sourceDevice?.id ?? "");
    setTargetDeviceId(targetDevice?.id ?? "");
    setSourceInterface(sourceDevice?.interfaces[0]?.name ?? "");
    setTargetInterface(targetDevice?.interfaces[0]?.name ?? "");
  }, [sourceDeviceId, store.topologyDraft.devices, targetDeviceId]);

  const saveTopology = () => {
    store.updateProjectName(projectName);
    store.saveTopology(projectName);
  };

  const sourceDevice = store.topologyDraft.devices.find((device) => device.id === sourceDeviceId) ?? null;
  const targetDevice = store.topologyDraft.devices.find((device) => device.id === targetDeviceId) ?? null;
  const sourceInterfaceGuide = sourceDevice ? interfaceExplanation(sourceDevice.type, sourceInterface) : null;
  const targetInterfaceGuide = targetDevice ? interfaceExplanation(targetDevice.type, targetInterface) : null;
  const interpretedSummary = interpretTopologyMutation.data ? interpretTopologySummary(interpretTopologyMutation.data.interpretation) : null;

  return (
    <div className="page-grid">
      <SectionCard
        title="Visual Topology Builder"
        subtitle="Build, save, delete, and rebuild topologies from this page."
        actions={(
          <div className="button-row">
            <button className="button button--secondary" onClick={store.undo}>Undo</button>
            <button className="button button--secondary" onClick={store.redo}>Redo</button>
            <button className="button button--secondary" onClick={() => store.resetDraftToDefault()}>Reset Default</button>
          </div>
        )}
      >
        <div className="builder-toolbar">
          <label className="field">
            <span>Project name</span>
            <input value={projectName} onChange={(event) => setProjectName(event.target.value)} />
          </label>
          <button className="button" onClick={saveTopology}>Save Topology</button>
          <button className="button button--secondary" onClick={() => store.setTopologyDraft(defaultTopologyFallback())}>Clear Draft</button>
          <button className="button button--secondary" onClick={() => store.addDevice("router")}>Add Router</button>
          <button className="button button--secondary" onClick={() => store.addDevice("switch")}>Add Switch</button>
          <button className="button button--secondary" onClick={() => store.addDevice("endpoint")}>Add Endpoint</button>
          <button className="button button--secondary" onClick={() => store.addVlan()}>Add VLAN</button>
        </div>
        <div className="builder-grid">
          {store.topologyDraft.devices.map((device) => (
            <label key={device.id} className="field">
              <span>{device.type.toUpperCase()} hostname</span>
              <input value={device.hostname} onChange={(event) => store.updateDeviceHostname(device.id, event.target.value)} />
            </label>
          ))}
        </div>
        <SectionCard title="Link Builder" subtitle="Connect devices by selecting source and target interfaces.">
          <div className="builder-grid">
            <label className="field">
              <span>Source device</span>
              <select value={sourceDeviceId} onChange={(event) => {
                const nextId = event.target.value;
                setSourceDeviceId(nextId);
                const nextDevice = store.topologyDraft.devices.find((device) => device.id === nextId);
                setSourceInterface(nextDevice?.interfaces[0]?.name ?? "");
              }}>
                {store.topologyDraft.devices.map((device) => <option key={device.id} value={device.id}>{device.hostname}</option>)}
              </select>
            </label>
            <label className="field">
              <span>Source interface</span>
              <select value={sourceInterface} onChange={(event) => setSourceInterface(event.target.value)}>
                {(store.topologyDraft.devices.find((device) => device.id === sourceDeviceId)?.interfaces ?? []).map((iface) => <option key={iface.name} value={iface.name}>{iface.name}</option>)}
              </select>
            </label>
            <label className="field">
              <span>Target device</span>
              <select value={targetDeviceId} onChange={(event) => {
                const nextId = event.target.value;
                setTargetDeviceId(nextId);
                const nextDevice = store.topologyDraft.devices.find((device) => device.id === nextId);
                setTargetInterface(nextDevice?.interfaces[0]?.name ?? "");
              }}>
                {store.topologyDraft.devices.map((device) => <option key={device.id} value={device.id}>{device.hostname}</option>)}
              </select>
            </label>
            <label className="field">
              <span>Target interface</span>
              <select value={targetInterface} onChange={(event) => setTargetInterface(event.target.value)}>
                {(store.topologyDraft.devices.find((device) => device.id === targetDeviceId)?.interfaces ?? []).map((iface) => <option key={iface.name} value={iface.name}>{iface.name}</option>)}
              </select>
            </label>
          </div>
          <div className="button-row">
            <button className="button" type="button" onClick={() => store.addLink(sourceDeviceId, sourceInterface, targetDeviceId, targetInterface)}>Add Link</button>
          </div>
          <div className="comparison-grid">
            <article className="list-card list-card--static">
              <strong>Source interface guide</strong>
              <span>{sourceInterfaceGuide?.tr ?? "Kaynak cihaz ve interface secildiginde burada aciklama gorunur."}</span>
              <small>{sourceInterfaceGuide?.en ?? "Guidance appears here after you choose a source device and interface."}</small>
            </article>
            <article className="list-card list-card--static">
              <strong>Target interface guide</strong>
              <span>{targetInterfaceGuide?.tr ?? "Hedef cihaz ve interface secildiginde burada aciklama gorunur."}</span>
              <small>{targetInterfaceGuide?.en ?? "Guidance appears here after you choose a target device and interface."}</small>
            </article>
          </div>
          <div className="comparison-grid">
            <article className="list-card list-card--static">
              <strong>GigabitEthernet aciklamasi</strong>
              <span>`GigabitEthernet0/0`, `GigabitEthernet0/1` gibi adlar router veya switch fiziksel portlarini temsil eder.</span>
              <span>Router to Switch baglantisinda uplink olarak, Switch to Endpoint baglantisinda ise access port mantigiyla dusunulmelidir.</span>
            </article>
            <article className="list-card list-card--static">
              <strong>Recommended link styles</strong>
              <span>Router to Switch: uplink, often trunk-ready in VLAN scenarios.</span>
              <span>Switch to Endpoint: single-VLAN access style connection.</span>
              <span>Switch to Switch: trunk/uplink.</span>
              <span>Endpoint to Endpoint: usually not recommended for this workflow.</span>
            </article>
          </div>
        </SectionCard>
        <div className="list-grid">
          {store.savedTopologies.map((record) => (
            <article key={record.id} className={`list-card list-card--static ${store.activeTopologyId === record.id ? "list-card--active" : ""}`}>
              <strong>{record.name}</strong>
              <small>{formatTimestamp(record.updated_at)}</small>
              <div className="button-row">
                <button className="button button--secondary" type="button" onClick={() => store.loadSavedTopology(record.id)}>Load</button>
                <button className="button button--danger" type="button" onClick={() => store.deleteSavedTopology(record.id)}>Delete</button>
              </div>
            </article>
          ))}
        </div>
        <TopologyCanvas topology={store.topologyDraft} deployment={store.activeDeployment} change={store.activeChange} mode="draft" />
      </SectionCard>

      <SectionCard title="Topology Builder Guide" subtitle="Türkçe ve English rehber.">
        <div className="comparison-grid">
          <article className="list-card list-card--static">
            <strong>Türkçe</strong>
            <span>1. Project name alanına topology adını yaz.</span>
            <span>2. Router, switch ve endpoint ekledikten sonra üstte isimlerini değiştir.</span>
            <span>3. Link Builder bölümünden source ve target interface seçip bağlantı oluştur.</span>
            <span>3. Save Topology ile kaydet; yeni topology Overview ve Project List’te görünür.</span>
            <span>4. Load ile tekrar aç, Delete ile kaldır.</span>
            <span>5. Clear Draft boş topology başlatır; Reset Default örnek yapıyı geri getirir.</span>
          </article>
          <article className="list-card list-card--static">
            <strong>English</strong>
            <span>1. Enter the topology name in the project field.</span>
            <span>2. After adding routers, switches, and endpoints, rename them in the hostname fields.</span>
            <span>3. Use the Link Builder to connect source and target interfaces.</span>
            <span>4. Save Topology to persist it; the new topology appears in Overview and Project List.</span>
            <span>5. Clear Draft starts a blank topology; Reset Default restores the sample design.</span>
          </article>
        </div>
      </SectionCard>

      <SectionCard title="Validation-safe Draft JSON" subtitle="The UI edits a vendor-neutral topology specification that can be sent directly to the backend.">
        <JsonPanel value={store.topologyDraft} />
      </SectionCard>

      <SectionCard
        title="Natural Language Topology"
        subtitle="Sprint 16 converts natural-language requirements into a validated TopologySpec preview."
        actions={<button className="button" onClick={() => interpretTopologyMutation.mutate(prompt)}>Interpret Requirement</button>}
      >
        <div className="button-row">
          {examplePrompts.map((item, index) => (
            <button key={`${item}-${index}`} className="button button--secondary" type="button" onClick={() => setPrompt(item)}>
              Example Prompt {index + 1}
            </button>
          ))}
        </div>
        <label className="field">
          <span>Requirement prompt</span>
          <textarea
            className="textarea"
            value={prompt}
            placeholder={promptPlaceholder}
            onChange={(event) => setPrompt(event.target.value)}
          />
        </label>
        <div className="comparison-grid">
          {promptTemplates.map((template, index) => (
            <article key={`${template}-${index}`} className="list-card list-card--static">
              <strong>{index < 3 ? `English Template ${index + 1}` : `Turkce Sablon ${index - 2}`}</strong>
              <span>{template}</span>
              <div className="button-row">
                <button className="button button--secondary" type="button" onClick={() => setPrompt(template)}>
                  Use Template
                </button>
              </div>
            </article>
          ))}
        </div>
        {interpretedSummary ? (
          <article className="list-card list-card--static">
            <strong>{interpretedSummary.title}</strong>
            {interpretedSummary.lines.map((line) => <span key={line}>{line}</span>)}
          </article>
        ) : null}
        {interpretTopologyMutation.data ? (
          <div className="comparison-grid">
            <article className="list-card list-card--static">
              <strong>Interpret result</strong>
              {(interpretTopologyMutation.data.interpretation.warnings.length > 0
                ? interpretTopologyMutation.data.interpretation.warnings
                : ["No warnings returned."]
              ).map((warning) => <span key={warning}>{warning}</span>)}
            </article>
            <article className="list-card list-card--static">
              <strong>Clarifications</strong>
              {(interpretTopologyMutation.data.interpretation.clarifications.length > 0
                ? interpretTopologyMutation.data.interpretation.clarifications.map((item) => `${item.field}: ${item.question}`)
                : ["No clarification needed."]
              ).map((item) => <span key={item}>{item}</span>)}
            </article>
          </div>
        ) : null}
        {interpretTopologyMutation.data?.interpretation.topology ? (
          <SectionCard
            title="AI Topology Preview"
            subtitle="The interpreted topology has already been applied to the draft builder above."
          >
            <TopologyCanvas topology={store.topologyDraft} mode="draft" />
          </SectionCard>
        ) : null}
        {interpretTopologyMutation.data ? <JsonPanel value={interpretTopologyMutation.data.interpretation} /> : <EmptyState title="No AI interpretation yet" description="Submit a topology prompt to see the structured preview, clarifications, warnings, and interpretation notes." />}
      </SectionCard>
    </div>
  );
}

export function AddressingPageV2() {
  const store = useWorkflowStore();
  const [request, setRequest] = useState<AddressingRequest>(store.addressRequest);
  const createPlanMutation = useMutation({
    mutationFn: (payload: AddressingRequest) => workflowClient.createIpPlan(payload),
    onSuccess: (plan) => {
      store.setAddressRequest(request);
      store.setAddressPlan(plan);
      store.setTopologyDraft(applyAddressPlanToTopology(store.topologyDraft, plan));
    },
  });

  useEffect(() => {
    if (request.segments.length === 0) {
      setRequest({
        ...request,
        segments: [
          ...store.topologyDraft.vlans.map((vlan) => ({
            name: vlan.name,
            host_count: Math.max(store.topologyDraft.endpoints.filter((endpoint) => endpoint.vlan_id === vlan.vlan_id).length + 10, 10),
          })),
        ],
      });
    }
  }, [request, store.topologyDraft.endpoints, store.topologyDraft.vlans]);

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

  const addSegment = () => {
    setRequest({
      ...request,
      segments: [
        ...request.segments,
        {
          name: `SEGMENT-${request.segments.length + 1}`,
          host_count: 10,
        },
      ],
    });
  };

  const removeSegment = (index: number) => {
    setRequest({
      ...request,
      segments: request.segments.filter((_, segmentIndex) => segmentIndex !== index),
    });
  };

  const updateTopologyFromSegment = (index: number, field: "name" | "subnet" | "gateway", value: string) => {
    const entry = ensureSegmentTopologyEntry(store.topologyDraft, request.segments[index]?.name ?? `SEGMENT-${index + 1}`, index);
    const vlan = entry.vlan;
    const subnet = entry.subnet;
    const existingBinding = segmentBindingFromTopology(store.topologyDraft, request.segments[index]?.name ?? `SEGMENT-${index + 1}`, index);
    if (!existingBinding.vlan && existingBinding.subnet) {
      const oldSubnet = existingBinding.subnet;
      const nextSubnets = store.topologyDraft.subnets.map((item, subnetIndex) => (
        item.id === oldSubnet.id || subnetIndex === index
          ? {
            ...item,
            ...(field === "name" ? { name: `${value} subnet` } : {}),
            ...(field === "subnet" ? { network: value } : {}),
            ...(field === "gateway" ? { gateway: value } : {}),
          }
          : item
      ));
      const prefixLength = (field === "subnet" ? value : oldSubnet.network).split("/")[1] ?? "24";
      const nextDevices = store.topologyDraft.devices.map((device) => device.type === "router"
        ? {
          ...device,
          interfaces: device.interfaces.map((iface) => {
            const currentIp = iface.ipv4_address;
            if (!currentIp) {
              return iface;
            }
            const currentAddress = currentIp.split("/")[0];
            const subnetGateway = oldSubnet.gateway ?? "";
            if (field === "gateway" && currentAddress === subnetGateway) {
              return { ...iface, ipv4_address: `${value}/${prefixLength}` };
            }
            if (field === "subnet" && oldSubnet.gateway && currentAddress === oldSubnet.gateway) {
              return { ...iface, ipv4_address: `${oldSubnet.gateway}/${prefixLength}` };
            }
            return iface;
          }),
        }
        : device);
      store.setTopologyDraft(synchronizeTopologyAssignments({
        ...store.topologyDraft,
        subnets: nextSubnets,
        devices: nextDevices,
        endpoints: store.topologyDraft.endpoints.map((endpoint) => endpoint.subnet_id === oldSubnet.id
          ? {
            ...endpoint,
            ...(field === "gateway" ? { default_gateway: value } : {}),
          }
          : endpoint),
      }));
      return;
    }
    const nextVlans = store.topologyDraft.vlans.slice();
    nextVlans[index] = nextVlans[index]
      ? {
        ...nextVlans[index],
        ...(field === "name" ? { name: value } : {}),
        ...(field === "subnet" ? { subnet: value } : {}),
        ...(field === "gateway" ? { gateway: value } : {}),
      }
      : {
        ...vlan,
        ...(field === "name" ? { name: value } : {}),
        ...(field === "subnet" ? { subnet: value } : {}),
        ...(field === "gateway" ? { gateway: value } : {}),
      };
    const subnetExists = store.topologyDraft.subnets.some((item) => item.vlan_id === vlan.vlan_id);
    const nextSubnets = subnetExists
      ? store.topologyDraft.subnets.map((item) => item.vlan_id === vlan.vlan_id ? {
        ...item,
        ...(field === "name" ? { name: `${value} subnet` } : {}),
        ...(field === "subnet" ? { network: value } : {}),
        ...(field === "gateway" ? { gateway: value } : {}),
      } : item)
      : [
        ...store.topologyDraft.subnets,
        {
          ...subnet,
          ...(field === "name" ? { name: `${value} subnet` } : {}),
          ...(field === "subnet" ? { network: value } : {}),
          ...(field === "gateway" ? { gateway: value } : {}),
        },
      ];
    store.setTopologyDraft(synchronizeTopologyAssignments({
      ...store.topologyDraft,
      vlans: nextVlans,
      subnets: nextSubnets,
      devices: store.topologyDraft.devices.map((device) => device.type === "router" ? {
        ...device,
        interfaces: device.interfaces.map((iface) => iface.name.endsWith(`.${vlan.vlan_id}`) && field === "gateway"
          ? { ...iface, ipv4_address: `${value}/${(nextVlans[index]?.subnet ?? "192.168.1.0/24").split("/")[1] ?? "24"}` }
          : iface),
      } : device),
      endpoints: store.topologyDraft.endpoints.map((endpoint) => endpoint.vlan_id === vlan.vlan_id ? {
        ...endpoint,
        subnet_id: nextSubnets.find((item) => item.vlan_id === vlan.vlan_id)?.id ?? endpoint.subnet_id,
        ...(field === "gateway" ? { default_gateway: value } : {}),
      } : endpoint),
    }));
  };

  const updateEndpoint = (endpointId: string, field: "ip_address" | "default_gateway", value: string) => {
    store.setTopologyDraft(synchronizeTopologyAssignments({
      ...store.topologyDraft,
      endpoints: store.topologyDraft.endpoints.map((endpoint) => endpoint.id === endpointId ? { ...endpoint, [field]: value } : endpoint),
    }));
  };

  const previewPlan: AddressingPlan = {
    base_network: request.base_network,
    reserved_networks: [],
    report: "Manual or generated IP plan currently applied in the UI.",
    allocations: request.segments.map((segment, index) => {
      const binding = segmentBindingFromTopology(store.topologyDraft, segment.name, index);
      const linkedVlan = binding.vlan;
      const linkedSubnet = binding.subnet;
      const linkedEndpoints = binding.endpoints;
      return {
        name: segment.name,
        network: linkedVlan?.subnet ?? linkedSubnet?.network ?? segment.fixed_subnet ?? "",
        gateway: linkedVlan?.gateway ?? linkedSubnet?.gateway ?? "",
        usable_host_count: segment.host_count,
        allocated_addresses: Object.fromEntries(linkedEndpoints.map((endpoint) => [endpoint.hostname, endpoint.ip_address])),
      };
    }),
  };

  const applyManualPlan = () => {
    const appliedPlan: AddressingPlan = {
      base_network: request.base_network,
      reserved_networks: [],
      report: "Manual IP plan applied from the UI.",
      allocations: previewPlan.allocations,
    };
    store.setAddressRequest(request);
    store.setAddressPlan(appliedPlan);
    store.saveTopology(store.topologyDraft.project.name);
  };

  const addressingInsights = buildAddressingInsights(store.topologyDraft, request, store.addressPlan);

  return (
    <div className="page-grid">
      <SectionCard
        title="IP Address Plan"
        subtitle="Plan the IP ranges for the topology you created in Topology Builder."
      >
        <div className="button-row ip-plan-actions">
          <button className="button" onClick={() => createPlanMutation.mutate(request)}>Generate Address Plan</button>
          <button className="button button--secondary" onClick={applyManualPlan}>Apply Manual IP Plan</button>
          <button className="button button--secondary" onClick={addSegment}>Add Segment</button>
        </div>
        <div className="ip-plan-layout">
          <div className="ip-plan-sidebar">
            <article className="list-card list-card--static">
              <strong>Türkçe rehber</strong>
              <span>1. Base network alanını gir.</span>
              <span>2. Segment host sayılarını düzenleyip Generate Address Plan ile otomatik plan oluştur.</span>
              <span>3. İstersen segment ekle veya sil; topology’ye göre segmentleri elle yönet.</span>
              <span>4. Segment subnet/gateway ve endpoint IP alanlarını elle değiştir.</span>
              <span>5. Apply Manual IP Plan ile output’u ve configuration akışını güncelle.</span>
            </article>
            <article className="list-card list-card--static">
              <strong>English guide</strong>
              <span>1. Enter the base network.</span>
              <span>2. Edit host counts and use Generate Address Plan for automatic planning.</span>
              <span>3. Add or remove segments based on the topology you built.</span>
              <span>4. Manually edit the segment subnet/gateway and endpoint IP fields below.</span>
              <span>5. Use Apply Manual IP Plan to update the output and configuration flow.</span>
            </article>
          </div>
          <div className="ip-plan-main">
            <label className="field ip-plan-field ip-plan-field--base">
              <span>Base network</span>
              <input value={request.base_network} onChange={(event) => setRequest({ ...request, base_network: event.target.value })} />
            </label>
            {request.segments.map((segment, index) => (
              <div className="segment-row" key={`${segment.name}-${index}`}>
                <label className="field ip-plan-field">
                  <span>Segment</span>
                  <input value={segment.name} onChange={(event) => updateSegment(index, "name", event.target.value)} />
                </label>
                <label className="field">
                  <span>Hosts</span>
                  <input type="number" value={segment.host_count} onChange={(event) => updateSegment(index, "host_count", event.target.value)} />
                </label>
                <button className="button button--danger" type="button" onClick={() => removeSegment(index)}>Remove</button>
              </div>
            ))}
          </div>
        </div>
      </SectionCard>

      <SectionCard title="Planner Validation and Interpretation" subtitle="Bilingual warnings explain why a base network or host value may not fit the topology.">
        <div className="comparison-grid">
          {addressingInsights.map((insight, index) => (
            <article key={`${insight.titleEn}-${index}`} className="list-card list-card--static">
              <StatusPill value={insight.tone.toUpperCase()} tone={insight.tone} />
              <strong>{insight.titleTr}</strong>
              {insight.detailsTr.map((detail) => <span key={detail}>{detail}</span>)}
              <small>{insight.titleEn}</small>
              {insight.detailsEn.map((detail) => <small key={detail}>{detail}</small>)}
            </article>
          ))}
        </div>
      </SectionCard>

      <SectionCard title="Manual Segment and Endpoint Mapping" subtitle="These values are tied to the topology project and feed the next configuration render.">
        <div className="stack">
          {request.segments.map((segment, index) => {
            const binding = segmentBindingFromTopology(store.topologyDraft, segment.name, index);
            const linkedVlan = binding.vlan;
            const linkedSubnet = binding.subnet;
            const linkedEndpoints = binding.endpoints;
            return (
            <article key={`${segment.name}-${index}`} className="list-card list-card--static">
              <strong>{segment.name}</strong>
              <div className="manual-segment-grid">
                <label className="field ip-plan-field">
                  <span>Segment name</span>
                  <input value={segment.name} onChange={(event) => {
                    updateSegment(index, "name", event.target.value);
                    updateTopologyFromSegment(index, "name", event.target.value);
                  }} />
                </label>
                <label className="field ip-plan-field">
                  <span>Subnet</span>
                  <input value={linkedVlan?.subnet ?? linkedSubnet?.network ?? ""} onChange={(event) => updateTopologyFromSegment(index, "subnet", event.target.value)} />
                </label>
                <label className="field ip-plan-field">
                  <span>Gateway</span>
                  <input value={linkedVlan?.gateway ?? linkedSubnet?.gateway ?? ""} onChange={(event) => updateTopologyFromSegment(index, "gateway", event.target.value)} />
                </label>
              </div>
              {linkedEndpoints.map((endpoint) => (
                <div key={endpoint.id} className="manual-endpoint-row">
                  <label className="field ip-plan-field">
                    <span>{endpoint.hostname} IP</span>
                    <input value={endpoint.ip_address} onChange={(event) => updateEndpoint(endpoint.id, "ip_address", event.target.value)} />
                  </label>
                  <label className="field ip-plan-field">
                    <span>{endpoint.hostname} Gateway</span>
                    <input value={endpoint.default_gateway ?? ""} onChange={(event) => updateEndpoint(endpoint.id, "default_gateway", event.target.value)} />
                  </label>
                </div>
              ))}
            </article>
          );})}
        </div>
      </SectionCard>

      <SectionCard title="Generated / Applied Address Output" subtitle="The latest automatic or manual plan appears here.">
        <JsonPanel value={store.addressPlan ?? previewPlan} />
      </SectionCard>
    </div>
  );
}

export function ConfigurationPageV2() {
  const store = useWorkflowStore();
  const activeDeployment = store.activeDeployment;
  const deploymentIsSynced = topologyEquals(activeDeployment?.topology ?? null, store.topologyDraft);
  const generateConfigurationMutation = useMutation({
    mutationFn: async () => {
      if (!activeDeployment || !deploymentIsSynced) {
        const deployment = await workflowClient.createDeployment(store.topologyDraft.project.name, store.topologyDraft);
        store.upsertDeployment(deployment);
        await workflowClient.configureDeployment(deployment.id);
        return workflowClient.getDeployment(deployment.id);
      }
      await workflowClient.configureDeployment(activeDeployment.id);
      return workflowClient.getDeployment(activeDeployment.id);
    },
    onSuccess: (deployment) => {
      store.upsertDeployment(deployment);
    },
  });
  const configurationReady = Boolean(activeDeployment?.configuration_preview?.rendered_configurations?.length);

  return (
    <div className="page-grid">
      <SectionCard
        title="Configuration Preview"
        subtitle="Configurations are rendered from the current topology draft and the latest IP plan."
        actions={<button className="button" onClick={() => generateConfigurationMutation.mutate()}>Generate Configurations</button>}
      >
        <div className="guide-grid">
          <article className="list-card list-card--static">
            <strong>Turkce aciklama</strong>
            <span>Bu sayfa topology ve IP plan bilgisinden uretilen router, switch ve endpoint konfigürasyonlarini gosterir.</span>
            <span>`Generate Configurations` gerekiyorsa once deployment kaydi olusturur, sonra backend'den guncel konfigürasyon onizlemesini ceker.</span>
          </article>
          <article className="list-card list-card--static">
            <strong>English guide</strong>
            <span>This page shows the generated router, switch, and endpoint configurations derived from the topology and IP plan.</span>
            <span>`Generate Configurations` creates or refreshes the deployment as needed, then fetches the latest preview from the backend.</span>
          </article>
        </div>
        <div className="metric-grid">
          <MetricTile label="Configuration state" value={configurationReady ? "Configured" : generateConfigurationMutation.isPending ? "Generating" : "Not generated"} tone={configurationReady ? "success" : "default"} />
          <MetricTile label="Project sync" value={deploymentIsSynced ? "Synced" : "Draft changed"} tone={deploymentIsSynced ? "success" : "accent"} />
          <MetricTile label="Rendered devices" value={activeDeployment?.configuration_preview?.rendered_configurations?.length ?? 0} tone="accent" />
        </div>
        {generateConfigurationMutation.error ? (
          <article className="list-card list-card--static">
            <strong>Configuration error</strong>
            <span>{mutationErrorMessage(generateConfigurationMutation.error)}</span>
          </article>
        ) : null}
        {!activeDeployment ? <p className="inline-note">No backend project is selected yet. Generate Configurations will create one from the current draft automatically.</p> : null}
        {activeDeployment && !deploymentIsSynced ? <p className="inline-note">The current draft changed after the last project sync. Generate Configurations will refresh the backend project with the new topology and IP plan.</p> : null}
        {!activeDeployment || !activeDeployment.configuration_preview ? (
          <EmptyState title="No configuration preview yet" description="Use Generate Configurations to sync the current topology draft and render updated device configs." />
        ) : (
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
