from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ServerStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class HealthStatus(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"


class UserRole(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class AgentTargetOS(str, Enum):
    WINDOWS = "windows"
    LINUX = "linux"


class AgentEnrollmentStatus(str, Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    EXPIRED = "expired"
    REVOKED = "revoked"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertState(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class NotificationChannel(str, Enum):
    EMAIL = "email"
    WEBHOOK = "webhook"


class TerminalSessionStatus(str, Enum):
    OPEN = "open"
    DISCONNECTED = "disconnected"
    CLOSED = "closed"
    UNSUPPORTED = "unsupported"


class TerminalFrameKind(str, Enum):
    OPENED = "opened"
    OUTPUT = "output"
    RESIZED = "resized"
    CLOSED = "closed"
    ERROR = "error"
    STATUS = "status"


class AllowedTask(BaseModel):
    name: str
    summary: str
    default_timeout_seconds: int
    sample_params: dict[str, Any] = Field(default_factory=dict)


class WorkflowTemplate(BaseModel):
    name: str
    summary: str
    steps: list[str]


class ServerRegistration(BaseModel):
    server_name: str
    server_id: str | None = None
    api_key: str | None = None
    group: str = "default"
    tags: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    command_capabilities: dict[str, Any] = Field(default_factory=dict)


class RegistrationResponse(BaseModel):
    server_id: str
    api_key: str
    heartbeat_interval_seconds: int


class ServerRecord(BaseModel):
    server_id: str
    server_name: str
    group: str
    status: ServerStatus = ServerStatus.ONLINE
    tags: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    command_capabilities: dict[str, Any] = Field(default_factory=dict)
    health: HealthStatus = HealthStatus.WARNING
    api_key: str
    created_at: datetime = Field(default_factory=utc_now)
    last_seen: datetime = Field(default_factory=utc_now)
    last_heartbeat_at: datetime | None = None
    last_metric_at: datetime | None = None
    last_task_poll_at: datetime | None = None
    last_task_result_at: datetime | None = None
    last_telemetry_at: datetime | None = None
    last_inventory_refresh_at: datetime | None = None
    last_task_activity_at: datetime | None = None
    platform_label: str | None = None
    platform_family: str | None = None
    primary_ip: str | None = None
    bmc_address: str | None = None


class ServerView(BaseModel):
    server_id: str
    server_name: str
    group: str
    status: ServerStatus = ServerStatus.ONLINE
    tags: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    command_capabilities: dict[str, Any] = Field(default_factory=dict)
    health: HealthStatus = HealthStatus.WARNING
    created_at: datetime = Field(default_factory=utc_now)
    last_seen: datetime = Field(default_factory=utc_now)
    last_heartbeat_at: datetime | None = None
    last_metric_at: datetime | None = None
    last_task_poll_at: datetime | None = None
    last_task_result_at: datetime | None = None
    last_telemetry_at: datetime | None = None
    last_inventory_refresh_at: datetime | None = None
    last_task_activity_at: datetime | None = None
    platform_label: str | None = None
    platform_family: str | None = None
    primary_ip: str | None = None
    bmc_address: str | None = None


class HeartbeatPayload(BaseModel):
    api_key: str
    status: ServerStatus = ServerStatus.ONLINE
    active_workflow_id: str | None = None
    running_tasks: list[str] = Field(default_factory=list)


class MetricPayload(BaseModel):
    cpu: float = Field(ge=0, le=100)
    memory: float = Field(ge=0, le=100)
    disk: float = Field(ge=0, le=100)
    network_mbps: float = Field(ge=0)
    temperature_c: float | None = None
    gpu_utilization: float | None = Field(default=None, ge=0, le=100)
    fan_speed_rpm: float | None = None
    timestamp: datetime = Field(default_factory=utc_now)


class MetricEnvelope(BaseModel):
    api_key: str
    metric: MetricPayload


class MetricSnapshot(BaseModel):
    server_id: str
    cpu: float
    memory: float
    disk: float
    network_mbps: float
    temperature_c: float | None = None
    gpu_utilization: float | None = None
    fan_speed_rpm: float | None = None
    timestamp: datetime = Field(default_factory=utc_now)


class CollectorCapability(BaseModel):
    state: str
    supported: bool = True
    message: str | None = None
    source: str | None = None


class CollectorStatus(BaseModel):
    collector_name: str
    status: str
    capability: CollectorCapability
    duration_ms: float | None = None
    message: str | None = None
    metrics_emitted: int = 0
    inventory_items_seen: int = 0
    recorded_at: datetime = Field(default_factory=utc_now)
    details: dict[str, Any] = Field(default_factory=dict)


class TerminalFrame(BaseModel):
    kind: TerminalFrameKind
    text: str | None = None
    cols: int | None = None
    rows: int | None = None
    timestamp: datetime = Field(default_factory=utc_now)
    meta: dict[str, Any] = Field(default_factory=dict)


class TerminalSession(BaseModel):
    session_id: str
    server_id: str
    opened_by: str
    status: TerminalSessionStatus = TerminalSessionStatus.OPEN
    shell_type: str | None = None
    terminal_supported: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    closed_at: datetime | None = None
    last_agent_seen_at: datetime | None = None
    last_browser_seen_at: datetime | None = None
    recent_output: list[TerminalFrame] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class TerminalSessionSummary(BaseModel):
    session_id: str
    server_id: str
    opened_by: str
    status: TerminalSessionStatus = TerminalSessionStatus.OPEN
    shell_type: str | None = None
    terminal_supported: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    closed_at: datetime | None = None
    last_agent_seen_at: datetime | None = None
    last_browser_seen_at: datetime | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class TerminalOpenRequest(BaseModel):
    server_id: str
    cols: int = Field(default=120, ge=40, le=240)
    rows: int = Field(default=32, ge=12, le=120)
    shell_preference: str | None = None


class TerminalInputRequest(BaseModel):
    data: str = Field(default="", max_length=16000)


class TerminalResizeRequest(BaseModel):
    cols: int = Field(ge=40, le=240)
    rows: int = Field(ge=12, le=120)


class TerminalAgentUpdate(BaseModel):
    session_id: str
    outputs: list[str] = Field(default_factory=list)
    shell_type: str | None = None
    closed: bool = False
    error_message: str | None = None


class TerminalAgentSyncRequest(BaseModel):
    api_key: str
    sessions: list[TerminalAgentUpdate] = Field(default_factory=list)


class TerminalAgentCommand(BaseModel):
    session_id: str
    action: str
    data: str | None = None
    cols: int | None = None
    rows: int | None = None
    shell_type: str | None = None


class TerminalAgentSyncResponse(BaseModel):
    commands: list[TerminalAgentCommand] = Field(default_factory=list)


class HardwareComponent(BaseModel):
    component_id: str
    server_id: str
    component_type: str
    name: str
    slot_or_path: str | None = None
    vendor: str | None = None
    model: str | None = None
    serial: str | None = None
    firmware_version: str | None = None
    status: str = "healthy"
    health: HealthStatus = HealthStatus.PASS
    capabilities: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime = Field(default_factory=utc_now)


class HardwareMetricPoint(BaseModel):
    component_id: str
    metric_key: str
    value: float | None = None
    unit: str | None = None
    status: str = "ok"
    labels: dict[str, Any] = Field(default_factory=dict)
    recorded_at: datetime = Field(default_factory=utc_now)


class HardwareMetricSeries(BaseModel):
    component_id: str
    metric_key: str
    unit: str | None = None
    points: list[HardwareMetricPoint] = Field(default_factory=list)


class HardwareCollectorReport(BaseModel):
    collector_name: str
    capability: CollectorCapability
    status: str
    duration_ms: float | None = None
    message: str | None = None
    inventory: list[dict[str, Any]] = Field(default_factory=list)
    telemetry: list[dict[str, Any]] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class HardwareReportPayload(BaseModel):
    api_key: str
    inventory: list[dict[str, Any]] = Field(default_factory=list)
    telemetry: list[dict[str, Any]] = Field(default_factory=list)
    collectors: list[HardwareCollectorReport] = Field(default_factory=list)
    summary_metrics: MetricPayload
    collected_at: datetime = Field(default_factory=utc_now)


class AgentAuthRequest(BaseModel):
    api_key: str


class AgentEnrollmentCreate(BaseModel):
    display_name: str
    group: str = "default"
    tags: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    target_os: AgentTargetOS
    created_by: str = "web-ui"


class AgentEnrollment(BaseModel):
    enrollment_id: str
    connection_code: str
    display_name: str
    group: str
    tags: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    target_os: AgentTargetOS
    status: AgentEnrollmentStatus
    expires_at: datetime
    claimed_at: datetime | None = None
    claimed_server_id: str | None = None
    created_by: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AgentEnrollmentClaimRequest(BaseModel):
    connection_code: str
    server_name: str | None = None
    tags: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)


class AgentEnrollmentClaimResponse(BaseModel):
    enrollment_id: str
    server_id: str
    api_key: str
    server_name: str
    group: str
    tags: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    claimed_at: datetime


class AgentReleaseArtifact(BaseModel):
    target_os: AgentTargetOS
    arch: str
    package_format: str = "native"
    available: bool = True
    filename: str | None = None
    download_url: str | None = None
    checksum_url: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    build_error: str | None = None


class AgentReleaseManifest(BaseModel):
    version: str
    published_at: datetime = Field(default_factory=utc_now)
    artifacts: list[AgentReleaseArtifact] = Field(default_factory=list)


class AgentInstallCommandResponse(BaseModel):
    enrollment: AgentEnrollment
    target_os: AgentTargetOS
    package_format: str = "native"
    command: str
    script_url: str
    download_url: str
    checksum_url: str
    service_name: str


class TaskDispatchRequest(BaseModel):
    server_id: str
    task: str
    params: dict[str, Any] = Field(default_factory=dict)
    requested_by: str = "system"


class WorkflowDispatchRequest(BaseModel):
    server_id: str
    workflow: str
    params: dict[str, Any] = Field(default_factory=dict)
    requested_by: str = "system"


class TaskAssignment(BaseModel):
    task_id: str
    task: str
    params: dict[str, Any] = Field(default_factory=dict)
    queued_at: datetime = Field(default_factory=utc_now)
    workflow_id: str | None = None
    attempt_count: int = 0
    worker_id: str | None = None


class TaskRun(BaseModel):
    task_id: str
    server_id: str
    task: str
    params: dict[str, Any] = Field(default_factory=dict)
    requested_by: str
    status: RunStatus = RunStatus.PENDING
    workflow_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    attempt_count: int = 0
    worker_id: str | None = None
    error_message: str | None = None
    logs: list[str] = Field(default_factory=list)
    result: dict[str, Any] = Field(default_factory=dict)
    score: float | None = None


class WorkflowRun(BaseModel):
    workflow_id: str
    server_id: str
    workflow: str
    steps: list[str]
    linked_task_ids: list[str] = Field(default_factory=list)
    status: RunStatus = RunStatus.PENDING
    current_step_index: int = 0
    requested_by: str = "system"
    params: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None


class TaskResult(BaseModel):
    api_key: str
    task_id: str
    status: RunStatus
    logs: list[str] = Field(default_factory=list)
    result: dict[str, Any] = Field(default_factory=dict)


class AuditEvent(BaseModel):
    event_id: str
    actor: str
    action: str
    resource: str
    timestamp: datetime = Field(default_factory=utc_now)
    details: dict[str, Any] = Field(default_factory=dict)


class LiveEvent(BaseModel):
    event_type: str
    payload: dict[str, Any]
    timestamp: datetime = Field(default_factory=utc_now)


class AlertRule(BaseModel):
    rule_id: str
    name: str
    signal: str
    threshold: float
    severity: AlertSeverity
    enabled: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AlertRuleCreate(BaseModel):
    name: str
    signal: str
    threshold: float
    severity: AlertSeverity = AlertSeverity.WARNING
    enabled: bool = True


class AlertRecord(BaseModel):
    alert_id: str
    server_id: str
    severity: AlertSeverity
    signal: str
    value: float | None = None
    message: str
    state: AlertState = AlertState.OPEN
    rule_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AlertStatusUpdate(BaseModel):
    state: AlertState


class NotificationEndpoint(BaseModel):
    endpoint_id: str
    name: str
    channel: NotificationChannel
    target: str
    enabled: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class NotificationEndpointCreate(BaseModel):
    name: str
    channel: NotificationChannel
    target: str
    enabled: bool = True


class ScheduleRecord(BaseModel):
    schedule_id: str
    name: str
    server_id: str
    workflow: str
    params: dict[str, Any] = Field(default_factory=dict)
    interval_minutes: int
    active: bool = True
    next_run_at: datetime
    last_run_at: datetime | None = None
    created_by: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ScheduleCreate(BaseModel):
    name: str
    server_id: str
    workflow: str
    params: dict[str, Any] = Field(default_factory=dict)
    interval_minutes: int = Field(ge=5, le=10080)
    active: bool = True
    created_by: str = "system"


class ScheduleUpdate(BaseModel):
    active: bool | None = None
    interval_minutes: int | None = Field(default=None, ge=5, le=10080)


class AdvisoryInsight(BaseModel):
    title: str
    severity: AlertSeverity
    summary: str
    recommendation: str


class BaselinePolicy(BaseModel):
    baseline_id: str
    name: str
    group: str
    task: str
    minimum_score: float
    max_temperature_c: float | None = None
    min_throughput: float | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class BaselinePolicyCreate(BaseModel):
    name: str
    group: str
    task: str
    minimum_score: float
    max_temperature_c: float | None = None
    min_throughput: float | None = None


class BaselineComparison(BaseModel):
    baseline: BaselinePolicy | None = None
    matched: bool = False
    score_delta: float | None = None
    checks: dict[str, Any] = Field(default_factory=dict)


class GroupInventorySummary(BaseModel):
    group: str
    total_servers: int
    online_servers: int
    active_alerts: int
    average_score: float
    capabilities: list[str] = Field(default_factory=list)


class HistoryPoint(BaseModel):
    label: str
    value: float
    amount: int
    total_runs: int
    completed_runs: int


class DashboardHistory(BaseModel):
    period: str
    points: list[HistoryPoint] = Field(default_factory=list)


class TaskArtifact(BaseModel):
    artifact_id: str
    task_id: str
    label: str
    artifact_type: str
    content_type: str
    size_bytes: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    download_path: str


class TaskEvent(BaseModel):
    event_id: str
    task_id: str
    event_type: str
    status: RunStatus | None = None
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class DashboardSummary(BaseModel):
    fleet_online: int
    fleet_total: int
    active_runs: int
    alerts: int
    average_score: float
    servers: list[ServerView]
    recent_runs: list[TaskRun]
    workflows: list[WorkflowRun]
    latest_metrics: list[MetricSnapshot]
    recent_alerts: list[AlertRecord] = Field(default_factory=list)
    group_inventory: list[GroupInventorySummary] = Field(default_factory=list)
    allowed_tasks: list[AllowedTask]
    workflow_templates: list[WorkflowTemplate]


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: UserRole
    expires_in_seconds: int


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class AuthenticatedUser(BaseModel):
    username: str
    role: UserRole


class MessageResponse(BaseModel):
    message: str


class UserRecord(BaseModel):
    user_id: str
    username: str
    role: UserRole
    active: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class UserCreate(BaseModel):
    username: str
    password: str
    role: UserRole = UserRole.VIEWER
    active: bool = True


class UserUpdate(BaseModel):
    role: UserRole | None = None
    active: bool | None = None
    password: str | None = Field(default=None, min_length=8)


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class NodeDetailResponse(BaseModel):
    server: ServerView
    latest_metric: MetricSnapshot | None = None
    recent_runs: list[TaskRun] = Field(default_factory=list)
    alerts: list[AlertRecord] = Field(default_factory=list)
    advisories: list[AdvisoryInsight] = Field(default_factory=list)
    hardware_overview: dict[str, Any] = Field(default_factory=dict)
    hardware_inventory: list[HardwareComponent] = Field(default_factory=list)
    collector_statuses: list[CollectorStatus] = Field(default_factory=list)
    system_identity: SystemIdentity = Field(default_factory=lambda: SystemIdentity())
    firmware_identity: FirmwareIdentity = Field(default_factory=lambda: FirmwareIdentity())
    bmc_identity: BmcIdentity = Field(default_factory=lambda: BmcIdentity())
    agent_identity: AgentIdentity = Field(default_factory=lambda: AgentIdentity())
    network_identity: NetworkIdentity = Field(default_factory=lambda: NetworkIdentity())
    software_inventory: SoftwareInventory = Field(default_factory=lambda: SoftwareInventory())
    platform_addresses: list[str] = Field(default_factory=list)


class HardwareInventoryResponse(BaseModel):
    server: ServerView
    components: list[HardwareComponent] = Field(default_factory=list)
    collector_statuses: list[CollectorStatus] = Field(default_factory=list)


class HardwareOverviewResponse(BaseModel):
    server: ServerView
    overall_health: HealthStatus = HealthStatus.WARNING
    component_health: dict[str, dict[str, Any]] = Field(default_factory=dict)
    hot_components: list[HardwareComponent] = Field(default_factory=list)
    failing_components: list[HardwareComponent] = Field(default_factory=list)
    stale_collectors: list[CollectorStatus] = Field(default_factory=list)
    collector_statuses: list[CollectorStatus] = Field(default_factory=list)
    last_telemetry_at: datetime | None = None
    last_inventory_refresh_at: datetime | None = None


class FleetMonitoringCard(BaseModel):
    server: ServerView
    latest_metric: MetricSnapshot | None = None
    overall_health: HealthStatus = HealthStatus.WARNING
    hot_component_count: int = 0
    failing_component_count: int = 0
    collector_issue_count: int = 0
    fan_speed_rpm: float | None = None
    component_counts: dict[str, int] = Field(default_factory=dict)


class FleetComponentSummary(BaseModel):
    key: str
    label: str
    total_components: int = 0
    healthy_components: int = 0
    warning_components: int = 0
    failing_components: int = 0
    reporting_servers: int = 0
    unsupported_servers: int = 0
    average_value: float | None = None
    unit: str | None = None


class FleetMetricHistoryPoint(BaseModel):
    timestamp: datetime = Field(default_factory=utc_now)
    label: str
    average_value: float | None = None
    max_value: float | None = None
    reporting_components: int = 0


class FleetMetricHistorySeries(BaseModel):
    key: str
    label: str
    metric_key: str
    unit: str | None = None
    points: list[FleetMetricHistoryPoint] = Field(default_factory=list)


class FleetMonitoringResponse(BaseModel):
    generated_at: datetime = Field(default_factory=utc_now)
    fleet_online: int = 0
    fleet_total: int = 0
    active_alerts: int = 0
    reporting_servers: int = 0
    hot_components: list[HardwareComponent] = Field(default_factory=list)
    failing_components: list[HardwareComponent] = Field(default_factory=list)
    collector_issues: list[CollectorStatus] = Field(default_factory=list)
    cards: list[FleetMonitoringCard] = Field(default_factory=list)
    component_summaries: list[FleetComponentSummary] = Field(default_factory=list)
    histories: list[FleetMetricHistorySeries] = Field(default_factory=list)


class SystemIdentity(BaseModel):
    os: str | None = None
    platform: str | None = None
    hostname: str | None = None
    architecture: str | None = None
    kernel: str | None = None
    build: str | None = None
    vendor: str | None = None
    model: str | None = None
    serial: str | None = None
    board: str | None = None
    board_vendor: str | None = None
    board_serial: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class FirmwareIdentity(BaseModel):
    bios_vendor: str | None = None
    bios_version: str | None = None
    bios_release_date: str | None = None
    board_firmware_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BmcIdentity(BaseModel):
    present: bool = False
    vendor: str | None = None
    model: str | None = None
    firmware_version: str | None = None
    address: str | None = None
    source: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentIdentity(BaseModel):
    version: str | None = None
    runtime: str | None = None
    executable: str | None = None
    platform: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NetworkInterfaceIdentity(BaseModel):
    name: str
    ipv4_addresses: list[str] = Field(default_factory=list)
    ipv6_addresses: list[str] = Field(default_factory=list)
    mac_address: str | None = None
    link_state: str | None = None
    speed_mbps: float | None = None
    mtu: int | None = None
    gateway: str | None = None
    dns_servers: list[str] = Field(default_factory=list)
    counters: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NetworkIdentity(BaseModel):
    primary_ip: str | None = None
    primary_mac: str | None = None
    gateway: str | None = None
    dns_servers: list[str] = Field(default_factory=list)
    hostname: str | None = None
    fqdn: str | None = None
    interfaces: list[NetworkInterfaceIdentity] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SoftwareInventory(BaseModel):
    os_edition: str | None = None
    os_build: str | None = None
    kernel_version: str | None = None
    python_version: str | None = None
    runtime: str | None = None
    driver_versions: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunDetailResponse(BaseModel):
    run: TaskRun
    server: ServerView | None = None
    workflow: WorkflowRun | None = None
    advisories: list[AdvisoryInsight] = Field(default_factory=list)
    regression: dict[str, Any] = Field(default_factory=dict)
    baseline_comparison: BaselineComparison = Field(default_factory=BaselineComparison)
    artifacts: list[TaskArtifact] = Field(default_factory=list)
    timeline: list[TaskEvent] = Field(default_factory=list)
