import { useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";

import { API_BASE, apiRequest, authenticatedBlob, getAccessToken, isAuthUnavailable, jsonFetcher } from "../lib/fetcher";
import type {
  AgentEnrollment,
  AgentInstallCommandResponse,
  AgentTargetOS,
  AlertRule,
  AlertSummary,
  BaselinePolicy,
  CollectorStatus,
  DashboardHistory,
  DashboardSummary,
  FleetMonitoringResponse,
  HardwareOverviewResponse,
  LiveEvent,
  NodeDetailResponse,
  NotificationEndpoint,
  RunDetailResponse,
  ScheduleRecord,
  ServerRecord,
  TerminalSession,
  TerminalSessionSummary,
  TaskRun,
  WorkflowRun
} from "../types";

const WS_BASE = API_BASE.replace(/^http/i, "ws");
const MAX_EVENTS = 12;

const EMPTY_DASHBOARD: DashboardSummary = {
  fleet_online: 0,
  fleet_total: 0,
  active_runs: 0,
  alerts: 0,
  average_score: 0,
  servers: [],
  recent_runs: [],
  workflows: [],
  latest_metrics: [],
  recent_alerts: [],
  group_inventory: [],
  allowed_tasks: [],
  workflow_templates: []
};

function ensureArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function normalizeDashboard(payload: DashboardSummary | undefined): DashboardSummary {
  if (!payload) {
    return EMPTY_DASHBOARD;
  }

  return {
    ...EMPTY_DASHBOARD,
    ...payload,
    servers: ensureArray<ServerRecord>(payload.servers).map((server) => normalizeServer(server)),
    recent_runs: ensureArray(payload.recent_runs),
    workflows: ensureArray(payload.workflows),
    latest_metrics: ensureArray(payload.latest_metrics),
    recent_alerts: ensureArray(payload.recent_alerts),
    group_inventory: ensureArray(payload.group_inventory),
    allowed_tasks: ensureArray(payload.allowed_tasks),
    workflow_templates: ensureArray(payload.workflow_templates)
  };
}

function normalizeRunDetail(payload: RunDetailResponse): RunDetailResponse {
  return {
    ...payload,
    advisories: ensureArray(payload.advisories),
    artifacts: ensureArray(payload.artifacts),
    timeline: ensureArray(payload.timeline),
    server: payload.server ? normalizeServer(payload.server) : null,
    run: {
      ...payload.run,
      logs: ensureArray(payload.run?.logs),
      result: payload.run?.result ?? {},
    },
  };
}

function normalizeServer(server: ServerRecord): ServerRecord {
  return {
    ...server,
    platform_label: server.platform_label ?? null,
    platform_family: server.platform_family ?? null,
    primary_ip: server.primary_ip ?? null,
    bmc_address: server.bmc_address ?? null,
    last_heartbeat_at: server.last_heartbeat_at ?? null,
    last_metric_at: server.last_metric_at ?? null,
    last_telemetry_at: server.last_telemetry_at ?? null,
    last_inventory_refresh_at: server.last_inventory_refresh_at ?? null,
    last_task_poll_at: server.last_task_poll_at ?? null,
    last_task_result_at: server.last_task_result_at ?? null,
    last_task_activity_at: server.last_task_activity_at ?? null,
  };
}

function normalizeNodeDetail(payload: NodeDetailResponse): NodeDetailResponse {
  return {
    ...payload,
    server: normalizeServer(payload.server),
    recent_runs: ensureArray(payload.recent_runs),
    alerts: ensureArray(payload.alerts),
    advisories: ensureArray(payload.advisories),
    hardware_inventory: ensureArray(payload.hardware_inventory),
    collector_statuses: ensureArray<CollectorStatus>(payload.collector_statuses),
    hardware_overview: payload.hardware_overview ?? {},
    system_identity: {
      os: payload.system_identity?.os ?? null,
      platform: payload.system_identity?.platform ?? null,
      hostname: payload.system_identity?.hostname ?? null,
      architecture: payload.system_identity?.architecture ?? null,
      kernel: payload.system_identity?.kernel ?? null,
      build: payload.system_identity?.build ?? null,
      vendor: payload.system_identity?.vendor ?? null,
      model: payload.system_identity?.model ?? null,
      serial: payload.system_identity?.serial ?? null,
      board: payload.system_identity?.board ?? null,
      board_vendor: payload.system_identity?.board_vendor ?? null,
      board_serial: payload.system_identity?.board_serial ?? null,
      metadata: payload.system_identity?.metadata ?? {},
    },
    firmware_identity: {
      bios_vendor: payload.firmware_identity?.bios_vendor ?? null,
      bios_version: payload.firmware_identity?.bios_version ?? null,
      bios_release_date: payload.firmware_identity?.bios_release_date ?? null,
      board_firmware_version: payload.firmware_identity?.board_firmware_version ?? null,
      metadata: payload.firmware_identity?.metadata ?? {},
    },
    bmc_identity: {
      present: payload.bmc_identity?.present ?? false,
      vendor: payload.bmc_identity?.vendor ?? null,
      model: payload.bmc_identity?.model ?? null,
      firmware_version: payload.bmc_identity?.firmware_version ?? null,
      address: payload.bmc_identity?.address ?? null,
      source: payload.bmc_identity?.source ?? null,
      metadata: payload.bmc_identity?.metadata ?? {},
    },
    agent_identity: {
      version: payload.agent_identity?.version ?? null,
      runtime: payload.agent_identity?.runtime ?? null,
      executable: payload.agent_identity?.executable ?? null,
      platform: payload.agent_identity?.platform ?? null,
      metadata: payload.agent_identity?.metadata ?? {},
    },
    network_identity: {
      primary_ip: payload.network_identity?.primary_ip ?? null,
      primary_mac: payload.network_identity?.primary_mac ?? null,
      gateway: payload.network_identity?.gateway ?? null,
      dns_servers: ensureArray(payload.network_identity?.dns_servers),
      hostname: payload.network_identity?.hostname ?? null,
      fqdn: payload.network_identity?.fqdn ?? null,
      interfaces: ensureArray<Record<string, unknown>>(payload.network_identity?.interfaces).map((item) => ({
        name: typeof item.name === "string" ? item.name : "interface",
        ipv4_addresses: ensureArray<string>(item.ipv4_addresses),
        ipv6_addresses: ensureArray<string>(item.ipv6_addresses),
        mac_address: typeof item.mac_address === "string" ? item.mac_address : null,
        link_state: typeof item.link_state === "string" ? item.link_state : null,
        speed_mbps: typeof item.speed_mbps === "number" ? item.speed_mbps : null,
        mtu: typeof item.mtu === "number" ? item.mtu : null,
        gateway: typeof item.gateway === "string" ? item.gateway : null,
        dns_servers: ensureArray<string>(item.dns_servers),
        counters: typeof item.counters === "object" && item.counters ? (item.counters as Record<string, unknown>) : {},
        metadata: typeof item.metadata === "object" && item.metadata ? (item.metadata as Record<string, unknown>) : {},
      })),
      metadata: payload.network_identity?.metadata ?? {},
    },
    software_inventory: {
      os_edition: payload.software_inventory?.os_edition ?? null,
      os_build: payload.software_inventory?.os_build ?? null,
      kernel_version: payload.software_inventory?.kernel_version ?? null,
      python_version: payload.software_inventory?.python_version ?? null,
      runtime: payload.software_inventory?.runtime ?? null,
      driver_versions: payload.software_inventory?.driver_versions ?? {},
      metadata: payload.software_inventory?.metadata ?? {},
    },
    platform_addresses: ensureArray(payload.platform_addresses),
  };
}

function normalizeHardwareOverview(payload: HardwareOverviewResponse): HardwareOverviewResponse {
  return {
    ...payload,
    server: normalizeServer(payload.server),
    hot_components: ensureArray(payload.hot_components),
    failing_components: ensureArray(payload.failing_components),
    stale_collectors: ensureArray(payload.stale_collectors),
    collector_statuses: ensureArray(payload.collector_statuses),
    component_health: payload.component_health ?? {},
    last_telemetry_at: payload.last_telemetry_at ?? null,
    last_inventory_refresh_at: payload.last_inventory_refresh_at ?? null,
  };
}

function normalizeFleetMonitoring(payload: FleetMonitoringResponse | undefined): FleetMonitoringResponse {
  if (!payload) {
    return {
      generated_at: new Date().toISOString(),
      fleet_online: 0,
      fleet_total: 0,
      active_alerts: 0,
      reporting_servers: 0,
      hot_components: [],
      failing_components: [],
      collector_issues: [],
      cards: [],
      component_summaries: [],
      histories: [],
    };
  }
  return {
    ...payload,
    hot_components: ensureArray(payload.hot_components),
    failing_components: ensureArray(payload.failing_components),
    collector_issues: ensureArray(payload.collector_issues),
    cards: ensureArray<FleetMonitoringResponse["cards"][number]>(payload.cards).map((card) => ({
      ...card,
      server: normalizeServer(card.server),
      latest_metric: card.latest_metric
        ? {
            ...card.latest_metric,
            fan_speed_rpm: card.latest_metric.fan_speed_rpm ?? null,
          }
        : null,
      fan_speed_rpm: card.fan_speed_rpm ?? null,
      component_counts: card.component_counts ?? {},
    })),
    component_summaries: ensureArray<FleetMonitoringResponse["component_summaries"][number]>(payload.component_summaries),
    histories: ensureArray<FleetMonitoringResponse["histories"][number]>(payload.histories).map((series) => ({
      ...series,
      points: ensureArray(series.points),
    })),
  };
}

function latestDashboardTimestamp(payload: DashboardSummary) {
  const candidates = [
    ...payload.latest_metrics.map((metric) => metric.timestamp),
    ...payload.recent_runs.map((run) => run.updated_at),
    ...payload.workflows.map((workflow) => workflow.updated_at),
    ...payload.recent_alerts.map((alert) => alert.updated_at).filter((value): value is string => Boolean(value))
  ]
    .map((value) => new Date(value).getTime())
    .filter((value) => Number.isFinite(value));

  if (!candidates.length) {
    return null;
  }

  return new Date(Math.max(...candidates)).toISOString();
}

type ConnectionState = "loading" | "live" | "offline";

type TaskDispatchPayload = {
  server_id: string;
  task: string;
  requested_by?: string;
  params?: Record<string, unknown>;
};

type WorkflowDispatchPayload = {
  server_id: string;
  workflow: string;
  requested_by?: string;
  params?: Record<string, unknown>;
};

function upsertEvent(history: LiveEvent[], incoming: LiveEvent) {
  const key = `${incoming.event_type}-${incoming.timestamp}-${JSON.stringify(incoming.payload)}`;
  const deduped = history.filter((event) => `${event.event_type}-${event.timestamp}-${JSON.stringify(event.payload)}` !== key);
  return [incoming, ...deduped].slice(0, MAX_EVENTS);
}

export function useDashboardHistory(period: "Week" | "Month" | "Year") {
  const periodKey = period.toLowerCase();
  const { data, error, isLoading } = useSWR<DashboardHistory>(`${API_BASE}/api/v1/dashboard/history?period=${periodKey}`, jsonFetcher, {
    revalidateOnFocus: false,
    dedupingInterval: 15_000,
  });

  return {
    history: data ?? { period: periodKey, points: [] },
    historyError: error,
    historyLoading: isLoading,
  };
}

export function usePrometheusData() {
  const { data, error, isLoading, mutate } = useSWR<DashboardSummary>(`${API_BASE}/api/v1/dashboard/summary`, jsonFetcher, {
    refreshInterval: 15_000,
    revalidateOnFocus: true
  });
  const { data: alertsData, mutate: mutateAlerts } = useSWR<AlertSummary[]>(`${API_BASE}/api/v1/control/alerts`, (url: string) => apiRequest<AlertSummary[]>(url));
  const { data: rulesData, mutate: mutateRules } = useSWR<AlertRule[]>(`${API_BASE}/api/v1/control/alert-rules`, (url: string) => apiRequest<AlertRule[]>(url));
  const { data: baselinesData, mutate: mutateBaselines } = useSWR<BaselinePolicy[]>(`${API_BASE}/api/v1/control/baselines`, (url: string) =>
    apiRequest<BaselinePolicy[]>(url)
  );
  const { data: schedulesData, mutate: mutateSchedules } = useSWR<ScheduleRecord[]>(`${API_BASE}/api/v1/control/schedules`, (url: string) =>
    apiRequest<ScheduleRecord[]>(url)
  );
  const { data: notificationsData, mutate: mutateNotifications } = useSWR<NotificationEndpoint[]>(
    `${API_BASE}/api/v1/control/notifications`,
    (url: string) => apiRequest<NotificationEndpoint[]>(url)
  );
  const { data: enrollmentsData, mutate: mutateEnrollments } = useSWR<AgentEnrollment[]>(
    `${API_BASE}/api/v1/control/agent-enrollments`,
    (url: string) => apiRequest<AgentEnrollment[]>(url)
  );
  const { data: monitoringData, mutate: mutateMonitoring } = useSWR<FleetMonitoringResponse>(
    `${API_BASE}/api/v1/control/monitoring/fleet`,
    (url: string) => apiRequest<FleetMonitoringResponse>(url),
    { refreshInterval: 15_000, revalidateOnFocus: true }
  );

  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [connection, setConnection] = useState<ConnectionState>("loading");
  const [lastUpdated, setLastUpdated] = useState(() => new Date().toISOString());
  const [actionPending, setActionPending] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<number | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const manualCloseRef = useRef(false);

  useEffect(() => {
    let cancelled = false;

    function clearReconnectTimer() {
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    }

    function scheduleReconnect() {
      if (cancelled) {
        return;
      }
      clearReconnectTimer();
      reconnectAttemptRef.current += 1;
      const delay = Math.min(15_000, 1_000 * 2 ** Math.min(reconnectAttemptRef.current, 4));
      reconnectTimerRef.current = window.setTimeout(() => {
        connect();
      }, delay);
    }

    function connect() {
      if (cancelled) {
        return;
      }
      if (isAuthUnavailable()) {
        setConnection("offline");
        return;
      }

      try {
        manualCloseRef.current = false;
        const socket = new WebSocket(`${WS_BASE}/ws/live`);
        socketRef.current = socket;

        socket.onopen = () => {
          if (socketRef.current !== socket) {
            return;
          }
          reconnectAttemptRef.current = 0;
          setConnection("live");
        };

        socket.onmessage = (event) => {
          if (socketRef.current !== socket) {
            return;
          }
          try {
            const message = JSON.parse(event.data) as LiveEvent;
            setEvents((current) => upsertEvent(current, message));
            setLastUpdated(message.timestamp ?? new Date().toISOString());
          } catch {
            // Ignore malformed frames from the local dev stream.
          }
          void mutate();
          void mutateMonitoring();
          void mutateEnrollments();
        };

        socket.onerror = () => {
          if (socketRef.current !== socket || manualCloseRef.current || cancelled) {
            return;
          }
      setConnection("offline");
        };

        socket.onclose = () => {
          if (socketRef.current === socket) {
            socketRef.current = null;
          }
          if (manualCloseRef.current || cancelled) {
            return;
          }
          if (!cancelled) {
      setConnection("offline");
            scheduleReconnect();
          }
        };
      } catch {
      setConnection("offline");
        scheduleReconnect();
      }
    }

    connect();

    return () => {
      cancelled = true;
      clearReconnectTimer();
      manualCloseRef.current = true;
      const socket = socketRef.current;
      if (socket) {
        socketRef.current = null;
        if (socket.readyState === WebSocket.CONNECTING) {
          socket.onopen = () => {
            socket.close();
          };
          socket.onmessage = null;
          socket.onerror = null;
          socket.onclose = null;
        } else {
          socket.close();
        }
      }
      socketRef.current = null;
    };
  }, [mutate, mutateEnrollments, mutateMonitoring]);

  useEffect(() => {
    if (data) {
      setLastUpdated(latestDashboardTimestamp(data) ?? new Date().toISOString());
    }
  }, [data]);

  useEffect(() => {
    if (!actionSuccess) {
      return;
    }
    const timer = window.setTimeout(() => setActionSuccess(null), 4000);
    return () => window.clearTimeout(timer);
  }, [actionSuccess]);

  const dashboard = useMemo(() => normalizeDashboard(data), [data]);
  const fleetMonitoring = useMemo(() => normalizeFleetMonitoring(monitoringData), [monitoringData]);

  async function triggerTask(payload: TaskDispatchPayload): Promise<TaskRun> {
    setActionPending(true);
    setActionError(null);
    setActionSuccess(null);
    try {
      const run = await apiRequest<TaskRun>(`${API_BASE}/api/v1/control/tasks/dispatch`, {
        method: "POST",
        body: JSON.stringify({
          server_id: payload.server_id,
          task: payload.task,
          requested_by: payload.requested_by ?? "web-ui",
          params: payload.params ?? {}
        })
      });
      setActionSuccess(`Task queued: ${run.task_id}`);
      await mutate();
      await mutateSchedules();
      return run;
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "Unable to dispatch task.";
      setActionError(message);
      throw requestError;
    } finally {
      setActionPending(false);
    }
  }

  async function triggerWorkflow(payload: WorkflowDispatchPayload): Promise<WorkflowRun> {
    setActionPending(true);
    setActionError(null);
    setActionSuccess(null);
    try {
      const workflow = await apiRequest<WorkflowRun>(`${API_BASE}/api/v1/control/workflows/dispatch`, {
        method: "POST",
        body: JSON.stringify({
          server_id: payload.server_id,
          workflow: payload.workflow,
          requested_by: payload.requested_by ?? "web-ui",
          params: payload.params ?? {}
        })
      });
      setActionSuccess(`Workflow queued: ${workflow.workflow_id}`);
      await mutate();
      await mutateSchedules();
      return workflow;
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "Unable to dispatch workflow.";
      setActionError(message);
      throw requestError;
    } finally {
      setActionPending(false);
    }
  }

  async function fetchRunDetail(taskId: string) {
    const payload = await apiRequest<RunDetailResponse>(`${API_BASE}/api/v1/control/runs/${taskId}`);
    return normalizeRunDetail(payload);
  }

  async function fetchNodeDetail(serverId: string) {
    const payload = await apiRequest<NodeDetailResponse>(`${API_BASE}/api/v1/control/nodes/${serverId}`);
    return normalizeNodeDetail(payload);
  }

  async function fetchHardwareOverview(serverId: string) {
    const payload = await apiRequest<HardwareOverviewResponse>(`${API_BASE}/api/v1/control/nodes/${serverId}/hardware`);
    return normalizeHardwareOverview(payload);
  }

  async function createSchedule(payload: {
    name: string;
    server_id: string;
    workflow: string;
    interval_minutes: number;
    params?: Record<string, unknown>;
    created_by?: string;
  }) {
    setActionPending(true);
    setActionError(null);
    setActionSuccess(null);
    try {
      const schedule = await apiRequest<ScheduleRecord>(`${API_BASE}/api/v1/control/schedules`, {
        method: "POST",
        body: JSON.stringify({ ...payload, created_by: payload.created_by ?? "web-ui", params: payload.params ?? {} })
      });
      setActionSuccess(`Schedule created: ${schedule.name}`);
      await mutateSchedules();
      return schedule;
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "Unable to create schedule.";
      setActionError(message);
      throw requestError;
    } finally {
      setActionPending(false);
    }
  }

  async function createNotificationEndpoint(payload: { name: string; channel: "email" | "webhook"; target: string }) {
    setActionPending(true);
    setActionError(null);
    setActionSuccess(null);
    try {
      const endpoint = await apiRequest<NotificationEndpoint>(`${API_BASE}/api/v1/control/notifications`, {
        method: "POST",
        body: JSON.stringify({ ...payload, enabled: true })
      });
      setActionSuccess(`Notification endpoint added: ${endpoint.name}`);
      await mutateNotifications();
      return endpoint;
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "Unable to add notification endpoint.";
      setActionError(message);
      throw requestError;
    } finally {
      setActionPending(false);
    }
  }

  async function createBaseline(payload: {
    name: string;
    group: string;
    task: string;
    minimum_score: number;
    max_temperature_c?: number | null;
    min_throughput?: number | null;
  }) {
    setActionPending(true);
    setActionError(null);
    setActionSuccess(null);
    try {
      const baseline = await apiRequest<BaselinePolicy>(`${API_BASE}/api/v1/control/baselines`, {
        method: "POST",
        body: JSON.stringify(payload)
      });
      setActionSuccess(`Baseline created: ${baseline.name}`);
      await mutateBaselines();
      return baseline;
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "Unable to create baseline.";
      setActionError(message);
      throw requestError;
    } finally {
      setActionPending(false);
    }
  }

  async function exportBenchmarks() {
    return apiRequest<{ export_type: string; average_score: number; group_inventory: Array<Record<string, unknown>> }>(
      `${API_BASE}/api/v1/control/exports/benchmarks`
    );
  }

  async function updateAlertState(alertId: string, state: "open" | "acknowledged" | "resolved") {
    const alert = await apiRequest<AlertSummary>(`${API_BASE}/api/v1/control/alerts/${alertId}`, {
      method: "PATCH",
      body: JSON.stringify({ state })
    });
    await mutateAlerts();
    await mutate();
    return alert;
  }

  async function downloadRunArtifact(taskId: string, artifactId: string, filenameHint: string) {
    setActionError(null);
    try {
      const blob = await authenticatedBlob(`${API_BASE}/api/v1/control/runs/${taskId}/artifacts/${artifactId}`);
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      const safe = (filenameHint || "artifact").replace(/[^\w.-]+/g, "_").slice(0, 120);
      anchor.download = safe;
      anchor.click();
      URL.revokeObjectURL(objectUrl);
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "Artifact download failed.";
      setActionError(message);
    }
  }

  async function retryRun(taskId: string) {
    setActionPending(true);
    setActionError(null);
    setActionSuccess(null);
    try {
      const run = await apiRequest<TaskRun>(`${API_BASE}/api/v1/control/runs/${taskId}/retry`, { method: "POST" });
      setActionSuccess(`Run requeued: ${run.task_id}`);
      await mutate();
      await mutateSchedules();
      return run;
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "Unable to retry run.";
      setActionError(message);
      throw requestError;
    } finally {
      setActionPending(false);
    }
  }

  async function cancelRun(taskId: string) {
    setActionPending(true);
    setActionError(null);
    setActionSuccess(null);
    try {
      const run = await apiRequest<TaskRun>(`${API_BASE}/api/v1/control/runs/${taskId}/cancel`, { method: "POST" });
      setActionSuccess(`Run updated: ${run.task_id}`);
      await mutate();
      await mutateSchedules();
      await mutateAlerts();
      return run;
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "Unable to cancel run.";
      setActionError(message);
      throw requestError;
    } finally {
      setActionPending(false);
    }
  }

  async function cancelWorkflow(workflowId: string) {
    setActionPending(true);
    setActionError(null);
    setActionSuccess(null);
    try {
      const workflow = await apiRequest<WorkflowRun>(`${API_BASE}/api/v1/control/workflows/${workflowId}/cancel`, {
        method: "POST"
      });
      setActionSuccess(`Workflow cancelled: ${workflow.workflow_id}`);
      await mutate();
      await mutateSchedules();
      return workflow;
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "Unable to cancel workflow.";
      setActionError(message);
      throw requestError;
    } finally {
      setActionPending(false);
    }
  }

  async function createAlertRule(payload: {
    name: string;
    signal: string;
    threshold: number;
    severity?: "info" | "warning" | "critical";
    enabled?: boolean;
  }) {
    setActionPending(true);
    setActionError(null);
    setActionSuccess(null);
    try {
      const rule = await apiRequest<AlertRule>(`${API_BASE}/api/v1/control/alert-rules`, {
        method: "POST",
        body: JSON.stringify({
          name: payload.name,
          signal: payload.signal,
          threshold: payload.threshold,
          severity: payload.severity ?? "warning",
          enabled: payload.enabled ?? true
        })
      });
      setActionSuccess(`Alert rule created: ${rule.name}`);
      await mutateRules();
      return rule;
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "Unable to create alert rule.";
      setActionError(message);
      throw requestError;
    } finally {
      setActionPending(false);
    }
  }

  async function createAgentEnrollment(payload: {
    display_name: string;
    group: string;
    tags?: string[];
    capabilities?: string[];
    target_os: AgentTargetOS;
  }) {
    setActionPending(true);
    setActionError(null);
    setActionSuccess(null);
    try {
      const enrollment = await apiRequest<AgentEnrollment>(`${API_BASE}/api/v1/control/agent-enrollments`, {
        method: "POST",
        body: JSON.stringify({
          display_name: payload.display_name,
          group: payload.group,
          tags: payload.tags ?? [],
          capabilities: payload.capabilities ?? [],
          target_os: payload.target_os,
        }),
      });
      setActionSuccess(`Connection created: ${enrollment.connection_code}`);
      await mutateEnrollments();
      return enrollment;
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "Unable to create agent enrollment.";
      setActionError(message);
      throw requestError;
    } finally {
      setActionPending(false);
    }
  }

  async function revokeAgentEnrollment(enrollmentId: string) {
    setActionPending(true);
    setActionError(null);
    setActionSuccess(null);
    try {
      const enrollment = await apiRequest<AgentEnrollment>(`${API_BASE}/api/v1/control/agent-enrollments/${enrollmentId}/revoke`, {
        method: "POST",
      });
      setActionSuccess(`Connection revoked: ${enrollment.display_name}`);
      await mutateEnrollments();
      return enrollment;
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "Unable to revoke agent enrollment.";
      setActionError(message);
      throw requestError;
    } finally {
      setActionPending(false);
    }
  }

  async function fetchAgentInstallCommand(enrollmentId: string, targetOs: AgentTargetOS) {
    return apiRequest<AgentInstallCommandResponse>(
      `${API_BASE}/api/v1/control/agent-enrollments/${enrollmentId}/install-command?target_os=${targetOs}`
    );
  }

  async function openTerminalSession(serverId: string, cols = 120, rows = 32) {
    return apiRequest<TerminalSession>(`${API_BASE}/api/v1/control/terminal/sessions`, {
      method: "POST",
      body: JSON.stringify({ server_id: serverId, cols, rows }),
    });
  }

  async function fetchTerminalSession(sessionId: string) {
    return apiRequest<TerminalSession>(`${API_BASE}/api/v1/control/terminal/sessions/${sessionId}`);
  }

  async function closeTerminalSession(sessionId: string) {
    return apiRequest<TerminalSession>(`${API_BASE}/api/v1/control/terminal/sessions/${sessionId}/close`, {
      method: "POST",
    });
  }

  async function sendTerminalInput(sessionId: string, data: string) {
    return apiRequest<TerminalSession>(`${API_BASE}/api/v1/control/terminal/sessions/${sessionId}/input`, {
      method: "POST",
      body: JSON.stringify({ data }),
    });
  }

  async function resizeTerminalSession(sessionId: string, cols: number, rows: number) {
    return apiRequest<TerminalSession>(`${API_BASE}/api/v1/control/terminal/sessions/${sessionId}/resize`, {
      method: "POST",
      body: JSON.stringify({ cols, rows }),
    });
  }

  async function listTerminalSessions(serverId?: string) {
    const search = serverId ? `?server_id=${encodeURIComponent(serverId)}` : "";
    return apiRequest<TerminalSessionSummary[]>(`${API_BASE}/api/v1/control/terminal/sessions${search}`);
  }

  async function terminalWebSocketUrl(sessionId: string) {
    const token = await getAccessToken();
    return `${WS_BASE}/ws/terminal/${sessionId}?token=${encodeURIComponent(token)}`;
  }

  return useMemo(
    () => ({
      dashboard,
      fleetMonitoring,
      alerts: alertsData ? ensureArray<AlertSummary>(alertsData) : dashboard.recent_alerts,
      alertRules: ensureArray<AlertRule>(rulesData),
      baselines: ensureArray<BaselinePolicy>(baselinesData),
      schedules: ensureArray<ScheduleRecord>(schedulesData),
      notificationEndpoints: ensureArray<NotificationEndpoint>(notificationsData),
      agentEnrollments: ensureArray<AgentEnrollment>(enrollmentsData),
      events,
      connection,
      lastUpdated,
      isLoading,
      error: error instanceof Error ? error.message : null,
      actionPending,
      actionError,
      actionSuccess,
      triggerTask,
      triggerWorkflow,
      fetchRunDetail,
      fetchNodeDetail,
      fetchHardwareOverview,
      createSchedule,
      createNotificationEndpoint,
      createBaseline,
      exportBenchmarks,
      updateAlertState,
      downloadRunArtifact,
      retryRun,
      cancelRun,
      cancelWorkflow,
      createAlertRule,
      createAgentEnrollment,
      revokeAgentEnrollment,
      fetchAgentInstallCommand,
      openTerminalSession,
      fetchTerminalSession,
      closeTerminalSession,
      sendTerminalInput,
      resizeTerminalSession,
      listTerminalSessions,
      terminalWebSocketUrl,
      refresh: async () => {
        await mutate();
        await mutateMonitoring();
      }
    }),
    [
      alertsData,
      baselinesData,
      rulesData,
      schedulesData,
      notificationsData,
      enrollmentsData,
      actionError,
      actionPending,
      actionSuccess,
      connection,
      dashboard,
      fleetMonitoring,
      error,
      events,
      isLoading,
      lastUpdated,
      mutate,
      mutateMonitoring,
      mutateRules
    ]
  );
}
