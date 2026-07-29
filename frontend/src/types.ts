export type ServerStatus = "online" | "offline";
export type RunStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type HealthStatus = "PASS" | "WARNING" | "FAIL";
export type AgentTargetOS = "windows" | "linux";
export type AgentEnrollmentStatus = "pending" | "claimed" | "expired" | "revoked";
export type TerminalSessionStatus = "open" | "disconnected" | "closed" | "unsupported";
export type TerminalFrameKind = "opened" | "output" | "resized" | "closed" | "error" | "status";

export interface AllowedTask {
  name: string;
  summary: string;
  default_timeout_seconds: number;
  sample_params: Record<string, unknown>;
}

export interface WorkflowTemplate {
  name: string;
  summary: string;
  steps: string[];
}

export interface ServerRecord {
  server_id: string;
  server_name: string;
  group: string;
  status: ServerStatus;
  tags: string[];
  capabilities: string[];
  command_capabilities?: Record<string, unknown>;
  health: HealthStatus;
  platform_label?: string | null;
  platform_family?: string | null;
  created_at: string;
  last_seen: string;
  last_heartbeat_at: string | null;
  last_metric_at: string | null;
  last_telemetry_at: string | null;
  last_inventory_refresh_at: string | null;
  last_task_poll_at: string | null;
  last_task_result_at: string | null;
  last_task_activity_at: string | null;
  primary_ip?: string | null;
  bmc_address?: string | null;
}

export interface MetricSnapshot {
  server_id: string;
  cpu: number;
  memory: number;
  disk: number;
  network_mbps: number;
  temperature_c: number | null;
  gpu_utilization: number | null;
  fan_speed_rpm?: number | null;
  timestamp: string;
}

export interface TaskRun {
  task_id: string;
  server_id: string;
  task: string;
  params: Record<string, unknown>;
  requested_by: string;
  status: RunStatus;
  workflow_id: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  attempt_count: number;
  worker_id: string | null;
  error_message: string | null;
  logs: string[];
  result: Record<string, unknown>;
  score: number | null;
}

export interface WorkflowRun {
  workflow_id: string;
  server_id: string;
  workflow: string;
  steps: string[];
  linked_task_ids: string[];
  status: RunStatus;
  current_step_index: number;
  requested_by: string;
  params: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
}

export interface AlertSummary {
  alert_id?: string;
  server_id: string;
  severity: string;
  signal: string;
  value: number | null;
  message?: string;
  state?: string;
  created_at?: string;
  updated_at?: string;
  rule_id?: string | null;
}

export interface AlertRule {
  rule_id: string;
  name: string;
  signal: string;
  threshold: number;
  severity: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface NotificationEndpoint {
  endpoint_id: string;
  name: string;
  channel: "email" | "webhook";
  target: string;
  enabled: boolean;
  created_at: string;
}

export interface ScheduleRecord {
  schedule_id: string;
  name: string;
  server_id: string;
  workflow: string;
  params: Record<string, unknown>;
  interval_minutes: number;
  active: boolean;
  next_run_at: string;
  last_run_at: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface AdvisoryInsight {
  title: string;
  severity: string;
  summary: string;
  recommendation: string;
}

export interface BaselinePolicy {
  baseline_id: string;
  name: string;
  group: string;
  task: string;
  minimum_score: number;
  max_temperature_c: number | null;
  min_throughput: number | null;
  created_at: string;
  updated_at: string;
}

export interface BaselineComparison {
  baseline: BaselinePolicy | null;
  matched: boolean;
  score_delta: number | null;
  checks: Record<string, unknown>;
}

export interface GroupInventorySummary {
  group: string;
  total_servers: number;
  online_servers: number;
  active_alerts: number;
  average_score: number;
  capabilities: string[];
}

export interface HistoryPoint {
  label: string;
  value: number;
  amount: number;
  total_runs: number;
  completed_runs: number;
}

export interface DashboardHistory {
  period: string;
  points: HistoryPoint[];
}

export interface TaskArtifact {
  artifact_id: string;
  task_id: string;
  label: string;
  artifact_type: string;
  content_type: string;
  size_bytes: number;
  metadata: Record<string, unknown>;
  created_at: string;
  download_path: string;
}

export interface TaskEvent {
  event_id: string;
  task_id: string;
  event_type: string;
  status: RunStatus | null;
  summary: string;
  details: Record<string, unknown>;
  created_at: string;
}

export interface CollectorCapability {
  state: string;
  supported: boolean;
  message: string | null;
  source: string | null;
}

export interface AgentEnrollment {
  enrollment_id: string;
  connection_code: string;
  display_name: string;
  group: string;
  tags: string[];
  capabilities: string[];
  target_os: AgentTargetOS;
  status: AgentEnrollmentStatus;
  expires_at: string;
  claimed_at: string | null;
  claimed_server_id: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface AgentInstallCommandResponse {
  enrollment: AgentEnrollment;
  target_os: AgentTargetOS;
  package_format: string;
  command: string;
  script_url: string;
  download_url: string;
  checksum_url: string;
  service_name: string;
}

export interface CollectorStatus {
  collector_name: string;
  status: string;
  capability: CollectorCapability;
  duration_ms: number | null;
  message: string | null;
  metrics_emitted: number;
  inventory_items_seen: number;
  recorded_at: string;
  details: Record<string, unknown>;
}

export interface HardwareComponent {
  component_id: string;
  server_id: string;
  component_type: string;
  name: string;
  slot_or_path: string | null;
  vendor: string | null;
  model: string | null;
  serial: string | null;
  firmware_version: string | null;
  status: string;
  health: HealthStatus;
  capabilities: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  last_seen_at: string;
}

export interface HardwareMetricPoint {
  component_id: string;
  metric_key: string;
  value: number | null;
  unit: string | null;
  status: string;
  labels: Record<string, unknown>;
  recorded_at: string;
}

export interface HardwareMetricSeries {
  component_id: string;
  metric_key: string;
  unit: string | null;
  points: HardwareMetricPoint[];
}

export interface SystemIdentity {
  os: string | null;
  platform: string | null;
  hostname: string | null;
  architecture: string | null;
  kernel: string | null;
  build: string | null;
  vendor: string | null;
  model: string | null;
  serial: string | null;
  board: string | null;
  board_vendor: string | null;
  board_serial: string | null;
  metadata: Record<string, unknown>;
}

export interface FirmwareIdentity {
  bios_vendor: string | null;
  bios_version: string | null;
  bios_release_date: string | null;
  board_firmware_version: string | null;
  metadata: Record<string, unknown>;
}

export interface BmcIdentity {
  present: boolean;
  vendor: string | null;
  model: string | null;
  firmware_version: string | null;
  address: string | null;
  source: string | null;
  metadata: Record<string, unknown>;
}

export interface AgentIdentity {
  version: string | null;
  runtime: string | null;
  executable: string | null;
  platform: string | null;
  metadata: Record<string, unknown>;
}

export interface NetworkInterfaceIdentity {
  name: string;
  ipv4_addresses: string[];
  ipv6_addresses: string[];
  mac_address: string | null;
  link_state: string | null;
  speed_mbps: number | null;
  mtu: number | null;
  gateway: string | null;
  dns_servers: string[];
  counters: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export interface NetworkIdentity {
  primary_ip: string | null;
  primary_mac: string | null;
  gateway: string | null;
  dns_servers: string[];
  hostname: string | null;
  fqdn: string | null;
  interfaces: NetworkInterfaceIdentity[];
  metadata: Record<string, unknown>;
}

export interface SoftwareInventory {
  os_edition: string | null;
  os_build: string | null;
  kernel_version: string | null;
  python_version: string | null;
  runtime: string | null;
  driver_versions: Record<string, string>;
  metadata: Record<string, unknown>;
}

export interface HardwareOverviewResponse {
  server: ServerRecord;
  overall_health: HealthStatus;
  component_health: Record<string, Record<string, unknown>>;
  hot_components: HardwareComponent[];
  failing_components: HardwareComponent[];
  stale_collectors: CollectorStatus[];
  collector_statuses: CollectorStatus[];
  last_telemetry_at: string | null;
  last_inventory_refresh_at: string | null;
}

export interface FleetMonitoringCard {
  server: ServerRecord;
  latest_metric: MetricSnapshot | null;
  overall_health: HealthStatus;
  hot_component_count: number;
  failing_component_count: number;
  collector_issue_count: number;
  fan_speed_rpm: number | null;
  component_counts: Record<string, number>;
}

export interface FleetComponentSummary {
  key: string;
  label: string;
  total_components: number;
  healthy_components: number;
  warning_components: number;
  failing_components: number;
  reporting_servers: number;
  unsupported_servers: number;
  average_value: number | null;
  unit: string | null;
}

export interface FleetMetricHistoryPoint {
  timestamp: string;
  label: string;
  average_value: number | null;
  max_value: number | null;
  reporting_components: number;
}

export interface FleetMetricHistorySeries {
  key: string;
  label: string;
  metric_key: string;
  unit: string | null;
  points: FleetMetricHistoryPoint[];
}

export interface FleetMonitoringResponse {
  generated_at: string;
  fleet_online: number;
  fleet_total: number;
  active_alerts: number;
  reporting_servers: number;
  hot_components: HardwareComponent[];
  failing_components: HardwareComponent[];
  collector_issues: CollectorStatus[];
  cards: FleetMonitoringCard[];
  component_summaries: FleetComponentSummary[];
  histories: FleetMetricHistorySeries[];
}

export interface DashboardSummary {
  fleet_online: number;
  fleet_total: number;
  active_runs: number;
  alerts: number;
  average_score: number;
  servers: ServerRecord[];
  recent_runs: TaskRun[];
  workflows: WorkflowRun[];
  latest_metrics: MetricSnapshot[];
  recent_alerts: AlertSummary[];
  group_inventory: GroupInventorySummary[];
  allowed_tasks: AllowedTask[];
  workflow_templates: WorkflowTemplate[];
}

export interface LiveEvent {
  event_type: string;
  payload: Record<string, unknown>;
  timestamp: string;
}

export interface TerminalFrame {
  kind: TerminalFrameKind;
  text: string | null;
  cols: number | null;
  rows: number | null;
  timestamp: string;
  meta: Record<string, unknown>;
}

export interface TerminalSession {
  session_id: string;
  server_id: string;
  opened_by: string;
  status: TerminalSessionStatus;
  shell_type: string | null;
  terminal_supported: boolean;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
  last_agent_seen_at: string | null;
  last_browser_seen_at: string | null;
  recent_output: TerminalFrame[];
  meta: Record<string, unknown>;
}

export interface TerminalSessionSummary {
  session_id: string;
  server_id: string;
  opened_by: string;
  status: TerminalSessionStatus;
  shell_type: string | null;
  terminal_supported: boolean;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
  last_agent_seen_at: string | null;
  last_browser_seen_at: string | null;
  meta: Record<string, unknown>;
}

export interface RunDetailResponse {
  run: TaskRun;
  server: ServerRecord | null;
  workflow: WorkflowRun | null;
  advisories: AdvisoryInsight[];
  regression: Record<string, unknown>;
  baseline_comparison: BaselineComparison;
  artifacts: TaskArtifact[];
  timeline: TaskEvent[];
}

export interface NodeDetailResponse {
  server: ServerRecord;
  latest_metric: MetricSnapshot | null;
  recent_runs: TaskRun[];
  alerts: AlertSummary[];
  advisories: AdvisoryInsight[];
  hardware_overview: Record<string, unknown>;
  hardware_inventory: HardwareComponent[];
  collector_statuses: CollectorStatus[];
  system_identity: SystemIdentity;
  firmware_identity: FirmwareIdentity;
  bmc_identity: BmcIdentity;
  agent_identity: AgentIdentity;
  network_identity: NetworkIdentity;
  software_inventory: SoftwareInventory;
  platform_addresses: string[];
}
