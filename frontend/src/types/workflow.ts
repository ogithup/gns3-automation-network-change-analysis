export type DeviceType = "router" | "switch" | "endpoint";

export type InterfaceSpec = {
  name: string;
  enabled?: boolean;
  access_vlan?: number;
  trunk_vlans?: number[];
  ipv4_address?: string;
};

export type DeviceSpec = {
  id: string;
  hostname: string;
  type: DeviceType;
  platform: string;
  site_id?: string;
  interfaces: InterfaceSpec[];
};

export type LinkSpec = {
  source_device: string;
  source_interface: string;
  target_device: string;
  target_interface: string;
};

export type VlanSpec = {
  vlan_id: number;
  name: string;
  subnet?: string;
  gateway?: string;
  endpoint_ids?: string[];
};

export type SubnetSpec = {
  id: string;
  name: string;
  network: string;
  gateway?: string;
  vlan_id?: number;
};

export type EndpointSpec = {
  id: string;
  device_id: string;
  hostname: string;
  ip_address: string;
  vlan_id?: number;
  subnet_id?: string;
  default_gateway?: string;
};

export type RouteSpec = {
  id: string;
  device_id: string;
  destination: string;
  next_hop?: string;
  outgoing_interface?: string;
  protocol: string;
};

export type RoutingProtocolSpec = {
  id: string;
  device_id: string;
  protocol: string;
  process_id?: string;
  area?: string;
};

export type AclRuleSpec = {
  id: string;
  action: string;
  protocol: string;
  source: string;
  destination: string;
};

export type AclSpec = {
  id: string;
  name: string;
  type: string;
  device_id: string;
  rules: AclRuleSpec[];
};

export type ServiceSpec = {
  id: string;
  name: string;
  kind: string;
  critical?: boolean;
  vlan_id?: number;
  subnet_id?: string;
};

export type ConnectivityRequirement = {
  id: string;
  source_endpoint_id: string;
  target_endpoint_id: string;
  protocol: string;
  expected: string;
};

export type ValidationTestSpec = {
  id: string;
  name: string;
  test_type: string;
  source_endpoint_id: string;
  target_endpoint_id: string;
  expected_success: boolean;
};

export type TopologySpec = {
  project: {
    name: string;
    description?: string;
  };
  sites: Array<{ id: string; name: string }>;
  devices: DeviceSpec[];
  links: LinkSpec[];
  vlans: VlanSpec[];
  subnets: SubnetSpec[];
  endpoints: EndpointSpec[];
  routes: RouteSpec[];
  routing_protocols: RoutingProtocolSpec[];
  acls: AclSpec[];
  services: ServiceSpec[];
  connectivity_requirements: ConnectivityRequirement[];
  validation_tests: ValidationTestSpec[];
  dhcp_pools?: Array<Record<string, unknown>>;
};

export type SavedTopologyRecord = {
  id: string;
  name: string;
  topology: TopologySpec;
  updated_at: string;
};

export type Gns3Version = {
  version: string;
  local: boolean;
};

export type Gns3ConnectivityResponse = {
  reachable: boolean;
  version: Gns3Version | null;
  detail: string;
};

export type SpecificationValidateResponse = {
  valid: boolean;
  project_name: string;
  device_count: number;
  vlan_count: number;
};

export type Gns3NodePlan = {
  domain_device_id: string;
  hostname: string;
  platform: string;
  template_name: string;
  position: {
    x: number;
    y: number;
  };
};

export type Gns3LinkPlan = {
  source_device_id: string;
  source_interface: string;
  target_device_id: string;
  target_interface: string;
  source_adapter_number: number;
  source_port_number: number;
  target_adapter_number: number;
  target_port_number: number;
};

export type Gns3DeploymentPlan = {
  project_name: string;
  node_requests: Gns3NodePlan[];
  link_requests: Gns3LinkPlan[];
  start_order: string[];
};

export type RenderedConfiguration = {
  device_id: string;
  device_hostname: string;
  platform: string;
  content: string;
  content_hash: string;
};

export type ConfigurationPreview = {
  project_name: string;
  rendered_configurations: RenderedConfiguration[];
};

export type DiscoveredInterface = {
  name: string;
  ip_address?: string | null;
  status: string;
  protocol: string;
};

export type DiscoveredVlan = {
  vlan_id: number;
  name: string;
  status: string;
  interfaces: string[];
};

export type DiscoveredTrunk = {
  interface_name: string;
  allowed_vlans: number[];
};

export type DiscoveredRoute = {
  code: string;
  network: string;
  next_hop?: string | null;
  outgoing_interface?: string | null;
};

export type DiscoveredAcl = {
  name: string;
  acl_type: string;
  entries: string[];
};

export type DiscoveredOspfNeighbor = {
  neighbor_id: string;
  address: string;
  state: string;
  interface_name: string;
};

export type Gns3ConsoleInfo = {
  node_id: string;
  console_host: string;
  console: number;
  console_type: string;
};

export type DiscoveredDeviceState = {
  device_id: string;
  hostname: string;
  platform: string;
  console: Gns3ConsoleInfo;
  running_config?: string;
  interfaces: DiscoveredInterface[];
  vlans: DiscoveredVlan[];
  trunk_vlans: DiscoveredTrunk[];
  routes: DiscoveredRoute[];
  acls: DiscoveredAcl[];
  ospf_neighbors: DiscoveredOspfNeighbor[];
  raw_outputs?: Record<string, string>;
};

export type DeviceStateSnapshot = {
  device_id: string;
  discovered_state: DiscoveredDeviceState;
};

export type DiscoveredNetworkState = {
  project_id: string;
  project_name: string;
  device_snapshots: DeviceStateSnapshot[];
};

export type ValidationResult = {
  predicted_reachable: boolean;
  actual_reachable?: boolean | null;
  failure_stage?: string | null;
  path?: string[] | null;
  evaluated_routes?: Array<Record<string, unknown>> | null;
  evaluated_acls?: Array<Record<string, unknown>> | null;
  state?: string | null;
  technical_explanation?: string | null;
  suspected_reason?: string | null;
  runtime?: Record<string, unknown> | null;
};

export type SimulationImpact = {
  affected_devices: string[];
  affected_interfaces: string[];
  affected_vlans: string[];
  affected_subnets: string[];
  affected_endpoints: string[];
  affected_services: string[];
  lost_reachability_paths: string[][];
  changed_validation_tests: string[];
  redundancy_available?: boolean | null;
};

export type ChangeSimulationResult = {
  snapshot: {
    name: string;
    topology_yaml: string;
  };
  command_type: string;
  command_summary: string;
  direct_impacts: string[];
  indirect_impacts: string[];
  before_results: ValidationResult[];
  after_results: ValidationResult[];
  impact: SimulationImpact;
};

export type RiskFactorScore = {
  factor: string;
  weight: number;
  raw_value: string | number | boolean;
  normalized_score: number;
  contribution: number;
  explanation: string;
};

export type RiskAssessment = {
  total_score: number;
  risk_level: string;
  recommendation: string;
  suggested_maintenance_requirement: string;
  suggested_rollback_readiness: string;
  explanation: string[];
  factor_scores: RiskFactorScore[];
  direct_impacts: string[];
  indirect_impacts: string[];
};

export type ApprovalRecord = {
  reviewer: string;
  approved: boolean;
  note?: string | null;
};

export type RootCauseFinding = {
  suspected_root_cause: string;
  confidence_score: number;
  osi_layer: string;
  supporting_evidence: string[];
  commands_evaluated: string[];
  failed_checks: string[];
  recommended_remediation: string;
  rollback_recommendation: string;
};

export type RootCauseAnalysisResult = {
  source_endpoint_id: string;
  target_endpoint_id: string;
  findings: RootCauseFinding[];
};

export type DeploymentRecordResponse = {
  id: string;
  project_name: string;
  status: string;
  correlation_id?: string | null;
  topology?: TopologySpec | null;
  dry_run_plan?: Gns3DeploymentPlan | null;
  configuration_preview?: ConfigurationPreview | null;
  discovered_state?: DiscoveredNetworkState | null;
  validations: ValidationResult[];
};

export type ChangeRecordResponse = {
  id: string;
  deployment_id: string;
  status: string;
  command_type: string;
  summary: string;
  correlation_id?: string | null;
  simulation?: ChangeSimulationResult | null;
  risk?: RiskAssessment | null;
  approval?: ApprovalRecord | null;
  root_causes: RootCauseAnalysisResult[];
};

export type ReportResponse = {
  id: string;
  deployment_id?: string | null;
  change_id?: string | null;
  validations: ValidationResult[];
  root_causes: RootCauseAnalysisResult[];
};

export type GeneratedReport = {
  id: string;
  title: string;
  created_at: string;
  html_content: string;
  pdf_base64: string;
  summary: string;
  sections: Array<{
    title: string;
    summary: string;
    data: Record<string, unknown>;
  }>;
};

export type AddressingSegmentRequest = {
  name: string;
  host_count: number;
  fixed_subnet?: string;
};

export type AddressingRequest = {
  base_network: string;
  segments: AddressingSegmentRequest[];
  reserved_networks?: string[];
  point_to_point_links?: number;
};

export type AddressingAllocation = {
  name: string;
  network: string;
  gateway: string;
  usable_host_count: number;
  allocated_addresses: Record<string, string>;
};

export type AddressingPlan = {
  base_network: string;
  allocations: AddressingAllocation[];
  reserved_networks: string[];
  report: string;
};

export type WorkflowProgressEvent = {
  status: string;
  timestamp?: string;
};

export type ChangeCommandPayload = Record<string, string | number | boolean | null | undefined>;

export type ClarificationItem = {
  field: string;
  question: string;
  reason: string;
  options: string[];
};

export type SafetyFinding = {
  source: string;
  pattern: string;
  detail: string;
  severity: string;
};

export type InterpretedTopologyPlan = {
  topology?: TopologySpec | null;
  clarifications: ClarificationItem[];
  warnings: string[];
  safety_findings: SafetyFinding[];
  blocked: boolean;
  preview: Record<string, unknown>;
};

export type InterpretedChangePlan = {
  command?: ChangeCommandPayload | null;
  summary?: string | null;
  clarifications: ClarificationItem[];
  warnings: string[];
  safety_findings: SafetyFinding[];
  blocked: boolean;
  preview: Record<string, unknown>;
};

export type DeterministicExplanation = {
  summary: string;
  bullets: string[];
  warnings: string[];
  next_actions: string[];
};
