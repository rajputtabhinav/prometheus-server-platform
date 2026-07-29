import { type ReactNode, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import jsPDF from "jspdf";
import autoTable from "jspdf-autotable";

import { DragonCompanionOverlay } from "./components/DragonCompanionOverlay";
import { ComponentCoverageChart, FleetMetricHistoryChart, GroupScoreChart, InfrastructureHealthChart, ReadinessHistoryChart, ResourceUsageChart, RunStatusChart } from "./components/TelemetryCharts";
import { useDashboardHistory, usePrometheusData } from "./hooks/usePrometheusData";
import { PLATFORM_TIMEZONE, formatCalendarDate, formatDateTime, formatNow } from "./lib/datetime";
import type { AgentEnrollment, AgentInstallCommandResponse, AgentTargetOS, AlertSummary, FleetComponentSummary, FleetMonitoringResponse, HardwareComponent, NodeDetailResponse, RunDetailResponse, ScheduleRecord, ServerRecord, TaskRun, TerminalSession } from "./types";

const NAV_ITEMS = ["Dashboard", "Servers", "Analytics", "Settings"] as const;
const PERIODS = ["Week", "Month", "Year"] as const;

type NavItem = (typeof NAV_ITEMS)[number] | "Tracker" | "Runs" | "Workflows";
type Period = (typeof PERIODS)[number];
type RunFilter = "all" | "running" | "completed" | "failed";
type ServerWorkspaceSection = "overview" | "monitor" | "launch" | "terminal";

function nice(value: string) {
  return value.replace(/[._-]/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function percent(value: number) {
  return `${Math.round(value)}%`;
}

function toCurrency(value: number) {
  return `$${value.toLocaleString()}`;
}

function statusLabel(value: string) {
  if (value === "completed") return "Complete";
  if (value === "running") return "Running";
  if (value === "failed") return "Failed";
  if (value === "pending") return "Pending";
  if (value === "cancelled") return "Cancelled";
  return nice(value);
}

function connectionLabel(value: ReturnType<typeof usePrometheusData>["connection"]) {
  if (value === "live") return "Live";
  if (value === "loading") return "Syncing";
  return "Offline";
}

function statusClass(status: string) {
  if (["completed", "online", "PASS"].includes(status)) return "status-chip status-chip--good";
  if (["running", "pending", "WARNING"].includes(status)) return "status-chip status-chip--warn";
  return "status-chip status-chip--bad";
}

function kpiDelta(base: number, modifier: number) {
  const value = Math.max(3, Math.min(64, Math.round(base + modifier)));
  return `+${value}%`;
}

function pickPrimaryServer(servers: ServerRecord[], selectedServerId: string) {
  return servers.find((server) => server.server_id === selectedServerId) ?? servers[0] ?? null;
}

function topRuns(runs: TaskRun[]) {
  return [...runs].sort((left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime()).slice(0, 5);
}

function latestServerActivity(server: ServerRecord | null) {
  if (!server) return null;
  return (
    server.last_task_activity_at ??
    server.last_task_result_at ??
    server.last_task_poll_at ??
    server.last_telemetry_at ??
    server.last_metric_at ??
    server.last_inventory_refresh_at ??
    server.last_heartbeat_at ??
    server.last_seen
  );
}

function componentMetricValue(component: HardwareComponent, key: string) {
  const value = component.metadata[key];
  if (typeof value === "number") {
    return value;
  }
  return null;
}

function detailValue(value: unknown) {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value.toLocaleString() : "Not reported";
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  if (typeof value === "string") {
    return value.trim() ? value : "Not reported";
  }
  return "Not reported";
}

function compactStat(value: number | null | undefined, suffix = "%") {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "--";
  }
  return `${Math.round(value)}${suffix}`;
}

function summaryByKey(summaries: FleetComponentSummary[], key: string) {
  return summaries.find((summary) => summary.key === key) ?? null;
}

function historyByKey(histories: FleetMonitoringResponse["histories"], key: string) {
  return histories.find((series) => series.key === key) ?? null;
}

function downloadBlobFile(filename: string, blob: Blob) {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(objectUrl);
}

function trackerExportRows(nodeDetail: NodeDetailResponse, server: ServerRecord | null) {
  const rows: Array<[string, string]> = [
    ["Server name", server?.server_name ?? "Not reported"],
    ["Server ID", server?.server_id ?? "Not reported"],
    ["Group", server?.group ?? "Not reported"],
    ["Status", server?.status ?? "Not reported"],
    ["Health", server?.health ?? "Not reported"],
    ["Primary IP", nodeDetail.network_identity.primary_ip ?? server?.primary_ip ?? "Not reported"],
    ["BMC/IPMI address", nodeDetail.bmc_identity.address ?? server?.bmc_address ?? "Not reported"],
    ["OS", nodeDetail.system_identity.os ?? "Not reported"],
    ["Platform", nodeDetail.system_identity.platform ?? "Not reported"],
    ["Hostname", nodeDetail.system_identity.hostname ?? "Not reported"],
    ["Architecture", nodeDetail.system_identity.architecture ?? "Not reported"],
    ["Kernel", nodeDetail.system_identity.kernel ?? "Not reported"],
    ["BIOS vendor", nodeDetail.firmware_identity.bios_vendor ?? "Not reported"],
    ["BIOS version", nodeDetail.firmware_identity.bios_version ?? "Not reported"],
    ["Gateway", nodeDetail.network_identity.gateway ?? "Not reported"],
    ["DNS", nodeDetail.network_identity.dns_servers.join(" / ") || "Not reported"],
    ["All addresses", nodeDetail.platform_addresses.join(" / ") || "Not reported"],
    ["Agent version", nodeDetail.agent_identity.version ?? "Not reported"],
    ["Agent runtime", nodeDetail.software_inventory.runtime ?? nodeDetail.agent_identity.runtime ?? "Not reported"],
    ["OS build", nodeDetail.software_inventory.os_build ?? "Not reported"],
    ["Python version", nodeDetail.software_inventory.python_version ?? "Not reported"],
    ["Tracked components", String(nodeDetail.hardware_inventory.length)],
    ["Open alerts", String(nodeDetail.alerts.filter((alert) => alert.state !== "resolved").length)],
    ["Interfaces", String(nodeDetail.network_identity.interfaces.length)],
  ];
  return rows;
}

function groupHardwareComponents(components: HardwareComponent[]) {
  return components.reduce<Record<string, HardwareComponent[]>>((acc, component) => {
    const key = component.component_type;
    acc[key] = acc[key] ? [...acc[key], component] : [component];
    return acc;
  }, {});
}

function taskRequirement(taskName: string) {
  if (taskName === "gpu_test") return "gpu";
  if (taskName === "disk_test") return "disk";
  if (taskName === "disk_health_test") return "disk";
  if (taskName === "network_test") return "network";
  if (taskName === "cpu_test") return "cpu";
  if (taskName === "memory_test") return "memory";
  if (taskName === "thermal_test") return "thermal";
  if (taskName === "fan_test") return "fan";
  if (taskName === "power_test") return "power";
  if (taskName === "pcie_test") return "pcie";
  if (taskName === "firmware_validation") return "firmware";
  if (taskName === "baseline_comparison") return "baseline";
  if (taskName === "system_validation") return "system_validation";
  if (taskName === "workload_test") return "workload_test";
  if (taskName === "burn_in_test") return "cpu";
  return null;
}

function isTaskSupported(taskName: string, server: ServerRecord | null) {
  const requirement = taskRequirement(taskName);
  if (!requirement) return true;
  return server?.capabilities.includes(requirement) ?? false;
}

function isNewServer(server: ServerRecord, windowHours = 24) {
  const createdAt = new Date(server.created_at).getTime();
  if (Number.isNaN(createdAt)) return false;
  return Date.now() - createdAt <= windowHours * 60 * 60 * 1000;
}

function formatComparisonValue(value: number | null | undefined, suffix = "%") {
  if (value === null || value === undefined || Number.isNaN(value)) return "Not reported";
  return `${Math.round(value)}${suffix}`;
}

function MetricCard({
  title,
  value,
  delta,
  subtitle
}: {
  title: string;
  value: string;
  delta: string;
  subtitle: string;
}) {
  return (
    <article className="clone-mini-card">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="clone-mini-title">{title}</p>
          <p className="clone-mini-value">{value}</p>
          <p className="clone-mini-subtitle">{subtitle}</p>
        </div>
        <span className="clone-card-mark" aria-hidden="true" />
      </div>
      <span className="clone-delta-pill">{delta}</span>
    </article>
  );
}

function ConsoleDropdown({
  label,
  value,
  options,
  onChange,
  placeholder
}: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
  placeholder: string;
}) {
  const [open, setOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement | null>(null);
  const selected = options.find((option) => option.value === value) ?? null;

  useEffect(() => {
    if (!open) return;

    function handlePointerDown(event: MouseEvent) {
      if (!dropdownRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }

    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [open]);

  return (
    <label className="clone-field">
      <span>{label}</span>
      <div ref={dropdownRef} className={`clone-dropdown ${open ? "clone-dropdown--open" : ""}`}>
        <button
          type="button"
          className="clone-dropdown-trigger"
          aria-haspopup="listbox"
          aria-expanded={open}
          onClick={() => setOpen((current) => !current)}
        >
          <span>{selected?.label ?? placeholder}</span>
          <span className="clone-dropdown-caret" aria-hidden="true" />
        </button>

        {open ? (
          <div className="clone-dropdown-menu" role="listbox" aria-label={label}>
            {options.length ? (
              options.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  role="option"
                  aria-selected={option.value === value}
                  className={option.value === value ? "clone-dropdown-option clone-dropdown-option--active" : "clone-dropdown-option"}
                  onClick={() => {
                    onChange(option.value);
                    setOpen(false);
                  }}
                >
                  {option.label}
                </button>
              ))
            ) : (
              <div className="clone-dropdown-empty">{placeholder}</div>
            )}
          </div>
        ) : null}
      </div>
    </label>
  );
}

function ProgressLine({
  label,
  current,
  target,
  value,
  tone
}: {
  label: string;
  current: string;
  target: string;
  value: number;
  tone: "teal" | "green" | "gold";
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3 text-[0.84rem]">
        <span className="font-semibold text-[#262626]">{label}</span>
        <span className="text-[#737373]">
          {current}
          <span className="text-[#a3a3a3]">/{target}</span>
        </span>
      </div>
      <div className="clone-progress-track">
        <div className={`clone-progress-fill clone-progress-fill--${tone}`} style={{ width: `${Math.max(6, Math.min(value, 100))}%` }} />
      </div>
    </div>
  );
}

function AgentOnboardingCard({
  defaultGroup,
  agentEnrollments,
  createAgentEnrollment,
  revokeAgentEnrollment,
  fetchAgentInstallCommand,
}: {
  defaultGroup: string;
  agentEnrollments: AgentEnrollment[];
  createAgentEnrollment: ReturnType<typeof usePrometheusData>["createAgentEnrollment"];
  revokeAgentEnrollment: ReturnType<typeof usePrometheusData>["revokeAgentEnrollment"];
  fetchAgentInstallCommand: ReturnType<typeof usePrometheusData>["fetchAgentInstallCommand"];
}) {
  const [targetOs, setTargetOs] = useState<AgentTargetOS>("windows");
  const [commandLoading, setCommandLoading] = useState(false);
  const [installCommand, setInstallCommand] = useState<AgentInstallCommandResponse | null>(null);
  const [selectedEnrollmentId, setSelectedEnrollmentId] = useState<string>("");
  const [copyState, setCopyState] = useState<"idle" | "copied">("idle");
  const sortedEnrollments = useMemo(
    () => [...agentEnrollments].sort((left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime()),
    [agentEnrollments]
  );

  useEffect(() => {
    if (!selectedEnrollmentId && sortedEnrollments.length) {
      setSelectedEnrollmentId(sortedEnrollments[0].enrollment_id);
    }
  }, [selectedEnrollmentId, sortedEnrollments]);

  useEffect(() => {
    if (sortedEnrollments.length || commandLoading) {
      return;
    }
    let cancelled = false;
    setCommandLoading(true);
    void createAgentEnrollment({
      display_name: `${targetOs}-server`,
      group: defaultGroup || "default",
      target_os: targetOs,
    })
      .then((enrollment) => {
        if (!cancelled) {
          setSelectedEnrollmentId(enrollment.enrollment_id);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setCommandLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [commandLoading, createAgentEnrollment, defaultGroup, sortedEnrollments.length, targetOs]);

  useEffect(() => {
    setInstallCommand(null);
  }, [selectedEnrollmentId, targetOs]);

  useEffect(() => {
    setCopyState("idle");
  }, [installCommand?.command, targetOs]);

  async function handleCopyCommand() {
    if (!selectedEnrollmentId) return;
    let command = installCommand?.command ?? null;
    if (!command) {
      setCommandLoading(true);
      try {
        const payload = await fetchAgentInstallCommand(selectedEnrollmentId, targetOs);
        setInstallCommand(payload);
        command = payload.command;
      } catch {
        setInstallCommand(null);
        return;
      } finally {
        setCommandLoading(false);
      }
    }
    if (!command) return;
    await navigator.clipboard.writeText(command);
    setCopyState("copied");
    window.setTimeout(() => setCopyState("idle"), 1800);
  }

  return (
    <section className="clone-command-card">
      <div className="clone-command-bar">
        <div className="clone-command-bar__controls">
          <div className="clone-period-toggle">
            {(["windows", "linux"] as AgentTargetOS[]).map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setTargetOs(option)}
                className={option === targetOs ? "clone-period-toggle__active" : "clone-period-toggle__idle"}
                >
                  {option === "windows" ? "Windows" : "Linux"}
                </button>
              ))}
          </div>
        </div>

        <div className="clone-command-line clone-command-line--compact">
          <pre className="clone-command-shell__body clone-command-shell__body--compact">
            {installCommand?.command ?? (commandLoading ? "Generating install command..." : "Copy to generate the one-line native installer command.")}
          </pre>
          <button className="clone-command-copy" type="button" onClick={() => void handleCopyCommand()} disabled={!selectedEnrollmentId || commandLoading}>
            {copyState === "copied" ? "Copied" : "Copy"}
          </button>
        </div>
      </div>
    </section>
  );
}

function DashboardView({
  dashboard,
  primaryServer,
  openControls,
  lastUpdated,
  currentTime,
  period,
  setPeriod,
  agentEnrollments,
  createAgentEnrollment,
  revokeAgentEnrollment,
  fetchAgentInstallCommand,
}: {
  dashboard: ReturnType<typeof usePrometheusData>["dashboard"];
  primaryServer: ServerRecord | null;
  openControls: () => void;
  lastUpdated: string;
  currentTime: Date;
  period: Period;
  setPeriod: (value: Period) => void;
  agentEnrollments: ReturnType<typeof usePrometheusData>["agentEnrollments"];
  createAgentEnrollment: ReturnType<typeof usePrometheusData>["createAgentEnrollment"];
  revokeAgentEnrollment: ReturnType<typeof usePrometheusData>["revokeAgentEnrollment"];
  fetchAgentInstallCommand: ReturnType<typeof usePrometheusData>["fetchAgentInstallCommand"];
}) {
  const [runSearch, setRunSearch] = useState("");
  const [runFilter, setRunFilter] = useState<RunFilter>("all");
  const { history, historyLoading } = useDashboardHistory(period);
  const onlineRatio = dashboard.fleet_total === 0 ? 0 : (dashboard.fleet_online / dashboard.fleet_total) * 100;
  const completedRuns = dashboard.recent_runs.filter((run) => run.status === "completed").length;
  const completedRatio = dashboard.recent_runs.length === 0 ? 0 : (completedRuns / dashboard.recent_runs.length) * 100;
  const alertPressure = dashboard.fleet_total === 0 ? 0 : (dashboard.alerts / dashboard.fleet_total) * 100;
  const historySeries = history.points;
  const highlightedPoint = historySeries[historySeries.length - 1] ?? null;
  const primaryMetric = dashboard.latest_metrics.find((metric) => metric.server_id === primaryServer?.server_id) ?? dashboard.latest_metrics[0];
  const recentRows = useMemo(() => {
    const pool = topRuns(dashboard.recent_runs);
    return pool.filter((run) => {
      const matchesFilter = runFilter === "all" ? true : run.status === runFilter;
      const query = runSearch.trim().toLowerCase();
      const serverName = dashboard.servers.find((server) => server.server_id === run.server_id)?.server_name ?? run.server_id;
      const matchesSearch =
        !query || [serverName, run.server_id, run.task, run.status].join(" ").toLowerCase().includes(query);
      return matchesFilter && matchesSearch;
    });
  }, [dashboard.recent_runs, dashboard.servers, runFilter, runSearch]);
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.68fr)_318px]">
      <div className="space-y-5">
        <AgentOnboardingCard
          defaultGroup={primaryServer?.group ?? "default"}
          agentEnrollments={agentEnrollments}
          createAgentEnrollment={createAgentEnrollment}
          revokeAgentEnrollment={revokeAgentEnrollment}
          fetchAgentInstallCommand={fetchAgentInstallCommand}
        />

        <section className="clone-strip-card">
          <div className="grid gap-4 md:grid-cols-3">
            <MetricCard
              title="Fleet Online"
              value={`${dashboard.fleet_online}/${dashboard.fleet_total || 0}`}
              delta={kpiDelta(onlineRatio, 6)}
              subtitle="servers reporting healthy heartbeats"
            />
            <MetricCard
              title="Active Runs"
              value={`${dashboard.active_runs}`}
              delta={kpiDelta(completedRatio, 5)}
              subtitle="benchmarks currently executing"
            />
            <MetricCard
              title="Benchmark Score"
              value={`${dashboard.average_score}%`}
              delta={kpiDelta(dashboard.average_score * 0.4, 4)}
              subtitle="fleet readiness confidence"
            />
          </div>
        </section>

        <section className="clone-main-card">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="clone-section-title">Fleet Readiness</p>
              <div className="mt-1 flex items-center gap-3">
                <h2 className="clone-balance-value">{dashboard.average_score}%</h2>
                <span className="clone-delta-pill">{kpiDelta(dashboard.average_score * 0.36, 5)}</span>
              </div>
              <p className="mt-3 text-[0.95rem] text-[#737373]">Live infrastructure confidence blended with benchmark readiness.</p>
            </div>

            <div className="clone-period-toggle">
              {PERIODS.map((option) => (
                <button
                  key={option}
                  onClick={() => setPeriod(option)}
                  aria-pressed={option === period}
                  className={option === period ? "clone-period-toggle__active" : "clone-period-toggle__idle"}
                >
                  {option}
                </button>
              ))}
            </div>
          </div>

          <div className="mt-7">
            <ReadinessHistoryChart history={historySeries} period={period} />
          </div>
          {highlightedPoint ? (
            <div className="mt-5 grid gap-3 md:grid-cols-3">
              <div className="clone-data-chip">
                <span>Highlighted bucket</span>
                <strong>{highlightedPoint.label}</strong>
              </div>
              <div className="clone-data-chip">
                <span>Readiness</span>
                <strong>{Math.round(highlightedPoint.value)}%</strong>
              </div>
              <div className="clone-data-chip">
                <span>Completed runs</span>
                <strong>
                  {highlightedPoint.completed_runs}/{highlightedPoint.total_runs}
                </strong>
              </div>
            </div>
          ) : null}
          {!historySeries.length ? (
            <div className="mt-6 clone-empty-state">{historyLoading ? "Loading history..." : "No historical run data available yet."}</div>
          ) : null}
        </section>

        <section className="clone-table-card">
          <div className="flex flex-wrap items-center justify-between gap-4 px-6 py-5">
            <p className="clone-section-title">Run History</p>
            <div className="flex items-center gap-3">
              <label className="clone-search-pill">
                <span className="icon-search icon-search--small" />
                <input value={runSearch} onChange={(event) => setRunSearch(event.target.value)} placeholder="Search runs" />
              </label>
              <button
                type="button"
                className="clone-filter-pill"
                onClick={() => setRunFilter((current) => (current === "all" ? "running" : current === "running" ? "completed" : current === "completed" ? "failed" : "all"))}
              >
                <span className="clone-filter-icon" />
                <span>{runFilter === "all" ? "All" : nice(runFilter)}</span>
              </button>
            </div>
          </div>

          <div className="clone-table-head">
            <span>Node</span>
            <span>Updated</span>
            <span>Score</span>
            <span>Status</span>
            <span>Task Type</span>
          </div>

          {(recentRows.length ? recentRows : []).map((run) => {
            const runServer = dashboard.servers.find((server) => server.server_id === run.server_id);
            return (
              <div key={run.task_id} className="clone-table-row">
                <div className="flex items-center gap-3" data-label="Node">
                  <span className="clone-table-avatar">{(runServer?.server_name ?? "P").slice(0, 1).toUpperCase()}</span>
                  <div>
                    <p className="font-semibold text-[#262626]">{runServer?.server_name ?? run.server_id}</p>
                    <p className="mt-1 text-[0.82rem] text-[#a3a3a3]">{run.server_id}</p>
                  </div>
                </div>
                <span className="text-[#737373]" data-label="Updated">{formatCalendarDate(run.updated_at)}</span>
                <span className="font-semibold text-[#262626]" data-label="Score">{run.score ?? "--"}</span>
                <span data-label="Status">
                  <span className={statusClass(run.status)}>{statusLabel(run.status)}</span>
                </span>
                <span className="text-[#737373]" data-label="Task Type">{nice(run.task)}</span>
              </div>
            );
          })}
          {!recentRows.length ? <div className="clone-empty-state">No matching runs for the current search and filter.</div> : null}
        </section>
      </div>

      <div className="space-y-5">
        <section className="clone-side-card">
          <div className="flex items-center justify-between gap-3">
            <p className="clone-section-title">Infrastructure Health</p>
            <span className="clone-filter-pill" aria-hidden="true">
              <span className="clone-filter-icon" />
              <span>Live</span>
            </span>
          </div>

          <InfrastructureHealthChart
            score={dashboard.average_score}
            onlineRatio={onlineRatio}
            completedRatio={completedRatio}
            alertPressure={alertPressure}
          />

          <div className="space-y-5">
            <ProgressLine label="Availability" current={`${dashboard.fleet_online}`} target={`${dashboard.fleet_total || 0}`} value={onlineRatio} tone="teal" />
            <ProgressLine label="Run completion" current={`${completedRuns}`} target={`${dashboard.recent_runs.length || 0}`} value={completedRatio} tone="green" />
            <ProgressLine label="Alert pressure" current={`${dashboard.alerts}`} target={`${dashboard.fleet_total || 0}`} value={alertPressure} tone="gold" />
          </div>
        </section>

        <section className="clone-side-card">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="clone-section-title">Selected Node</p>
              <p className="mt-1 text-[0.92rem] text-[#737373]">Selected server snapshot</p>
            </div>
            <button className="text-sm font-semibold text-[#525252]" onClick={openControls}>
              Open controls
            </button>
          </div>

          <div className="clone-server-card">
            <p className="clone-server-card__eyebrow">{primaryServer?.group ?? "Server Group"}</p>
            <p className="mt-4 text-[0.96rem] font-semibold text-[#525252]">{primaryServer?.server_name ?? "Prometheus Node"}</p>
            <p className="mt-5 text-[2rem] font-extrabold tracking-[0.02em] text-[#111111]">
              {primaryServer?.server_id ? primaryServer.server_id.match(/.{1,4}/g)?.join(" ") : "3234 8678 4234 7628"}
            </p>

            <div className="mt-6 grid grid-cols-3 gap-3 text-[0.72rem] uppercase tracking-[0.14em] text-[#737373]">
              <div>
                <p>CPU</p>
                <p className="mt-2 text-[1rem] font-bold normal-case text-[#262626]">{primaryMetric ? percent(primaryMetric.cpu) : "--"}</p>
              </div>
              <div>
                <p>Memory</p>
                <p className="mt-2 text-[1rem] font-bold normal-case text-[#262626]">{primaryMetric ? percent(primaryMetric.memory) : "--"}</p>
              </div>
              <div>
                <p>Disk</p>
                <p className="mt-2 text-[1rem] font-bold normal-case text-[#262626]">{primaryMetric ? percent(primaryMetric.disk) : "--"}</p>
              </div>
            </div>

            <div className="mt-7 flex items-end justify-between">
              <div>
                <p className="text-[0.68rem] uppercase tracking-[0.18em] text-[#737373]">Health status</p>
                <p className="mt-2 text-[1.05rem] font-bold text-[#262626]">{primaryServer?.health ?? "PASS"}</p>
              </div>
              <div className="text-right">
                <p className="text-[0.68rem] uppercase tracking-[0.18em] text-[#737373]">Time ({PLATFORM_TIMEZONE})</p>
                <p className="mt-2 text-[1.05rem] font-bold text-[#262626]">{formatNow(currentTime)}</p>
                <p className="mt-1 text-[0.78rem] text-[#737373]">Last sync {formatDateTime(lastUpdated)}</p>
              </div>
            </div>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-3">
            <button className="clone-cta clone-cta--light" onClick={openControls}>
              <span className="clone-arrow-icon clone-arrow-icon--down" />
              <span>Run Task</span>
            </button>
            <button className="clone-cta clone-cta--light" onClick={openControls}>
              <span className="clone-arrow-icon clone-arrow-icon--up" />
              <span>Run Workflow</span>
            </button>
          </div>
        </section>

      </div>

    </div>
  );
}

function ControlHub({
  dashboard,
  selectedServerId,
  setSelectedServerId,
  selectedTask,
  setSelectedTask,
  selectedWorkflow,
  setSelectedWorkflow,
  actionPending,
  actionError,
  actionSuccess,
  triggerTask,
  triggerWorkflow,
  inline = false,
  onClose
}: {
  dashboard: ReturnType<typeof usePrometheusData>["dashboard"];
  selectedServerId: string;
  setSelectedServerId: (value: string) => void;
  selectedTask: string;
  setSelectedTask: (value: string) => void;
  selectedWorkflow: string;
  setSelectedWorkflow: (value: string) => void;
  actionPending: ReturnType<typeof usePrometheusData>["actionPending"];
  actionError: string | null;
  actionSuccess: string | null;
  triggerTask: ReturnType<typeof usePrometheusData>["triggerTask"];
  triggerWorkflow: ReturnType<typeof usePrometheusData>["triggerWorkflow"];
  inline?: boolean;
  onClose?: () => void;
}) {
  const selectedTaskTemplate = dashboard.allowed_tasks.find((task) => task.name === selectedTask) ?? null;
  const selectedWorkflowTemplate = dashboard.workflow_templates.find((workflow) => workflow.name === selectedWorkflow) ?? null;
  const selectedServer = dashboard.servers.find((server) => server.server_id === selectedServerId) ?? null;
  const serverOptions = dashboard.servers.map((server) => ({ value: server.server_id, label: server.server_name }));
  const taskOptions = dashboard.allowed_tasks
    .filter((task) => isTaskSupported(task.name, selectedServer))
    .map((task) => ({ value: task.name, label: nice(task.name) }));
  const workflowOptions = dashboard.workflow_templates
    .filter((workflow) => workflow.steps.every((step) => isTaskSupported(step, selectedServer)))
    .map((workflow) => ({ value: workflow.name, label: nice(workflow.name) }));

  return (
    <section className={inline ? "clone-inline-control-card" : "clone-overlay-card"}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="clone-section-title">Execution Console</p>
          <p className="mt-1 text-[0.92rem] text-[#737373]">Dispatch real Prometheus tasks without crowding the main dashboard.</p>
        </div>
        {onClose ? (
          <button className="mini-icon-button mini-icon-button--tiny" aria-label="Close controls" onClick={onClose}>
            <span className="clone-close-icon" />
          </button>
        ) : null}
      </div>

        <div className="mt-5 space-y-4">
          <ConsoleDropdown
            label="Target server"
            value={selectedServerId}
            options={serverOptions}
            onChange={setSelectedServerId}
            placeholder="No servers connected yet"
          />

          <ConsoleDropdown
            label="Quick task"
            value={selectedTask}
            options={taskOptions}
            onChange={setSelectedTask}
            placeholder="No tasks available"
          />
          {selectedTaskTemplate ? (
            <div className="clone-helper-copy">
              <p>{selectedTaskTemplate.summary}</p>
              <p>Default timeout: {selectedTaskTemplate.default_timeout_seconds}s</p>
            </div>
          ) : null}

          <ConsoleDropdown
            label="Workflow"
            value={selectedWorkflow}
            options={workflowOptions}
            onChange={setSelectedWorkflow}
            placeholder="No workflows available"
          />
        {selectedWorkflowTemplate ? (
          <div className="clone-helper-copy">
            <p>{selectedWorkflowTemplate.summary}</p>
            <p>{selectedWorkflowTemplate.steps.length} step workflow</p>
          </div>
        ) : null}
      </div>

      {actionError ? <div className="clone-warning-banner">{actionError}</div> : null}
      {actionSuccess ? <div className="clone-success-banner">{actionSuccess}</div> : null}

      <div className="mt-5 space-y-3">
        <button
          onClick={() =>
            selectedServerId &&
            selectedTask &&
            void triggerTask({ server_id: selectedServerId, task: selectedTask, requested_by: "web-ui" })
          }
          disabled={!selectedServerId || !selectedTask || actionPending}
          className="clone-primary-action disabled:opacity-60"
        >
          {actionPending ? "Running task..." : "Run task now"}
        </button>
        <button
          onClick={() =>
            selectedServerId &&
            selectedWorkflow &&
            void triggerWorkflow({ server_id: selectedServerId, workflow: selectedWorkflow, requested_by: "web-ui" })
          }
          disabled={!selectedServerId || !selectedWorkflow || actionPending}
          className="clone-secondary-action disabled:opacity-60"
        >
          {actionPending ? "Dispatching workflow..." : "Run workflow"}
        </button>
      </div>
    </section>
  );
}

function ShellPanel({
  title,
  subtitle,
  children
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  return (
    <section className="clone-main-card">
      <div className="mb-5">
        <p className="clone-section-title">{title}</p>
        <p className="mt-2 text-[0.95rem] text-[#737373]">{subtitle}</p>
      </div>
      {children}
    </section>
  );
}

function App() {
  const {
    dashboard,
    fleetMonitoring,
    alerts,
    alertRules,
    baselines,
    schedules,
    notificationEndpoints,
    events,
    connection,
    lastUpdated,
    isLoading,
    error,
    actionPending,
    actionError,
    actionSuccess,
    triggerTask,
    triggerWorkflow,
    fetchRunDetail,
    fetchNodeDetail,
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
    agentEnrollments,
    createAgentEnrollment,
    revokeAgentEnrollment,
    fetchAgentInstallCommand,
    openTerminalSession,
    closeTerminalSession,
    terminalWebSocketUrl
  } = usePrometheusData();

  const [activeNav, setActiveNav] = useState<NavItem>("Dashboard");
  const [period, setPeriod] = useState<Period>("Month");
  const [controlsOpen, setControlsOpen] = useState(false);
  const [selectedServerId, setSelectedServerId] = useState("");
  const [runsSelectedServerId, setRunsSelectedServerId] = useState("");
  const [runsDetailOpen, setRunsDetailOpen] = useState(false);
  const [workflowSelectedServerId, setWorkflowSelectedServerId] = useState("");
  const [workflowDetailOpen, setWorkflowDetailOpen] = useState(false);
  const [analyticsPeriod, setAnalyticsPeriod] = useState<Period>("Month");
  const [analyticsServerId, setAnalyticsServerId] = useState("");
  const [analyticsCompareServerId, setAnalyticsCompareServerId] = useState("");
  const [analyticsGroupFilter, setAnalyticsGroupFilter] = useState("all");
  const [analyticsPlatformFilter, setAnalyticsPlatformFilter] = useState("all");
  const [analyticsExportMessage, setAnalyticsExportMessage] = useState<string | null>(null);
  const [trackerDetailOpen, setTrackerDetailOpen] = useState(false);
  const [trackerExportMessage, setTrackerExportMessage] = useState<string | null>(null);
  const [serverWorkspaceSection, setServerWorkspaceSection] = useState<ServerWorkspaceSection>("overview");
  const [terminalSession, setTerminalSession] = useState<TerminalSession | null>(null);
  const [terminalBuffer, setTerminalBuffer] = useState("");
  const [terminalInput, setTerminalInput] = useState("");
  const [terminalConnecting, setTerminalConnecting] = useState(false);
  const [terminalError, setTerminalError] = useState<string | null>(null);
  const [selectedTask, setSelectedTask] = useState("");
  const [selectedWorkflow, setSelectedWorkflow] = useState("");
  const [selectedRunId, setSelectedRunId] = useState("");
  const [nodeDetail, setNodeDetail] = useState<NodeDetailResponse | null>(null);
  const [runDetail, setRunDetail] = useState<RunDetailResponse | null>(null);
  const legacyRunDetail = runDetail as any;
  const [detailLoading, setDetailLoading] = useState(false);
  const [scheduleInterval, setScheduleInterval] = useState("60");
  const [baselineScore, setBaselineScore] = useState("85");
  const [notificationTarget, setNotificationTarget] = useState("");
  const [notificationChannel, setNotificationChannel] = useState<"email" | "webhook">("webhook");
  const [ruleName, setRuleName] = useState("");
  const [ruleSignal, setRuleSignal] = useState("cpu_utilization");
  const [ruleThreshold, setRuleThreshold] = useState("85");
  const [ruleSeverity, setRuleSeverity] = useState<"info" | "warning" | "critical">("warning");
  const [searchText, setSearchText] = useState("");
  const [runsSearchText, setRunsSearchText] = useState("");
  const [workflowSearchText, setWorkflowSearchText] = useState("");
  const [currentTime, setCurrentTime] = useState(() => new Date());
  const deferredSearch = useDeferredValue(searchText);
  const deferredRunsSearch = useDeferredValue(runsSearchText);
  const deferredWorkflowSearch = useDeferredValue(workflowSearchText);
  const profileButtonRef = useRef<HTMLButtonElement | null>(null);
  const searchButtonRef = useRef<HTMLButtonElement | null>(null);
  const overlayPanelRef = useRef<HTMLDivElement | null>(null);
  const terminalSocketRef = useRef<WebSocket | null>(null);
  const terminalViewportRef = useRef<HTMLDivElement | null>(null);
  const selectedServer = useMemo(
    () => dashboard.servers.find((server) => server.server_id === selectedServerId) ?? null,
    [dashboard.servers, selectedServerId]
  );
  const workflowSelectedServer = useMemo(
    () => dashboard.servers.find((server) => server.server_id === workflowSelectedServerId) ?? null,
    [dashboard.servers, workflowSelectedServerId]
  );
  const supportedTaskName = useMemo(
    () => dashboard.allowed_tasks.find((task) => isTaskSupported(task.name, selectedServer))?.name ?? "",
    [dashboard.allowed_tasks, selectedServer]
  );
  const supportedWorkflowName = useMemo(
    () =>
      dashboard.workflow_templates.find((workflow) =>
        workflow.steps.every((step) => isTaskSupported(step, selectedServer))
      )?.name ?? "",
    [dashboard.workflow_templates, selectedServer]
  );
  const workflowTaskOptions = useMemo(
    () => dashboard.allowed_tasks.filter((task) => isTaskSupported(task.name, workflowSelectedServer)),
    [dashboard.allowed_tasks, workflowSelectedServer]
  );
  const workflowTemplateOptions = useMemo(
    () =>
      dashboard.workflow_templates.filter((workflow) =>
        workflow.steps.every((step) => isTaskSupported(step, workflowSelectedServer))
      ),
    [dashboard.workflow_templates, workflowSelectedServer]
  );

  useEffect(() => {
    if (!selectedServerId && dashboard.servers.length > 0) {
      setSelectedServerId(dashboard.servers[0].server_id);
    }
  }, [dashboard.servers, selectedServerId]);

  useEffect(() => {
    if (!selectedTask && supportedTaskName) {
      setSelectedTask(supportedTaskName);
    }
  }, [selectedTask, supportedTaskName]);

  useEffect(() => {
    if (!selectedWorkflow && supportedWorkflowName) {
      setSelectedWorkflow(supportedWorkflowName);
    }
  }, [selectedWorkflow, supportedWorkflowName]);

  useEffect(() => {
    if (selectedTask && !isTaskSupported(selectedTask, selectedServer)) {
      if (supportedTaskName !== selectedTask) {
        setSelectedTask(supportedTaskName);
      }
    }
    if (
      selectedWorkflow &&
      !dashboard.workflow_templates.some(
        (workflow) =>
          workflow.name === selectedWorkflow && workflow.steps.every((step) => isTaskSupported(step, selectedServer))
      )
    ) {
      if (supportedWorkflowName !== selectedWorkflow) {
        setSelectedWorkflow(supportedWorkflowName);
      }
    }
  }, [dashboard.workflow_templates, selectedServer, selectedTask, selectedWorkflow, supportedTaskName, supportedWorkflowName]);

  useEffect(() => {
    const timer = window.setInterval(() => setCurrentTime(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!selectedRunId && dashboard.recent_runs.length > 0) {
      setSelectedRunId(dashboard.recent_runs[0].task_id);
    }
  }, [dashboard.recent_runs, selectedRunId]);

  useEffect(() => {
    if (!terminalSession) {
      terminalSocketRef.current?.close();
      terminalSocketRef.current = null;
      return;
    }

    let cancelled = false;
    let socket: WebSocket | null = null;

    void terminalWebSocketUrl(terminalSession.session_id)
      .then((url) => {
        if (cancelled) return;
        socket = new WebSocket(url);
        terminalSocketRef.current = socket;
        socket.onmessage = (event) => {
          try {
            const payload = JSON.parse(event.data) as { kind?: string; text?: string; session?: TerminalSession };
            if (payload.kind === "output" && typeof payload.text === "string") {
              setTerminalBuffer((current) => `${current}${payload.text}`);
            }
            if ((payload.kind === "session" || payload.kind === "status") && payload.session) {
              setTerminalSession(payload.session);
            }
          } catch {
            // Ignore malformed terminal frames.
          }
        };
        socket.onclose = () => {
          if (!cancelled) {
            setTerminalSession((current) => (current ? { ...current, status: "disconnected" } : current));
          }
        };
      })
      .catch((requestError) => {
        if (!cancelled) {
          setTerminalError(requestError instanceof Error ? requestError.message : "Unable to connect terminal websocket.");
        }
      });

    return () => {
      cancelled = true;
      if (socket) {
        socket.close();
      }
      if (terminalSocketRef.current === socket) {
        terminalSocketRef.current = null;
      }
    };
  }, [terminalSession?.session_id, terminalWebSocketUrl]);

  useEffect(() => {
    const viewport = terminalViewportRef.current;
    if (viewport) {
      viewport.scrollTop = viewport.scrollHeight;
    }
  }, [terminalBuffer]);

  function openServerWorkspace(serverId: string, section: ServerWorkspaceSection = "overview") {
    setSelectedServerId(serverId);
    setRunsSelectedServerId(serverId);
    setWorkflowSelectedServerId(serverId);
    setTrackerDetailOpen(true);
    setRunsDetailOpen(false);
    setWorkflowDetailOpen(false);
    setServerWorkspaceSection(section);
    setActiveNav("Servers");
  }

  async function openServerTerminal(serverId: string) {
    openServerWorkspace(serverId, "terminal");
    setTerminalError(null);
    setTerminalConnecting(true);
    try {
      const session = await openTerminalSession(serverId, 132, 34);
      setTerminalSession(session);
      setTerminalBuffer(session.recent_output.map((frame) => frame.text ?? "").join(""));
    } catch (requestError) {
      setTerminalSession(null);
      setTerminalBuffer("");
      setTerminalError(requestError instanceof Error ? requestError.message : "Unable to open terminal session.");
    } finally {
      setTerminalConnecting(false);
    }
  }

  function submitTerminalCommand() {
    if (!terminalSession || !terminalInput.trim()) {
      return;
    }
    const command = terminalInput.endsWith("\n") ? terminalInput : `${terminalInput}\n`;
    const socket = terminalSocketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ kind: "input", data: command }));
      setTerminalBuffer((current) => `${current}> ${terminalInput}\n`);
      setTerminalInput("");
      return;
    }
    setTerminalError("Terminal websocket is not connected yet.");
  }

  const primaryServer = pickPrimaryServer(dashboard.servers, selectedServerId);
  const filteredServers = useMemo(() => {
    const term = deferredSearch.trim().toLowerCase();
    if (!term) return dashboard.servers;
    return dashboard.servers.filter((server) =>
      [
        server.server_name,
        server.server_id,
        server.group,
        server.health,
        server.status,
        server.platform_label ?? "",
        server.platform_family ?? "",
        server.primary_ip ?? "",
        ...server.tags,
        ...server.capabilities
      ]
        .join(" ")
        .toLowerCase()
        .includes(term)
    );
  }, [dashboard.servers, deferredSearch]);
  const filteredWorkflowServers = useMemo(() => {
    const term = deferredWorkflowSearch.trim().toLowerCase();
    if (!term) return dashboard.servers;
    return dashboard.servers.filter((server) =>
      [
        server.server_name,
        server.server_id,
        server.group,
        server.primary_ip ?? "",
        server.platform_label ?? "",
        server.status,
        server.health,
        ...server.tags,
        ...server.capabilities,
      ]
        .join(" ")
        .toLowerCase()
        .includes(term)
    );
  }, [dashboard.servers, deferredWorkflowSearch]);
  const analyticsGroups = useMemo(() => ["all", ...new Set(dashboard.servers.map((server) => server.group))], [dashboard.servers]);
  const analyticsPlatforms = useMemo(
    () => ["all", ...new Set(dashboard.servers.map((server) => server.platform_label ?? server.platform_family ?? "Unknown"))],
    [dashboard.servers]
  );
  const filteredAnalyticsServers = useMemo(
    () =>
      dashboard.servers.filter((server) => {
        const groupMatch = analyticsGroupFilter === "all" || server.group === analyticsGroupFilter;
        const platformValue = server.platform_label ?? server.platform_family ?? "Unknown";
        const platformMatch = analyticsPlatformFilter === "all" || platformValue === analyticsPlatformFilter;
        return groupMatch && platformMatch;
      }),
    [analyticsGroupFilter, analyticsPlatformFilter, dashboard.servers]
  );
  const hardwareGroups = useMemo(() => groupHardwareComponents(nodeDetail?.hardware_inventory ?? []), [nodeDetail?.hardware_inventory]);
  const hardwareSections = useMemo(
    () => [
      { key: "cpu", label: "CPU" },
      { key: "memory", label: "Memory" },
      { key: "storage", label: "Storage" },
      { key: "gpu", label: "GPU" },
      { key: "network", label: "Network" },
      { key: "thermal_power", label: "Thermal / Power" },
      { key: "pcie_inventory", label: "Inventory / PCIe" },
      { key: "system", label: "System" },
    ],
    []
  );
  const serverMetricMap = useMemo(
    () => new Map(dashboard.latest_metrics.map((metric) => [metric.server_id, metric])),
    [dashboard.latest_metrics]
  );

  const latestRuns = useMemo(() => topRuns(dashboard.recent_runs), [dashboard.recent_runs]);
  const liveMetrics = useMemo(
    () =>
      dashboard.latest_metrics.map((metric) => ({
        ...metric,
        serverName: dashboard.servers.find((server) => server.server_id === metric.server_id)?.server_name ?? metric.server_id
      })),
    [dashboard.latest_metrics, dashboard.servers]
  );
  const workflowServerMetric = useMemo(
    () => dashboard.latest_metrics.find((metric) => metric.server_id === workflowSelectedServerId) ?? null,
    [dashboard.latest_metrics, workflowSelectedServerId]
  );
  const workflowServerRuns = useMemo(
    () =>
      [...dashboard.recent_runs]
        .filter((run) => run.server_id === workflowSelectedServerId)
        .sort((left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime())
        .slice(0, 5),
    [dashboard.recent_runs, workflowSelectedServerId]
  );
  const workflowServerWorkflowRuns = useMemo(
    () =>
      [...dashboard.workflows]
        .filter((workflow) => workflow.server_id === workflowSelectedServerId)
        .sort((left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime())
        .slice(0, 5),
    [dashboard.workflows, workflowSelectedServerId]
  );
  const analyticsServer = useMemo(
    () => filteredAnalyticsServers.find((server) => server.server_id === analyticsServerId) ?? filteredAnalyticsServers[0] ?? null,
    [analyticsServerId, filteredAnalyticsServers]
  );
  const analyticsCompareServer = useMemo(() => {
    const selected = filteredAnalyticsServers.find((server) => server.server_id === analyticsCompareServerId);
    if (selected && selected.server_id !== analyticsServer?.server_id) return selected;
    return filteredAnalyticsServers.find((server) => server.server_id !== analyticsServer?.server_id) ?? analyticsServer ?? null;
  }, [analyticsCompareServerId, analyticsServer, filteredAnalyticsServers]);
  const analyticsPrimaryMetric = useMemo(
    () => (analyticsServer ? serverMetricMap.get(analyticsServer.server_id) ?? null : null),
    [analyticsServer, serverMetricMap]
  );
  const analyticsSecondaryMetric = useMemo(
    () => (analyticsCompareServer ? serverMetricMap.get(analyticsCompareServer.server_id) ?? null : null),
    [analyticsCompareServer, serverMetricMap]
  );
  const filteredAnalyticsMetrics = useMemo(
    () => liveMetrics.filter((metric) => filteredAnalyticsServers.some((server) => server.server_id === metric.server_id)),
    [filteredAnalyticsServers, liveMetrics]
  );
  const analyticsRunSubset = useMemo(
    () =>
      dashboard.recent_runs.filter((run) =>
        filteredAnalyticsServers.some((server) => server.server_id === run.server_id)
      ),
    [dashboard.recent_runs, filteredAnalyticsServers]
  );
  const analyticsAlertsSubset = useMemo(
    () =>
      alerts.filter((alert) =>
        filteredAnalyticsServers.some((server) => server.server_id === alert.server_id)
      ),
    [alerts, filteredAnalyticsServers]
  );
  const monitoringCards = fleetMonitoring.cards;
  const cpuHistory = historyByKey(fleetMonitoring.histories, "cpu");
  const memoryHistory = historyByKey(fleetMonitoring.histories, "memory");
  const storageHistory = historyByKey(fleetMonitoring.histories, "storage");
  const gpuHistory = historyByKey(fleetMonitoring.histories, "gpu");
  const networkHistory = historyByKey(fleetMonitoring.histories, "network");
  const thermalHistory = historyByKey(fleetMonitoring.histories, "thermal");
  const fanHistory = historyByKey(fleetMonitoring.histories, "fan");
  const fanSummary = summaryByKey(fleetMonitoring.component_summaries, "fan");
  const { history: analyticsHistory, historyLoading: analyticsHistoryLoading } = useDashboardHistory(analyticsPeriod);
  const analyticsOverviewCards = useMemo(() => {
    const hottest = [...liveMetrics]
      .filter((metric) => metric.temperature_c !== null && metric.temperature_c !== undefined)
      .sort((left, right) => (right.temperature_c ?? 0) - (left.temperature_c ?? 0))[0];
    const mostLoaded = [...liveMetrics].sort((left, right) => right.cpu - left.cpu)[0];
    const noisiest = [...alerts].sort(
      (left, right) => new Date(right.updated_at ?? right.created_at ?? 0).getTime() - new Date(left.updated_at ?? left.created_at ?? 0).getTime()
    )[0];
    const weakestGroup = [...dashboard.group_inventory].sort((left, right) => left.average_score - right.average_score)[0];
    return [
      { label: "Hottest server", value: hottest ? `${hottest.serverName} ${formatComparisonValue(hottest.temperature_c, "C")}` : "Not reported" },
      { label: "Highest CPU pressure", value: mostLoaded ? `${mostLoaded.serverName} ${formatComparisonValue(mostLoaded.cpu)}` : "Not reported" },
      { label: "Latest alert hotspot", value: noisiest ? `${nice(noisiest.signal)} on ${noisiest.server_id}` : "No active alerts" },
      { label: "Weakest group", value: weakestGroup ? `${weakestGroup.group} ${weakestGroup.average_score}%` : "Not reported" },
    ];
  }, [alerts, dashboard.group_inventory, liveMetrics]);
  const analyticsComparisonRows = useMemo(
    () => [
      { label: "CPU", left: analyticsPrimaryMetric?.cpu ?? null, right: analyticsSecondaryMetric?.cpu ?? null, suffix: "%" },
      { label: "Memory", left: analyticsPrimaryMetric?.memory ?? null, right: analyticsSecondaryMetric?.memory ?? null, suffix: "%" },
      { label: "Disk", left: analyticsPrimaryMetric?.disk ?? null, right: analyticsSecondaryMetric?.disk ?? null, suffix: "%" },
      { label: "Network", left: analyticsPrimaryMetric?.network_mbps ?? null, right: analyticsSecondaryMetric?.network_mbps ?? null, suffix: " Mbps" },
      { label: "Temperature", left: analyticsPrimaryMetric?.temperature_c ?? null, right: analyticsSecondaryMetric?.temperature_c ?? null, suffix: "C" },
      { label: "GPU", left: analyticsPrimaryMetric?.gpu_utilization ?? null, right: analyticsSecondaryMetric?.gpu_utilization ?? null, suffix: "%" },
      { label: "Fan speed", left: analyticsPrimaryMetric?.fan_speed_rpm ?? null, right: analyticsSecondaryMetric?.fan_speed_rpm ?? null, suffix: " RPM" },
    ],
    [analyticsPrimaryMetric, analyticsSecondaryMetric]
  );
  const analyticsRegressions = useMemo(() => {
    const grouped = new Map<string, TaskRun[]>();
    for (const run of dashboard.recent_runs) {
      if (run.score === null) continue;
      const key = `${run.server_id}:${run.task}`;
      const bucket = grouped.get(key) ?? [];
      bucket.push(run);
      grouped.set(key, bucket);
    }
    return [...grouped.values()]
      .map((runs) => runs.sort((left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime()))
      .filter((runs) => runs.length >= 2 && runs[0].score !== null && runs[1].score !== null)
      .map((runs) => {
        const latest = runs[0];
        const previous = runs[1];
        const delta = (latest.score ?? 0) - (previous.score ?? 0);
        return {
          serverId: latest.server_id,
          task: latest.task,
          latestScore: latest.score ?? 0,
          previousScore: previous.score ?? 0,
          delta,
          updatedAt: latest.updated_at,
          severity: delta <= -10 ? "critical" : delta < 0 ? "warning" : "info",
        };
      })
      .sort((left, right) => left.delta - right.delta)
      .slice(0, 6);
  }, [dashboard.recent_runs]);
  const filteredMonitoringCards = useMemo(() => {
    const term = deferredRunsSearch.trim().toLowerCase();
    if (!term) return monitoringCards;
    return monitoringCards.filter((card) =>
      [
        card.server.server_name,
        card.server.server_id,
        card.server.group,
        card.server.primary_ip ?? "",
        card.server.platform_label ?? "",
        card.server.health,
        card.server.status,
        ...card.server.tags,
        ...card.server.capabilities,
      ]
        .join(" ")
        .toLowerCase()
        .includes(term)
    );
  }, [deferredRunsSearch, monitoringCards]);
  const runsSelectedCard = useMemo(
    () => monitoringCards.find((card) => card.server.server_id === runsSelectedServerId) ?? monitoringCards[0] ?? null,
    [monitoringCards, runsSelectedServerId]
  );
  const runsSelectedServer = runsSelectedCard?.server ?? null;
  const runsSelectedLatestMetric = runsSelectedCard?.latest_metric ?? null;
  const runsSelectedCollectorIssues = useMemo(
    () => fleetMonitoring.collector_issues.filter((collector) => collector.status !== "ok" && collector.status !== "healthy").slice(0, 4),
    [fleetMonitoring.collector_issues]
  );
  const runsSelectedHotspots = useMemo(
    () =>
      [...fleetMonitoring.failing_components, ...fleetMonitoring.hot_components]
        .filter((component, index, all) => all.findIndex((entry) => entry.component_id === component.component_id) === index)
        .filter((component) => component.server_id === runsSelectedServerId)
        .slice(0, 6),
    [fleetMonitoring.failing_components, fleetMonitoring.hot_components, runsSelectedServerId]
  );
  const selectedMonitoringCard = useMemo(
    () => monitoringCards.find((card) => card.server.server_id === selectedServerId) ?? monitoringCards[0] ?? null,
    [monitoringCards, selectedServerId]
  );
  const selectedMonitoringServer = selectedMonitoringCard?.server ?? selectedServer ?? null;
  const selectedMonitoringMetric = selectedMonitoringCard?.latest_metric ?? (selectedMonitoringServer ? serverMetricMap.get(selectedMonitoringServer.server_id) ?? null : null);
  const selectedServerHotspots = useMemo(
    () =>
      [...fleetMonitoring.failing_components, ...fleetMonitoring.hot_components]
        .filter((component, index, all) => all.findIndex((entry) => entry.component_id === component.component_id) === index)
        .filter((component) => component.server_id === selectedServerId)
        .slice(0, 6),
    [fleetMonitoring.failing_components, fleetMonitoring.hot_components, selectedServerId]
  );
  const selectedServerRuns = useMemo(
    () =>
      [...dashboard.recent_runs]
        .filter((run) => run.server_id === selectedServerId)
        .sort((left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime())
        .slice(0, 5),
    [dashboard.recent_runs, selectedServerId]
  );
  const selectedServerWorkflowRuns = useMemo(
    () =>
      [...dashboard.workflows]
        .filter((workflow) => workflow.server_id === selectedServerId)
        .sort((left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime())
        .slice(0, 5),
    [dashboard.workflows, selectedServerId]
  );
  const selectedServerTaskOptions = useMemo(
    () => dashboard.allowed_tasks.filter((task) => isTaskSupported(task.name, selectedServer)),
    [dashboard.allowed_tasks, selectedServer]
  );
  const selectedServerWorkflowOptions = useMemo(
    () =>
      dashboard.workflow_templates.filter((workflow) =>
        workflow.steps.every((step) => isTaskSupported(step, selectedServer))
      ),
    [dashboard.workflow_templates, selectedServer]
  );

  const overlayOpen = controlsOpen && activeNav === "Dashboard";
  const activeAlertCount = alerts.filter((alert) => alert.state !== "resolved").length;

  function exportTrackerDetails(format: "pdf" | "json" | "csv") {
    if (!nodeDetail || !primaryServer) {
      setTrackerExportMessage("Select a server before exporting.");
      return;
    }

    const safeBase = `${primaryServer.server_name || primaryServer.server_id}-tracker-details`.replace(/[^\w.-]+/g, "_").slice(0, 120);
    const rows = trackerExportRows(nodeDetail, primaryServer);

    if (format === "json") {
      const payload = {
        exported_at: new Date().toISOString(),
        server: primaryServer,
        node_detail: nodeDetail,
      };
      downloadBlobFile(`${safeBase}.json`, new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
      setTrackerExportMessage("Tracker JSON downloaded.");
      return;
    }

    if (format === "csv") {
      const csv = [["Field", "Value"], ...rows]
        .map((entry) => entry.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(","))
        .join("\n");
      downloadBlobFile(`${safeBase}.csv`, new Blob([csv], { type: "text/csv;charset=utf-8" }));
      setTrackerExportMessage("Tracker CSV downloaded.");
      return;
    }

    const doc = new jsPDF({ unit: "pt", format: "a4" });
    doc.setFontSize(18);
    doc.text(primaryServer.server_name, 40, 40);
    doc.setFontSize(10);
    doc.text(`Generated ${formatDateTime(new Date().toISOString())}`, 40, 58);
    autoTable(doc, {
      startY: 76,
      head: [["Field", "Value"]],
      body: rows,
      styles: { fontSize: 9, cellPadding: 6 },
      headStyles: { fillColor: [11, 91, 102] },
      theme: "grid",
    });
    doc.save(`${safeBase}.pdf`);
    setTrackerExportMessage("Tracker PDF downloaded.");
  }

  function exportAnalyticsDetails(format: "pdf" | "json" | "csv") {
    const payload = {
      exported_at: new Date().toISOString(),
      period: analyticsPeriod,
      filters: {
        group: analyticsGroupFilter,
        platform: analyticsPlatformFilter,
        primary_server: analyticsServer?.server_id ?? null,
        compare_server: analyticsCompareServer?.server_id ?? null,
      },
      overview: analyticsOverviewCards,
      regressions: analyticsRegressions,
      comparison: analyticsComparisonRows.map((row) => ({
        label: row.label,
        left: row.left,
        right: row.right,
        delta: row.left !== null && row.right !== null ? row.left - row.right : null,
      })),
      trend_points: analyticsHistory.points,
    };

    const safeBase = `analytics-${analyticsPeriod.toLowerCase()}-${new Date().toISOString().slice(0, 10)}`;
    const rows: Array<[string, string, string, string]> = analyticsComparisonRows.map((row) => [
      row.label,
      formatComparisonValue(row.left, row.suffix),
      formatComparisonValue(row.right, row.suffix),
      row.left !== null && row.right !== null ? formatComparisonValue(row.left - row.right, row.suffix) : "Not reported",
    ]);

    if (format === "json") {
      downloadBlobFile(`${safeBase}.json`, new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
      setAnalyticsExportMessage("Analytics JSON downloaded.");
      return;
    }

    if (format === "csv") {
      const csv = [["Metric", "Primary", "Compare", "Delta"], ...rows]
        .map((entry) => entry.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(","))
        .join("\n");
      downloadBlobFile(`${safeBase}.csv`, new Blob([csv], { type: "text/csv;charset=utf-8" }));
      setAnalyticsExportMessage("Analytics CSV downloaded.");
      return;
    }

    const doc = new jsPDF({ unit: "pt", format: "a4" });
    doc.setFontSize(18);
    doc.text("Prometheus Analytics Report", 40, 40);
    doc.setFontSize(10);
    doc.text(`Generated ${formatDateTime(new Date().toISOString())}`, 40, 58);
    doc.text(`Period ${analyticsPeriod} | Group ${analyticsGroupFilter} | Platform ${analyticsPlatformFilter}`, 40, 74);
    autoTable(doc, {
      startY: 92,
      head: [["Metric", analyticsServer?.server_name ?? "Primary", analyticsCompareServer?.server_name ?? "Compare", "Delta"]],
      body: rows,
      styles: { fontSize: 9, cellPadding: 6 },
      headStyles: { fillColor: [11, 91, 102] },
      theme: "grid",
    });
    doc.save(`${safeBase}.pdf`);
    setAnalyticsExportMessage("Analytics PDF downloaded.");
  }

  useEffect(() => {
    if (activeNav !== "Servers" && trackerDetailOpen) {
      setTrackerDetailOpen(false);
    }
  }, [activeNav, trackerDetailOpen]);

  useEffect(() => {
    if (!runsSelectedServerId && monitoringCards.length > 0) {
      setRunsSelectedServerId(monitoringCards[0].server.server_id);
    }
  }, [monitoringCards, runsSelectedServerId]);

  useEffect(() => {
    if (!workflowSelectedServerId && dashboard.servers.length > 0) {
      setWorkflowSelectedServerId(dashboard.servers[0].server_id);
    }
  }, [dashboard.servers, workflowSelectedServerId]);

  useEffect(() => {
    if (!analyticsServerId && filteredAnalyticsServers.length > 0) {
      setAnalyticsServerId(filteredAnalyticsServers[0].server_id);
    }
  }, [analyticsServerId, filteredAnalyticsServers]);

  useEffect(() => {
    if ((!analyticsCompareServerId || analyticsCompareServerId === analyticsServerId) && filteredAnalyticsServers.length > 1) {
      const fallback = filteredAnalyticsServers.find((server) => server.server_id !== analyticsServerId);
      if (fallback) {
        setAnalyticsCompareServerId(fallback.server_id);
      }
    }
  }, [analyticsCompareServerId, analyticsServerId, filteredAnalyticsServers]);

  useEffect(() => {
    if (activeNav !== "Runs" && runsDetailOpen) {
      setRunsDetailOpen(false);
    }
  }, [activeNav, runsDetailOpen]);

  useEffect(() => {
    if (activeNav !== "Workflows" && workflowDetailOpen) {
      setWorkflowDetailOpen(false);
    }
  }, [activeNav, workflowDetailOpen]);

  useEffect(() => {
    if (!trackerExportMessage) {
      return;
    }
    const timer = window.setTimeout(() => setTrackerExportMessage(null), 3000);
    return () => window.clearTimeout(timer);
  }, [trackerExportMessage]);

  useEffect(() => {
    if (!analyticsExportMessage) {
      return;
    }
    const timer = window.setTimeout(() => setAnalyticsExportMessage(null), 3000);
    return () => window.clearTimeout(timer);
  }, [analyticsExportMessage]);

  useEffect(() => {
    if (!selectedServerId) {
      setNodeDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    void fetchNodeDetail(selectedServerId)
      .then((payload) => {
        if (!cancelled) {
          setNodeDetail(payload);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setDetailLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [fetchNodeDetail, selectedServerId]);

  useEffect(() => {
    if (!selectedRunId) {
      setRunDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    void fetchRunDetail(selectedRunId)
      .then((payload) => {
        if (!cancelled) {
          setRunDetail(payload);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setDetailLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [fetchRunDetail, selectedRunId]);

  useEffect(() => {
    if (!overlayOpen) return;

    const previousActive = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focusTarget =
      overlayPanelRef.current?.querySelector<HTMLElement>("button, select, input, [tabindex]:not([tabindex='-1'])") ?? overlayPanelRef.current;
    focusTarget?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setControlsOpen(false);
      }
    };

    window.addEventListener("keydown", handleKeyDown);

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      previousActive?.focus();
    };
  }, [overlayOpen]);

  return (
    <div className="app-shell min-h-screen px-0 py-0">
      <DragonCompanionOverlay />
      <div className="app-shell__inner min-h-screen w-full rounded-none border-0 px-6 py-6 shadow-none lg:px-7 lg:py-7">
        <header className="flex flex-col gap-5 pb-6 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-center">
            <nav className="app-nav-surface rounded-full p-1.5">
              <div className="flex flex-wrap items-center gap-1">
                {NAV_ITEMS.map((item) => (
                  <button
                    key={item}
                    onClick={() => setActiveNav(item)}
                    aria-current={activeNav === item ? "page" : undefined}
                    className={activeNav === item ? "clone-nav-pill clone-nav-pill--active" : "clone-nav-pill"}
                  >
                    {item}
                  </button>
                ))}
              </div>
            </nav>
          </div>

          <div className="flex items-center gap-3 self-end xl:self-auto">
            <button
              ref={searchButtonRef}
              className="mini-icon-button"
              aria-label="Open tracker search"
              onClick={() => setActiveNav("Servers")}
            >
              <span className="icon-search" />
            </button>
            <button className="mini-icon-button" aria-label="Open live events" onClick={() => setActiveNav("Analytics")}>
              <span className="icon-bell" />
            </button>
            <button
              ref={profileButtonRef}
              className="clone-profile-pill"
              onClick={() => setControlsOpen(true)}
              aria-haspopup="dialog"
              aria-expanded={overlayOpen}
              aria-controls="execution-console"
            >
              <span className="clone-profile-avatar">P</span>
              <span className="text-left">
                <span className="clone-profile-title block text-[1rem] font-semibold">Prometheus</span>
                <span className="clone-profile-status block text-[0.72rem] uppercase tracking-[0.2em]">{connectionLabel(connection)}</span>
              </span>
            </button>
          </div>
        </header>

        {error ? <div className="clone-banner clone-banner--warn">Controller unavailable: {error}. Showing no live infrastructure data until the backend reconnects.</div> : null}
        {!error && isLoading ? <div className="clone-banner">Connecting to the controller and waiting for live infrastructure data...</div> : null}

        <main className="mt-6">
          {activeNav === "Dashboard" ? (
            <DashboardView
              dashboard={dashboard}
              primaryServer={primaryServer}
              openControls={() => setControlsOpen(true)}
              lastUpdated={lastUpdated}
              currentTime={currentTime}
              period={period}
              setPeriod={setPeriod}
              agentEnrollments={agentEnrollments}
              createAgentEnrollment={createAgentEnrollment}
              revokeAgentEnrollment={revokeAgentEnrollment}
              fetchAgentInstallCommand={fetchAgentInstallCommand}
            />
          ) : null}

          {activeNav === "Servers" ? (
            <div className="space-y-5">
              <ShellPanel title="Servers" subtitle="Choose a machine first, then inspect it, monitor it, or launch validation workflows from one place.">
                <div className="mb-5 flex items-center justify-between gap-3">
                  <div className="clone-search-input">
                    <span className="icon-search icon-search--small" />
                    <input value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder="Search servers, IPs, groups, tags, platforms" />
                  </div>
                  <span className="clone-delta-pill">{filteredServers.length} tracked</span>
                </div>

                {!trackerDetailOpen ? (
                  <div className="tracker-grid">
                    {filteredServers.map((server) => {
                      const metric = serverMetricMap.get(server.server_id);
                      return (
                        <article key={server.server_id} className="tracker-card tracker-card--compact">
                          <button
                            type="button"
                            className="w-full text-left"
                            onClick={() => openServerWorkspace(server.server_id, "overview")}
                          >
                            <div className="tracker-card__top">
                              <div>
                                <p className="tracker-card__name">{server.server_name}</p>
                                <p className="tracker-card__subtle">{server.platform_label ?? server.group}</p>
                              </div>
                              <span className={statusClass(server.health)}>{server.health}</span>
                            </div>
                            <div className="tracker-card__meta">
                              <span>{server.group}</span>
                              <span>{server.status}</span>
                              <span>{server.primary_ip ?? server.tags[0] ?? "untagged"}</span>
                            </div>
                            <div className="tracker-card__stats">
                              <div className="tracker-card__stat"><span>CPU</span><strong>{compactStat(metric?.cpu)}</strong></div>
                              <div className="tracker-card__stat"><span>Memory</span><strong>{compactStat(metric?.memory)}</strong></div>
                              <div className="tracker-card__stat"><span>Disk</span><strong>{compactStat(metric?.disk)}</strong></div>
                              <div className="tracker-card__stat"><span>Temp</span><strong>{compactStat(metric?.temperature_c, "C")}</strong></div>
                              <div className="tracker-card__stat"><span>Fan</span><strong>{compactStat(metric?.fan_speed_rpm, " RPM")}</strong></div>
                            </div>
                            <div className="tracker-card__foot">
                              <span>{server.primary_ip ? "Primary IP" : "Last heartbeat"}</span>
                              <strong>{server.primary_ip ?? (server.last_heartbeat_at ? formatDateTime(server.last_heartbeat_at) : "Not reported")}</strong>
                            </div>
                          </button>
                          <div className="mt-4 flex flex-wrap gap-2">
                            <button
                              type="button"
                              className="tracker-export-button"
                              onClick={(event) => {
                                event.preventDefault();
                                event.stopPropagation();
                                openServerWorkspace(server.server_id, "overview");
                              }}
                            >
                              Details
                            </button>
                            <button
                              type="button"
                              className="tracker-export-button"
                              onClick={(event) => {
                                event.preventDefault();
                                event.stopPropagation();
                                openServerWorkspace(server.server_id, "monitor");
                              }}
                            >
                              Monitor
                            </button>
                            <button
                              type="button"
                              className="tracker-export-button"
                              onClick={(event) => {
                                event.preventDefault();
                                event.stopPropagation();
                                openServerWorkspace(server.server_id, "launch");
                              }}
                            >
                              Launch
                            </button>
                            <button
                              type="button"
                              className="tracker-export-button"
                              onClick={(event) => {
                                event.preventDefault();
                                event.stopPropagation();
                                void openServerTerminal(server.server_id);
                              }}
                            >
                              Terminal
                            </button>
                          </div>
                        </article>
                      );
                    })}
                    {!filteredServers.length ? <div className="clone-empty-state">No servers matched your current search.</div> : null}
                  </div>
                ) : primaryServer ? (
                  <div className="tracker-detail-shell">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <button
                        type="button"
                        className="tracker-back"
                        onClick={() => {
                          setTrackerDetailOpen(false);
                          setServerWorkspaceSection("overview");
                        }}
                      >
                        <span className="tracker-back__icon" aria-hidden="true" />
                        Back to fleet
                      </button>
                      <div className="flex flex-wrap items-center justify-end gap-2">
                        <div className="clone-period-toggle">
                          {([
                            ["overview", "Overview"],
                            ["monitor", "Monitor"],
                            ["launch", "Launch"],
                            ["terminal", "Terminal"],
                          ] as const).map(([value, label]) => (
                            <button
                              key={value}
                              type="button"
                              className={serverWorkspaceSection === value ? "clone-period-pill clone-period-pill--active" : "clone-period-pill"}
                              onClick={() => setServerWorkspaceSection(value)}
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                        <button type="button" className="tracker-export-button" onClick={() => exportTrackerDetails("pdf")}>PDF</button>
                        <button type="button" className="tracker-export-button" onClick={() => exportTrackerDetails("csv")}>CSV</button>
                        <button type="button" className="tracker-export-button" onClick={() => exportTrackerDetails("json")}>JSON</button>
                      </div>
                    </div>

                    <div className="tracker-detail-hero">
                      <div>
                        <p className="tracker-detail-hero__eyebrow">{primaryServer.group}</p>
                        <h2 className="tracker-detail-hero__title">{primaryServer.server_name}</h2>
                        <p className="tracker-detail-hero__copy">
                          {detailValue(nodeDetail?.system_identity.hostname ?? primaryServer.server_id)} on{" "}
                          {detailValue(nodeDetail?.system_identity.os ?? primaryServer.platform_label ?? primaryServer.platform_family)}
                        </p>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={statusClass(primaryServer.status)}>{statusLabel(primaryServer.status)}</span>
                        <span className={statusClass(primaryServer.health)}>{primaryServer.health}</span>
                        <span className="clone-soft-pill">{primaryServer.primary_ip ?? "No primary IP"}</span>
                      </div>
                    </div>

                    {serverWorkspaceSection === "overview" ? (
                      detailLoading && !nodeDetail ? (
                        <div className="clone-empty-state">Loading live server overview...</div>
                      ) : nodeDetail ? (
                        <div className="space-y-4">
                          <section className="space-y-3">
                            <p className="clone-section-title">Overview</p>
                            <div className="tracker-section-grid">
                              <div className="clone-data-chip"><span>Status</span><strong>{detailValue(primaryServer.status)}</strong></div>
                              <div className="clone-data-chip"><span>Health</span><strong>{detailValue(nodeDetail.hardware_overview.overall_health ?? primaryServer.health)}</strong></div>
                              <div className="clone-data-chip"><span>Last heartbeat</span><strong>{primaryServer.last_heartbeat_at ? formatDateTime(primaryServer.last_heartbeat_at) : "Not reported"}</strong></div>
                              <div className="clone-data-chip"><span>Last telemetry</span><strong>{primaryServer.last_telemetry_at ? formatDateTime(primaryServer.last_telemetry_at) : "Not reported"}</strong></div>
                              <div className="clone-data-chip"><span>Inventory refresh</span><strong>{primaryServer.last_inventory_refresh_at ? formatDateTime(primaryServer.last_inventory_refresh_at) : "Not reported"}</strong></div>
                              <div className="clone-data-chip"><span>Last task activity</span><strong>{primaryServer.last_task_activity_at ? formatDateTime(primaryServer.last_task_activity_at) : "Not reported"}</strong></div>
                              <div className="clone-data-chip"><span>Tracked components</span><strong>{nodeDetail.hardware_inventory.length}</strong></div>
                              <div className="clone-data-chip"><span>Open alerts</span><strong>{nodeDetail.alerts.filter((alert) => alert.state !== "resolved").length}</strong></div>
                              <div className="clone-data-chip"><span>Recent task runs</span><strong>{selectedServerRuns.length}</strong></div>
                              <div className="clone-data-chip"><span>Recent workflows</span><strong>{selectedServerWorkflowRuns.length}</strong></div>
                            </div>
                          </section>

                          <section className="space-y-3">
                            <p className="clone-section-title">Identity</p>
                            <div className="tracker-section-grid">
                              <div className="tracker-section-card"><span>OS / platform</span><strong>{detailValue(nodeDetail.system_identity.os ?? nodeDetail.system_identity.platform)}</strong></div>
                              <div className="tracker-section-card"><span>Hostname</span><strong>{detailValue(nodeDetail.system_identity.hostname)}</strong></div>
                              <div className="tracker-section-card"><span>Architecture</span><strong>{detailValue(nodeDetail.system_identity.architecture)}</strong></div>
                              <div className="tracker-section-card"><span>Kernel / build</span><strong>{detailValue(nodeDetail.system_identity.kernel ?? nodeDetail.system_identity.build)}</strong></div>
                              <div className="tracker-section-card"><span>Server ID</span><strong>{detailValue(primaryServer.server_id)}</strong></div>
                              <div className="tracker-section-card"><span>Vendor / model</span><strong>{detailValue([nodeDetail.system_identity.vendor, nodeDetail.system_identity.model].filter(Boolean).join(" / "))}</strong></div>
                              <div className="tracker-section-card"><span>Serial</span><strong>{detailValue(nodeDetail.system_identity.serial)}</strong></div>
                              <div className="tracker-section-card"><span>Board</span><strong>{detailValue(nodeDetail.system_identity.board)}</strong></div>
                              <div className="tracker-section-card"><span>Primary IP</span><strong>{detailValue(nodeDetail.network_identity.primary_ip ?? primaryServer.primary_ip)}</strong></div>
                              <div className="tracker-section-card"><span>Agent version</span><strong>{detailValue(nodeDetail.agent_identity.version)}</strong></div>
                            </div>
                          </section>

                          <section className="space-y-3">
                            <p className="clone-section-title">Firmware / BMC / Network</p>
                            <div className="tracker-section-grid">
                              <div className="tracker-section-card"><span>BIOS vendor</span><strong>{detailValue(nodeDetail.firmware_identity.bios_vendor)}</strong></div>
                              <div className="tracker-section-card"><span>BIOS version</span><strong>{detailValue(nodeDetail.firmware_identity.bios_version)}</strong></div>
                              <div className="tracker-section-card"><span>BMC present</span><strong>{detailValue(nodeDetail.bmc_identity.present)}</strong></div>
                              <div className="tracker-section-card"><span>BMC / IPMI address</span><strong>{detailValue(nodeDetail.bmc_identity.address ?? primaryServer.bmc_address)}</strong></div>
                              <div className="tracker-section-card"><span>Gateway</span><strong>{detailValue(nodeDetail.network_identity.gateway)}</strong></div>
                              <div className="tracker-section-card"><span>DNS</span><strong>{detailValue(nodeDetail.network_identity.dns_servers.join(" / "))}</strong></div>
                              <div className="tracker-section-card"><span>Interfaces</span><strong>{detailValue(nodeDetail.network_identity.interfaces.length)}</strong></div>
                              <div className="tracker-section-card"><span>All addresses</span><strong>{detailValue(nodeDetail.platform_addresses.join(" / "))}</strong></div>
                            </div>
                          </section>

                          <div className="grid gap-5 xl:grid-cols-2">
                            <ShellPanel title="Recent Alerts & Advisories" subtitle="What currently needs attention on this server.">
                              <div className="space-y-3">
                                {nodeDetail.alerts.slice(0, 5).map((alert) => (
                                  <div key={alert.alert_id} className="clone-list-row">
                                    <div>
                                      <p className="font-semibold text-[#262626]">{nice(alert.signal)}</p>
                                      <p className="mt-1 text-sm text-[#a3a3a3]">{alert.message ?? "No alert message provided"}</p>
                                    </div>
                                    <div className="text-sm text-[#737373]">{alert.updated_at ?? alert.created_at ? formatDateTime(alert.updated_at ?? alert.created_at ?? "") : "Not reported"}</div>
                                    <div><span className={statusClass(alert.state === "resolved" ? "completed" : alert.severity)}>{nice(alert.severity)}</span></div>
                                  </div>
                                ))}
                                {nodeDetail.alerts.length === 0 ? <div className="clone-empty-state">No alerts or advisories are active for this server.</div> : null}
                              </div>
                            </ShellPanel>

                            <ShellPanel title="Recent Runs" subtitle="Latest validation and workflow activity for this server.">
                              <div className="space-y-3">
                                {selectedServerRuns.map((run) => (
                                  <div key={run.task_id} className="clone-list-row">
                                    <div>
                                      <p className="font-semibold text-[#262626]">{nice(run.task)}</p>
                                      <p className="mt-1 text-sm text-[#a3a3a3]">{formatDateTime(run.updated_at)}</p>
                                    </div>
                                    <div className="text-sm text-[#737373]">Score {run.score ?? "--"}</div>
                                    <div><span className={statusClass(run.status)}>{statusLabel(run.status)}</span></div>
                                  </div>
                                ))}
                                {selectedServerWorkflowRuns.map((workflow) => (
                                  <div key={workflow.workflow_id} className="clone-list-row">
                                    <div>
                                      <p className="font-semibold text-[#262626]">{nice(workflow.workflow)}</p>
                                      <p className="mt-1 text-sm text-[#a3a3a3]">{formatDateTime(workflow.updated_at)}</p>
                                    </div>
                                    <div className="text-sm text-[#737373]">Workflow</div>
                                    <div><span className={statusClass(workflow.status)}>{statusLabel(workflow.status)}</span></div>
                                  </div>
                                ))}
                                {selectedServerRuns.length === 0 && selectedServerWorkflowRuns.length === 0 ? (
                                  <div className="clone-empty-state">No test or workflow activity has been recorded for this server yet.</div>
                                ) : null}
                              </div>
                            </ShellPanel>
                          </div>
                        </div>
                      ) : (
                        <div className="clone-empty-state">No live server overview is available yet.</div>
                      )
                    ) : null}
                    {serverWorkspaceSection === "monitor" ? (
                      <div className="space-y-5">
                        <div className="tracker-section-grid">
                          <div className="clone-data-chip"><span>CPU</span><strong>{compactStat(selectedMonitoringMetric?.cpu)}</strong></div>
                          <div className="clone-data-chip"><span>Memory</span><strong>{compactStat(selectedMonitoringMetric?.memory)}</strong></div>
                          <div className="clone-data-chip"><span>Disk</span><strong>{compactStat(selectedMonitoringMetric?.disk)}</strong></div>
                          <div className="clone-data-chip"><span>Temperature</span><strong>{compactStat(selectedMonitoringMetric?.temperature_c, "C")}</strong></div>
                          <div className="clone-data-chip"><span>Fan speed</span><strong>{compactStat(selectedMonitoringMetric?.fan_speed_rpm, " RPM")}</strong></div>
                          <div className="clone-data-chip"><span>Collector gaps</span><strong>{runsSelectedCollectorIssues.length}</strong></div>
                        </div>

                        <div className="grid gap-5 xl:grid-cols-2">
                          <ShellPanel title="Selected Server Live Posture" subtitle="Current monitoring posture for the selected server.">
                            {selectedMonitoringMetric ? (
                              <ResourceUsageChart
                                metrics={[
                                  {
                                    ...selectedMonitoringMetric,
                                    serverName: selectedMonitoringServer?.server_name ?? primaryServer.server_name,
                                  },
                                ]}
                              />
                            ) : (
                              <div className="clone-empty-state">No live monitoring metric has been reported for this server yet.</div>
                            )}
                          </ShellPanel>
                          <ComponentCoverageChart summaries={fleetMonitoring.component_summaries} />
                        </div>

                        <div className="grid gap-5 xl:grid-cols-2">
                          {cpuHistory ? <FleetMetricHistoryChart series={cpuHistory} /> : null}
                          {memoryHistory ? <FleetMetricHistoryChart series={memoryHistory} /> : null}
                          {storageHistory ? <FleetMetricHistoryChart series={storageHistory} /> : null}
                          {networkHistory ? <FleetMetricHistoryChart series={networkHistory} /> : null}
                          {thermalHistory ? <FleetMetricHistoryChart series={thermalHistory} /> : null}
                          {fanHistory ? <FleetMetricHistoryChart series={fanHistory} /> : null}
                          {gpuHistory ? <FleetMetricHistoryChart series={gpuHistory} /> : null}
                        </div>

                        <div className="grid gap-5 xl:grid-cols-2">
                          <ShellPanel title="Hot Components" subtitle="Thermal, failure, and component risk signals on this server.">
                            <div className="space-y-3">
                              {selectedServerHotspots.map((component) => (
                                <div key={component.component_id} className="clone-list-row">
                                  <div>
                                      <p className="font-semibold text-[#262626]">{component.name}</p>
                                      <p className="mt-1 text-sm text-[#a3a3a3]">{nice(component.component_type)}</p>
                                  </div>
                                    <div className="text-sm text-[#737373]">{detailValue(component.metadata.temperature_c ?? component.metadata.health)}</div>
                                  <div><span className={statusClass(component.status)}>{nice(component.status)}</span></div>
                                </div>
                              ))}
                              {!selectedServerHotspots.length ? <div className="clone-empty-state">No hot or failing components are currently flagged on this server.</div> : null}
                            </div>
                          </ShellPanel>
                          <ShellPanel title="Collector Coverage" subtitle="Visibility gaps and unsupported sensors surfaced from the monitoring plane.">
                            <div className="space-y-3">
                              {runsSelectedCollectorIssues.map((collector) => (
                                <div key={`${collector.collector_name}-${collector.recorded_at}`} className="clone-list-row">
                                  <div>
                                      <p className="font-semibold text-[#262626]">{nice(collector.collector_name)}</p>
                                      <p className="mt-1 text-sm text-[#a3a3a3]">{collector.message ?? "No collector message provided"}</p>
                                  </div>
                                    <div className="text-sm text-[#737373]">{formatDateTime(collector.recorded_at)}</div>
                                  <div><span className={statusClass(collector.status)}>{nice(collector.status)}</span></div>
                                </div>
                              ))}
                              {!runsSelectedCollectorIssues.length ? <div className="clone-empty-state">Collector coverage is healthy across the current fleet snapshot.</div> : null}
                            </div>
                          </ShellPanel>
                        </div>
                      </div>
                    ) : null}
                    {serverWorkspaceSection === "launch" ? (
                      <div className="space-y-5">
                        <div className="tracker-section-grid">
                          <div className="clone-data-chip"><span>Runnable tests</span><strong>{selectedServerTaskOptions.length}</strong></div>
                          <div className="clone-data-chip"><span>Runnable workflows</span><strong>{selectedServerWorkflowOptions.length}</strong></div>
                          <div className="clone-data-chip"><span>Capabilities</span><strong>{primaryServer.capabilities.length}</strong></div>
                          <div className="clone-data-chip"><span>Platform</span><strong>{detailValue(primaryServer.platform_label ?? primaryServer.platform_family)}</strong></div>
                          <div className="clone-data-chip"><span>Primary IP</span><strong>{detailValue(primaryServer.primary_ip)}</strong></div>
                          <div className="clone-data-chip"><span>BMC/IPMI</span><strong>{detailValue(primaryServer.bmc_address)}</strong></div>
                        </div>

                        {actionError ? <div className="clone-warning-banner">{actionError}</div> : null}
                        {actionSuccess ? <div className="clone-success-banner">{actionSuccess}</div> : null}

                        <div className="grid gap-5 xl:grid-cols-2">
                          <ShellPanel title="Quick Tests" subtitle="Single benchmarks and validation checks available on this server right now.">
                            <div className="space-y-3">
                              {selectedServerTaskOptions.map((task) => (
                                <article key={task.name} className="clone-stack-card">
                                  <div className="flex items-start justify-between gap-3">
                                    <div>
                                      <p className="text-[1rem] font-bold text-[#262626]">{nice(task.name)}</p>
                                      <p className="mt-2 text-sm text-[#737373]">{task.summary}</p>
                                    </div>
                                    <span className="clone-soft-pill">{task.default_timeout_seconds}s</span>
                                  </div>
                                  <div className="mt-4 flex items-center justify-between gap-3">
                                    <span className="text-sm text-[#a3a3a3]">Supported on {primaryServer.platform_label ?? primaryServer.group}</span>
                                    <button
                                      type="button"
                                      className="clone-secondary-action"
                                      disabled={actionPending}
                                      onClick={() => void triggerTask({ server_id: primaryServer.server_id, task: task.name, requested_by: "web-ui" })}
                                    >
                                      {actionPending ? "Running..." : "Run test"}
                                    </button>
                                  </div>
                                </article>
                              ))}
                              {!selectedServerTaskOptions.length ? <div className="clone-empty-state">No supported single tests are available for this server.</div> : null}
                            </div>
                          </ShellPanel>

                          <ShellPanel title="Workflow Templates" subtitle="Multi-step validation and benchmarking flows that match this server's capabilities.">
                            <div className="space-y-3">
                              {selectedServerWorkflowOptions.map((workflow) => (
                                <article key={workflow.name} className="clone-stack-card">
                                  <div className="flex items-start justify-between gap-3">
                                    <div>
                                      <p className="text-[1rem] font-bold text-[#262626]">{nice(workflow.name)}</p>
                                      <p className="mt-2 text-sm text-[#737373]">{workflow.summary}</p>
                                    </div>
                                    <span className="clone-soft-pill">{workflow.steps.length} steps</span>
                                  </div>
                                  <div className="mt-4 flex flex-wrap gap-2">
                                    {workflow.steps.map((step) => (
                                      <span key={step} className="clone-soft-pill">
                                        {nice(step)}
                                      </span>
                                    ))}
                                  </div>
                                  <div className="mt-4 flex items-center justify-between gap-3">
                                    <span className="text-sm text-[#a3a3a3]">Every step is supported on this host</span>
                                    <button
                                      type="button"
                                      className="clone-primary-action"
                                      disabled={actionPending}
                                      onClick={() => void triggerWorkflow({ server_id: primaryServer.server_id, workflow: workflow.name, requested_by: "web-ui" })}
                                    >
                                      {actionPending ? "Dispatching..." : "Run workflow"}
                                    </button>
                                  </div>
                                </article>
                              ))}
                              {!selectedServerWorkflowOptions.length ? <div className="clone-empty-state">No workflow templates fully match this server's capabilities yet.</div> : null}
                            </div>
                          </ShellPanel>
                        </div>

                        <div className="grid gap-5 xl:grid-cols-2">
                          <ShellPanel title="Recent Workflow Runs" subtitle="Latest workflow executions for this server.">
                            <div className="space-y-3">
                              {selectedServerWorkflowRuns.map((workflow) => (
                                <div key={workflow.workflow_id} className="clone-list-row">
                                  <div>
                                     <p className="font-semibold text-[#262626]">{nice(workflow.workflow)}</p>
                                     <p className="mt-1 text-sm text-[#a3a3a3]">Step {workflow.current_step_index + 1}/{Math.max(1, workflow.steps.length)}</p>
                                  </div>
                                   <div className="text-sm text-[#737373]">{formatDateTime(workflow.updated_at)}</div>
                                  <div><span className={statusClass(workflow.status)}>{statusLabel(workflow.status)}</span></div>
                                  <div>
                                    {workflow.status === "pending" || workflow.status === "running" ? (
                                      <button
                                        type="button"
                                        className="text-sm font-semibold text-[#8b2c2c]"
                                        disabled={actionPending}
                                        onClick={() => void cancelWorkflow(workflow.workflow_id)}
                                      >
                                        Cancel
                                      </button>
                                    ) : (
                                       <span className="text-sm text-[#a3a3a3]">-</span>
                                    )}
                                  </div>
                                </div>
                              ))}
                              {!selectedServerWorkflowRuns.length ? <div className="clone-empty-state">No workflow runs recorded for this server yet.</div> : null}
                            </div>
                          </ShellPanel>

                          <ShellPanel title="Recent Test Runs" subtitle="Latest task and benchmark executions for this same server.">
                            <div className="space-y-3">
                              {selectedServerRuns.map((run) => (
                                <div key={run.task_id} className="clone-list-row">
                                  <div>
                                     <p className="font-semibold text-[#262626]">{nice(run.task)}</p>
                                     <p className="mt-1 text-sm text-[#a3a3a3]">{formatDateTime(run.updated_at)}</p>
                                  </div>
                                   <div className="text-sm text-[#737373]">Score {run.score ?? "--"}</div>
                                  <div><span className={statusClass(run.status)}>{statusLabel(run.status)}</span></div>
                                </div>
                              ))}
                              {!selectedServerRuns.length ? <div className="clone-empty-state">No task runs recorded for this server yet.</div> : null}
                            </div>
                          </ShellPanel>
                        </div>
                      </div>
                    ) : null}
                    {serverWorkspaceSection === "terminal" ? (
                      <div className="space-y-5">
                        <div className="tracker-section-grid">
                          <div className="clone-data-chip"><span>Access</span><strong>Admin only</strong></div>
                          <div className="clone-data-chip"><span>Session</span><strong>{terminalSession?.status ?? (terminalConnecting ? "connecting" : "not opened")}</strong></div>
                          <div className="clone-data-chip"><span>Shell</span><strong>{terminalSession?.shell_type ?? "Pending"}</strong></div>
                          <div className="clone-data-chip"><span>Last agent seen</span><strong>{terminalSession?.last_agent_seen_at ? formatDateTime(terminalSession.last_agent_seen_at) : "Waiting"}</strong></div>
                          <div className="clone-data-chip"><span>Last browser activity</span><strong>{terminalSession?.last_browser_seen_at ? formatDateTime(terminalSession.last_browser_seen_at) : "Not reported"}</strong></div>
                          <div className="clone-data-chip"><span>Transport</span><strong>Agent session</strong></div>
                        </div>

                        {terminalError ? <div className="clone-warning-banner">{terminalError}</div> : null}

                        <section className="terminal-shell">
                          <div className="terminal-shell__header">
                            <div>
                              <p className="terminal-shell__title">{primaryServer.server_name} terminal</p>
                              <p className="terminal-shell__subtitle">Connected through the Prometheus agent, with no SSH dependency.</p>
                            </div>
                            <div className="terminal-shell__actions">
                              <button
                                type="button"
                                className="clone-secondary-action"
                                onClick={() => setTerminalBuffer("")}
                              >
                                Clear viewport
                              </button>
                              <button
                                type="button"
                                className="clone-primary-action"
                                disabled={!terminalSession}
                                onClick={() => {
                                  if (!terminalSession) return;
                                  void closeTerminalSession(terminalSession.session_id).then((session) => {
                                    setTerminalSession(session);
                                  }).catch((requestError) => {
                                    setTerminalError(requestError instanceof Error ? requestError.message : "Unable to close terminal session.");
                                  });
                                }}
                              >
                                Close session
                              </button>
                            </div>
                          </div>

                          <div ref={terminalViewportRef} className="terminal-shell__viewport">
                            <pre className="terminal-shell__output">{terminalBuffer || (terminalConnecting ? "Opening agent-mediated shell..." : "No terminal output yet.")}</pre>
                          </div>

                          <div className="terminal-shell__composer">
                            <textarea
                              value={terminalInput}
                              onChange={(event) => setTerminalInput(event.target.value)}
                              className="terminal-shell__input"
                              placeholder={terminalSession ? "Type a command and press Run" : "Open a terminal session to start sending commands"}
                              onKeyDown={(event) => {
                                if (event.key === "Enter" && !event.shiftKey) {
                                  event.preventDefault();
                                  submitTerminalCommand();
                                }
                              }}
                            />
                            <button
                              type="button"
                              className="clone-primary-action"
                              disabled={!terminalSession || terminalConnecting}
                              onClick={() => submitTerminalCommand()}
                            >
                              Run
                            </button>
                          </div>
                        </section>
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <div className="clone-empty-state">No server is available to open right now.</div>
                )}
              </ShellPanel>
            </div>
          ) : null}

          {activeNav === "Tracker" ? (
            <div className="space-y-5">
              <ShellPanel title="Fleet Tracker" subtitle="Every connected machine lands here first as a live card, then expands into a full hardware and platform workspace.">
                <div className="mb-5 flex items-center justify-between gap-3">
                  <div className="clone-search-input">
                    <span className="icon-search icon-search--small" />
                    <input value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder="Search servers, groups, tags" />
                  </div>
                  <span className="clone-delta-pill">{filteredServers.length} tracked</span>
                </div>

                {!trackerDetailOpen ? (
                  <div className="tracker-grid">
                    {filteredServers.map((server) => {
                      const metric = serverMetricMap.get(server.server_id);
                      return (
                        <button
                          key={server.server_id}
                          type="button"
                          className="tracker-card"
                          onClick={() => {
                            setSelectedServerId(server.server_id);
                            setTrackerDetailOpen(true);
                          }}
                        >
                          <div className="tracker-card__top">
                            <div>
                              <p className="tracker-card__name">{server.server_name}</p>
                              <p className="tracker-card__subtle">{server.platform_label ?? server.group}</p>
                            </div>
                            <span className={statusClass(server.health)}>{server.health}</span>
                          </div>
                          <div className="tracker-card__meta">
                            <span>{server.group}</span>
                            <span>{server.status}</span>
                            <span>{server.primary_ip ?? server.tags[0] ?? "untagged"}</span>
                          </div>
                          <div className="tracker-card__stats">
                            <div className="tracker-card__stat"><span>CPU</span><strong>{compactStat(metric?.cpu)}</strong></div>
                            <div className="tracker-card__stat"><span>Memory</span><strong>{compactStat(metric?.memory)}</strong></div>
                            <div className="tracker-card__stat"><span>Disk</span><strong>{compactStat(metric?.disk)}</strong></div>
                            <div className="tracker-card__stat"><span>Temp</span><strong>{compactStat(metric?.temperature_c, "C")}</strong></div>
                          </div>
                          <div className="tracker-card__foot">
                            <span>{server.primary_ip ? "Primary IP" : "Last heartbeat"}</span>
                            <strong>{server.primary_ip ?? (server.last_heartbeat_at ? formatDateTime(server.last_heartbeat_at) : "Not reported")}</strong>
                          </div>
                        </button>
                      );
                    })}
                    {!filteredServers.length ? <div className="clone-empty-state">No servers matched your current search.</div> : null}
                  </div>
                ) : (
                  <div className="tracker-detail-shell">
                    <div className="flex items-center justify-between gap-3">
                      <button type="button" className="tracker-back" onClick={() => setTrackerDetailOpen(false)}>
                        <span className="tracker-back__icon" aria-hidden="true" />
                        Back to fleet
                      </button>
                      <div className="flex flex-wrap items-center justify-end gap-2">
                        <button type="button" className="tracker-export-button" onClick={() => exportTrackerDetails("pdf")}>PDF</button>
                        <button type="button" className="tracker-export-button" onClick={() => exportTrackerDetails("csv")}>CSV</button>
                        <button type="button" className="tracker-export-button" onClick={() => exportTrackerDetails("json")}>JSON</button>
                        <span className="clone-soft-pill">{primaryServer?.platform_label ?? "Tracker detail"}</span>
                      </div>
                    </div>
                    {trackerExportMessage ? <div className="clone-success-banner">{trackerExportMessage}</div> : null}

                    <div className="tracker-detail-hero">
                      <div>
                        <p className="tracker-detail-hero__eyebrow">{primaryServer?.group ?? "Server group"}</p>
                        <h2 className="tracker-detail-hero__title">{primaryServer?.server_name ?? "No server selected"}</h2>
                        <p className="tracker-detail-hero__copy">
                          {detailValue(nodeDetail?.system_identity.hostname ?? primaryServer?.server_id)} on {detailValue(nodeDetail?.system_identity.os ?? primaryServer?.platform_family)}
                        </p>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={statusClass(primaryServer?.status ?? "offline")}>{statusLabel(primaryServer?.status ?? "offline")}</span>
                        <span className={statusClass(primaryServer?.health ?? "FAIL")}>{primaryServer?.health ?? "Unknown"}</span>
                      </div>
                    </div>

                    {detailLoading && !nodeDetail ? <div className="clone-empty-state">Loading live server detail...</div> : null}

                    {nodeDetail ? (
                      <div className="space-y-4">
                        <section className="space-y-3">
                          <p className="clone-section-title">Overview</p>
                          <div className="tracker-section-grid">
                            <div className="clone-data-chip"><span>Status</span><strong>{detailValue(primaryServer?.status)}</strong></div>
                            <div className="clone-data-chip"><span>Health</span><strong>{detailValue(nodeDetail.hardware_overview.overall_health ?? primaryServer?.health)}</strong></div>
                            <div className="clone-data-chip"><span>Last heartbeat</span><strong>{primaryServer?.last_heartbeat_at ? formatDateTime(primaryServer.last_heartbeat_at) : "Not reported"}</strong></div>
                            <div className="clone-data-chip"><span>Last telemetry</span><strong>{primaryServer?.last_telemetry_at ? formatDateTime(primaryServer.last_telemetry_at) : "Not reported"}</strong></div>
                            <div className="clone-data-chip"><span>Inventory refresh</span><strong>{primaryServer?.last_inventory_refresh_at ? formatDateTime(primaryServer.last_inventory_refresh_at) : "Not reported"}</strong></div>
                            <div className="clone-data-chip"><span>Last task activity</span><strong>{primaryServer?.last_task_activity_at ? formatDateTime(primaryServer.last_task_activity_at) : "Not reported"}</strong></div>
                            <div className="clone-data-chip"><span>Tracked components</span><strong>{nodeDetail.hardware_inventory.length}</strong></div>
                            <div className="clone-data-chip"><span>Hot components</span><strong>{detailValue(nodeDetail.hardware_overview.hot_component_count ?? 0)}</strong></div>
                            <div className="clone-data-chip"><span>Failing components</span><strong>{detailValue(nodeDetail.hardware_overview.failing_component_count ?? 0)}</strong></div>
                            <div className="clone-data-chip"><span>Open alerts</span><strong>{nodeDetail.alerts.filter((alert) => alert.state !== "resolved").length}</strong></div>
                          </div>
                        </section>

                        <section className="space-y-3">
                          <p className="clone-section-title">Identity</p>
                          <div className="tracker-section-grid">
                            <div className="tracker-section-card"><span>OS / platform</span><strong>{detailValue(nodeDetail.system_identity.os ?? nodeDetail.system_identity.platform)}</strong></div>
                            <div className="tracker-section-card"><span>Hostname</span><strong>{detailValue(nodeDetail.system_identity.hostname)}</strong></div>
                            <div className="tracker-section-card"><span>Architecture</span><strong>{detailValue(nodeDetail.system_identity.architecture)}</strong></div>
                            <div className="tracker-section-card"><span>Kernel / build</span><strong>{detailValue(nodeDetail.system_identity.kernel ?? nodeDetail.system_identity.build)}</strong></div>
                            <div className="tracker-section-card"><span>Server ID</span><strong>{detailValue(primaryServer?.server_id)}</strong></div>
                            <div className="tracker-section-card"><span>Vendor / model</span><strong>{detailValue([nodeDetail.system_identity.vendor, nodeDetail.system_identity.model].filter(Boolean).join(" / "))}</strong></div>
                            <div className="tracker-section-card"><span>Serial</span><strong>{detailValue(nodeDetail.system_identity.serial)}</strong></div>
                            <div className="tracker-section-card"><span>Board</span><strong>{detailValue(nodeDetail.system_identity.board)}</strong></div>
                            <div className="tracker-section-card"><span>Board vendor</span><strong>{detailValue(nodeDetail.system_identity.board_vendor)}</strong></div>
                            <div className="tracker-section-card"><span>Agent version</span><strong>{detailValue(nodeDetail.agent_identity.version)}</strong></div>
                          </div>
                        </section>

                        <section className="space-y-3">
                          <p className="clone-section-title">Network & Addresses</p>
                          <div className="tracker-section-grid">
                            <div className="tracker-section-card"><span>Primary IP</span><strong>{detailValue(nodeDetail.network_identity.primary_ip ?? primaryServer?.primary_ip)}</strong></div>
                            <div className="tracker-section-card"><span>Primary MAC</span><strong>{detailValue(nodeDetail.network_identity.primary_mac)}</strong></div>
                            <div className="tracker-section-card"><span>Gateway</span><strong>{detailValue(nodeDetail.network_identity.gateway)}</strong></div>
                            <div className="tracker-section-card"><span>DNS</span><strong>{detailValue(nodeDetail.network_identity.dns_servers.join(" / "))}</strong></div>
                            <div className="tracker-section-card"><span>Hostname</span><strong>{detailValue(nodeDetail.network_identity.hostname)}</strong></div>
                            <div className="tracker-section-card"><span>FQDN</span><strong>{detailValue(nodeDetail.network_identity.fqdn)}</strong></div>
                            <div className="tracker-section-card"><span>Interfaces</span><strong>{detailValue(nodeDetail.network_identity.interfaces.length)}</strong></div>
                            <div className="tracker-section-card"><span>All addresses</span><strong>{detailValue(nodeDetail.platform_addresses.join(" / "))}</strong></div>
                          </div>
                        </section>

                        <section className="space-y-3">
                          <p className="clone-section-title">Firmware / BMC</p>
                          <div className="tracker-section-grid">
                            <div className="tracker-section-card"><span>BIOS vendor</span><strong>{detailValue(nodeDetail.firmware_identity.bios_vendor)}</strong></div>
                            <div className="tracker-section-card"><span>BIOS version</span><strong>{detailValue(nodeDetail.firmware_identity.bios_version)}</strong></div>
                            <div className="tracker-section-card"><span>BIOS release date</span><strong>{detailValue(nodeDetail.firmware_identity.bios_release_date)}</strong></div>
                            <div className="tracker-section-card"><span>Board firmware</span><strong>{detailValue(nodeDetail.firmware_identity.board_firmware_version)}</strong></div>
                            <div className="tracker-section-card"><span>BMC present</span><strong>{detailValue(nodeDetail.bmc_identity.present)}</strong></div>
                            <div className="tracker-section-card"><span>BMC vendor / model</span><strong>{detailValue([nodeDetail.bmc_identity.vendor, nodeDetail.bmc_identity.model].filter(Boolean).join(" / "))}</strong></div>
                            <div className="tracker-section-card"><span>BMC firmware</span><strong>{detailValue(nodeDetail.bmc_identity.firmware_version)}</strong></div>
                            <div className="tracker-section-card"><span>BMC source</span><strong>{detailValue(nodeDetail.bmc_identity.source)}</strong></div>
                            <div className="tracker-section-card"><span>IPMI / BMC address</span><strong>{detailValue(nodeDetail.bmc_identity.address ?? primaryServer?.bmc_address)}</strong></div>
                          </div>
                        </section>

                        <section className="space-y-3">
                          <p className="clone-section-title">Software & Runtime</p>
                          <div className="tracker-section-grid">
                            <div className="tracker-section-card"><span>OS edition</span><strong>{detailValue(nodeDetail.software_inventory.os_edition)}</strong></div>
                            <div className="tracker-section-card"><span>OS build</span><strong>{detailValue(nodeDetail.software_inventory.os_build)}</strong></div>
                            <div className="tracker-section-card"><span>Kernel version</span><strong>{detailValue(nodeDetail.software_inventory.kernel_version)}</strong></div>
                            <div className="tracker-section-card"><span>Python version</span><strong>{detailValue(nodeDetail.software_inventory.python_version)}</strong></div>
                            <div className="tracker-section-card"><span>Agent runtime</span><strong>{detailValue(nodeDetail.software_inventory.runtime ?? nodeDetail.agent_identity.runtime)}</strong></div>
                            <div className="tracker-section-card"><span>Executable</span><strong>{detailValue(nodeDetail.agent_identity.executable)}</strong></div>
                            <div className="tracker-section-card"><span>Agent platform</span><strong>{detailValue(nodeDetail.agent_identity.platform)}</strong></div>
                            <div className="tracker-section-card"><span>Driver versions</span><strong>{detailValue(Object.entries(nodeDetail.software_inventory.driver_versions).map(([key, value]) => `${key}:${value}`).join(" / "))}</strong></div>
                          </div>
                        </section>

                        {hardwareSections.map((section) => {
                          const components = hardwareGroups[section.key] ?? [];
                          return (
                            <section key={section.key} className="space-y-3">
                              <div className="flex items-center justify-between gap-3">
                                <p className="clone-section-title">{section.label}</p>
                                <span className="clone-soft-pill">{components.length} components</span>
                              </div>
                              {components.length ? (
                                <div className="space-y-2">
                                  {components.map((component) => (
                                    <div key={component.component_id} className="clone-list-row tracker-list-row">
                                      <div>
                                        <p className="font-semibold text-[#262626]">{component.name}</p>
                                        <p className="mt-1 text-sm text-[#a3a3a3]">
                                          {[component.vendor, component.model, component.slot_or_path].filter(Boolean).join(" / ") || component.component_id}
                                        </p>
                                      </div>
                                      <div className="text-sm text-[#737373]">
                                        {detailValue(
                                          componentMetricValue(component, "logical_cores") ??
                                            componentMetricValue(component, "total_bytes") ??
                                            (typeof component.metadata["fstype"] === "string" ? component.metadata["fstype"] : null) ??
                                            (typeof component.metadata["platform"] === "string" ? component.metadata["platform"] : null)
                                        )}
                                      </div>
                                      <div className="text-sm text-[#737373]">{detailValue(component.firmware_version)}</div>
                                      <div><span className={statusClass(component.health)}>{component.health}</span></div>
                                    </div>
                                  ))}
                                </div>
                              ) : (
                                <div className="clone-empty-state">No {section.label.toLowerCase()} components reported on this server yet.</div>
                              )}
                            </section>
                          );
                        })}

                        <section className="space-y-3">
                          <p className="clone-section-title">Network Interfaces</p>
                          {nodeDetail.network_identity.interfaces.length ? (
                            <div className="space-y-2">
                              {nodeDetail.network_identity.interfaces.map((iface) => (
                                <div key={iface.name} className="clone-list-row tracker-list-row">
                                  <div>
                                    <p className="font-semibold text-[#262626]">{iface.name}</p>
                                    <p className="mt-1 text-sm text-[#a3a3a3]">
                                      {detailValue([...iface.ipv4_addresses, ...iface.ipv6_addresses].join(" / "))}
                                    </p>
                                  </div>
                                  <div className="text-sm text-[#737373]">{detailValue(iface.mac_address)}</div>
                                  <div className="text-sm text-[#737373]">{detailValue(iface.speed_mbps ? `${iface.speed_mbps} Mbps` : null)}</div>
                                  <div><span className={statusClass(iface.link_state === "up" ? "online" : "offline")}>{detailValue(iface.link_state)}</span></div>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <div className="clone-empty-state">No interface inventory has been reported for this server yet.</div>
                          )}
                        </section>

                        <section className="space-y-3">
                          <p className="clone-section-title">Collector Freshness</p>
                          {(nodeDetail.collector_statuses ?? []).length ? (
                            (nodeDetail.collector_statuses ?? []).map((collector) => (
                              <div key={collector.collector_name} className="clone-list-row tracker-list-row">
                                <div>
                                  <p className="font-semibold text-[#262626]">{nice(collector.collector_name)}</p>
                                  <p className="mt-1 text-sm text-[#a3a3a3]">
                                    {collector.capability.state}{collector.capability.source ? ` / ${collector.capability.source}` : ""}
                                  </p>
                                </div>
                                <div className="text-sm text-[#737373]">{collector.metrics_emitted} metrics</div>
                                <div className="text-sm text-[#737373]">{collector.inventory_items_seen} items</div>
                                <div><span className={statusClass(collector.status === "ok" ? "running" : collector.status === "healthy" ? "completed" : "failed")}>{nice(collector.status)}</span></div>
                              </div>
                            ))
                          ) : (
                            <div className="clone-empty-state">Collector status will appear after the next hardware report.</div>
                          )}
                        </section>

                        <section className="grid gap-4 xl:grid-cols-2">
                          <div className="space-y-3">
                            <p className="clone-section-title">Alerts / Advisories</p>
                            {nodeDetail.alerts.length ? (
                              nodeDetail.alerts.map((alert) => (
                                <div key={`${alert.server_id}-${alert.signal}-${alert.created_at}`} className="clone-stack-card">
                                  <div className="flex items-center justify-between gap-3">
                                    <p className="font-semibold text-[#262626]">{nice(alert.signal)}</p>
                                    <span className={statusClass(alert.severity)}>{nice(alert.severity)}</span>
                                  </div>
                                  <p className="mt-2 text-sm text-[#737373]">{alert.message ?? "Alert is active for this signal."}</p>
                                </div>
                              ))
                            ) : nodeDetail.advisories.length ? (
                              nodeDetail.advisories.map((advisory) => (
                                <div key={advisory.title} className="clone-stack-card">
                                  <p className="font-semibold text-[#262626]">{advisory.title}</p>
                                  <p className="mt-2 text-sm text-[#737373]">{advisory.summary}</p>
                                  <p className="mt-2 text-sm font-medium text-[#404040]">{advisory.recommendation}</p>
                                </div>
                              ))
                            ) : (
                              <div className="clone-empty-state">No alerts or advisories are active for this server.</div>
                            )}
                          </div>

                          <div className="space-y-3">
                            <p className="clone-section-title">Recent Runs</p>
                            {nodeDetail.recent_runs.length ? (
                              nodeDetail.recent_runs.map((run) => (
                                <button key={run.task_id} type="button" className="clone-list-row tracker-list-row text-left" onClick={() => setSelectedRunId(run.task_id)}>
                                  <div>
                                    <p className="font-semibold text-[#262626]">{nice(run.task)}</p>
                                    <p className="mt-1 text-sm text-[#a3a3a3]">{formatDateTime(run.updated_at)}</p>
                                  </div>
                                  <div className="text-sm text-[#737373]">{detailValue(run.worker_id)}</div>
                                  <div className="text-sm font-semibold text-[#262626]">{run.score ?? "--"}</div>
                                  <div><span className={statusClass(run.status)}>{statusLabel(run.status)}</span></div>
                                </button>
                              ))
                            ) : (
                              <div className="clone-empty-state">No runs have been recorded for this server yet.</div>
                            )}
                          </div>
                        </section>

                        <section className="space-y-3">
                          <p className="clone-section-title">Run Detail</p>
                          {runDetail && runDetail.server?.server_id === nodeDetail.server.server_id ? (
                            <div className="space-y-3">
                              <div className="tracker-section-grid">
                                <div className="clone-data-chip"><span>Task</span><strong>{nice(runDetail.run.task)}</strong></div>
                                <div className="clone-data-chip"><span>Status</span><strong>{statusLabel(runDetail.run.status)}</strong></div>
                                <div className="clone-data-chip"><span>Attempts</span><strong>{runDetail.run.attempt_count}</strong></div>
                                <div className="clone-data-chip"><span>Score</span><strong>{runDetail.run.score ?? "--"}</strong></div>
                              </div>
                              <div className="clone-helper-copy">
                                <p>{String(runDetail.run.result.summary ?? "No summary available yet.")}</p>
                                <p>{runDetail.run.error_message ?? "No execution error recorded."}</p>
                              </div>
                              <div className="space-y-2">
                                <p className="clone-section-title">Execution Timeline</p>
                                {(runDetail.timeline ?? []).length ? (
                                  (runDetail.timeline ?? []).map((event) => (
                                    <div key={event.event_id} className="clone-list-row">
                                      <div>
                                        <p className="font-semibold text-[#262626]">{event.summary}</p>
                                        <p className="mt-1 text-sm text-[#a3a3a3]">
                                          {nice(event.event_type)}{event.status ? ` • ${statusLabel(event.status)}` : ""}
                                        </p>
                                      </div>
                                      <div className="text-sm text-[#737373]">{formatDateTime(event.created_at)}</div>
                                    </div>
                                  ))
                                ) : (
                                  <div className="clone-empty-state">No execution timeline events have been captured yet.</div>
                                )}
                              </div>
                            </div>
                          ) : (
                            <div className="clone-empty-state">
                              {detailLoading ? "Loading run detail..." : "Select a recent run above to inspect execution detail for this server."}
                            </div>
                          )}
                        </section>
                      </div>
                    ) : null}
                  </div>
                )}
              </ShellPanel>
            </div>
          ) : null}

          {false ? (
            <div className="grid gap-5 xl:grid-cols-[minmax(0,1.42fr)_320px]">
              <ShellPanel title="Fleet Tracker" subtitle="Search the fleet and inspect the latest server posture without leaving the dashboard language.">
                <div className="mb-5 flex items-center justify-between gap-3">
                  <div className="clone-search-input">
                    <span className="icon-search icon-search--small" />
                    <input value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder="Search servers, groups, tags" />
                  </div>
                  <span className="clone-delta-pill">{filteredServers.length} tracked</span>
                </div>
                <div className="space-y-3">
                  {filteredServers.map((server) => {
                    const metric = dashboard.latest_metrics.find((item) => item.server_id === server.server_id);
                    return (
                      <button
                        key={server.server_id}
                        className={server.server_id === selectedServerId ? "clone-list-row clone-list-row--selected text-left" : "clone-list-row text-left"}
                        onClick={() => setSelectedServerId(server.server_id)}
                        aria-pressed={server.server_id === selectedServerId}
                      >
                        <div>
                          <p className="font-semibold text-[#262626]">{server.server_name}</p>
                          <p className="mt-1 text-sm text-[#a3a3a3]">{server.server_id}</p>
                        </div>
                        <div className="text-sm text-[#737373]">{server.group}</div>
                        <div className="text-sm font-semibold text-[#262626]">{metric ? percent(metric.cpu) : "--"}</div>
                        <div>
                          <span className={statusClass(server.health)}>{server.health}</span>
                        </div>
                      </button>
                    );
                  })}
                  {!filteredServers.length ? <div className="clone-empty-state">No servers matched your current search.</div> : null}
                </div>
              </ShellPanel>

              <ShellPanel title="Server Snapshot" subtitle="Live metrics for the currently selected node.">
                <div className="space-y-4">
                  <div className="clone-server-card">
                    <p className="clone-server-card__eyebrow">{primaryServer?.group ?? "Server Group"}</p>
                    <p className="mt-4 text-[1.05rem] font-semibold text-[#525252]">{primaryServer?.server_name ?? "No server selected"}</p>
                    <div className="mt-6 grid grid-cols-2 gap-4 text-sm">
                      <div className="clone-data-chip">
                        <span>Last heartbeat</span>
                        <strong>{primaryServer?.last_heartbeat_at ? formatDateTime(primaryServer.last_heartbeat_at ?? "") : "--"}</strong>
                      </div>
                      <div className="clone-data-chip">
                        <span>Last activity</span>
                        <strong>{latestServerActivity(primaryServer) ? formatDateTime(latestServerActivity(primaryServer) ?? "") : "--"}</strong>
                      </div>
                      <div className="clone-data-chip">
                        <span>Status</span>
                        <strong>{primaryServer?.status ?? "--"}</strong>
                      </div>
                      <div className="clone-data-chip">
                        <span>Capabilities</span>
                        <strong>{primaryServer?.capabilities.length ?? 0}</strong>
                      </div>
                      <div className="clone-data-chip">
                        <span>Last metric</span>
                        <strong>{primaryServer?.last_metric_at ? formatDateTime(primaryServer.last_metric_at ?? "") : "--"}</strong>
                      </div>
                      <div className="clone-data-chip">
                        <span>Last telemetry</span>
                        <strong>{primaryServer?.last_telemetry_at ? formatDateTime(primaryServer.last_telemetry_at ?? "") : "--"}</strong>
                      </div>
                      <div className="clone-data-chip">
                        <span>Inventory refresh</span>
                        <strong>{primaryServer?.last_inventory_refresh_at ? formatDateTime(primaryServer.last_inventory_refresh_at ?? "") : "--"}</strong>
                      </div>
                      <div className="clone-data-chip">
                        <span>Health</span>
                        <strong>{primaryServer?.health ?? "--"}</strong>
                      </div>
                    </div>
                  </div>
                  {nodeDetail?.latest_metric ? (
                    <div className="grid gap-3 md:grid-cols-2">
                      <div className="clone-data-chip"><span>Network</span><strong>{Math.round(nodeDetail?.latest_metric?.network_mbps ?? 0)} Mbps</strong></div>
                      <div className="clone-data-chip"><span>Temperature</span><strong>{nodeDetail?.latest_metric?.temperature_c ? `${Math.round(nodeDetail?.latest_metric?.temperature_c ?? 0)}C` : "--"}</strong></div>
                      <div className="clone-data-chip"><span>GPU</span><strong>{nodeDetail?.latest_metric?.gpu_utilization ? `${Math.round(nodeDetail?.latest_metric?.gpu_utilization ?? 0)}%` : "--"}</strong></div>
                      <div className="clone-data-chip"><span>Open alerts</span><strong>{nodeDetail?.alerts.filter((alert) => alert.state !== "resolved").length ?? 0}</strong></div>
                    </div>
                  ) : null}
                  {nodeDetail ? (
                    <>
                      <div className="grid gap-3 md:grid-cols-2">
                        <div className="clone-data-chip">
                          <span>Hardware health</span>
                          <strong>{String(nodeDetail?.hardware_overview.overall_health ?? primaryServer?.health ?? "--")}</strong>
                        </div>
                        <div className="clone-data-chip">
                          <span>Tracked components</span>
                          <strong>{nodeDetail?.hardware_inventory.length ?? 0}</strong>
                        </div>
                        <div className="clone-data-chip">
                          <span>Hot components</span>
                          <strong>{Number(nodeDetail?.hardware_overview.hot_component_count ?? 0)}</strong>
                        </div>
                        <div className="clone-data-chip">
                          <span>Failing components</span>
                          <strong>{Number(nodeDetail?.hardware_overview.failing_component_count ?? 0)}</strong>
                        </div>
                      </div>

                      <div className="space-y-2">
                        <p className="clone-section-title">Collector Freshness</p>
                        {(nodeDetail?.collector_statuses ?? []).length ? (
                          (nodeDetail?.collector_statuses ?? []).map((collector) => (
                            <div key={collector.collector_name} className="clone-list-row">
                              <div>
                                <p className="font-semibold text-[#262626]">{nice(collector.collector_name)}</p>
                                <p className="mt-1 text-sm text-[#a3a3a3]">
                                  {collector.capability.state}{collector.capability.source ? ` • ${collector.capability.source}` : ""}
                                </p>
                              </div>
                              <div className="text-sm text-[#737373]">{collector.metrics_emitted} metrics</div>
                              <div className="text-sm text-[#737373]">{collector.inventory_items_seen} items</div>
                              <div>
                                <span className={statusClass(collector.status === "ok" ? "running" : collector.status === "healthy" ? "completed" : "failed")}>
                                  {nice(collector.status)}
                                </span>
                              </div>
                            </div>
                          ))
                        ) : (
                          <div className="clone-empty-state">Collector status will appear after the next hardware report.</div>
                        )}
                      </div>

                      <div className="space-y-3">
                        <p className="clone-section-title">Hardware Explorer</p>
                        {hardwareSections.map((section) => {
                          const components = hardwareGroups[section.key] ?? [];
                          return (
                            <div key={section.key} className="clone-stack-card">
                              <div className="flex items-center justify-between gap-3">
                                <p className="font-semibold text-[#262626]">{section.label}</p>
                                <span className="text-sm text-[#737373]">{components.length} components</span>
                              </div>
                              {components.length ? (
                                <div className="mt-3 space-y-2">
                                  {components.map((component) => (
                                    <div key={component.component_id} className="clone-list-row">
                                      <div>
                                        <p className="font-semibold text-[#262626]">{component.name}</p>
                                        <p className="mt-1 text-sm text-[#a3a3a3]">
                                          {[component.vendor, component.model, component.slot_or_path].filter(Boolean).join(" • ") || component.component_id}
                                        </p>
                                      </div>
                                      <div className="text-sm text-[#737373]">
                                        {componentMetricValue(component, "logical_cores") ??
                                          componentMetricValue(component, "total_bytes") ??
                                          (typeof component.metadata["fstype"] === "string" ? component.metadata["fstype"] : null) ??
                                          (typeof component.metadata["platform"] === "string" ? component.metadata["platform"] : null) ??
                                          "--"}
                                      </div>
                                      <div>
                                        <span className={statusClass(component.health)}>{component.health}</span>
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              ) : (
                                <div className="clone-empty-state">No {section.label.toLowerCase()} components reported on this server yet.</div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </>
                  ) : null}
                  <div className="space-y-3">
                    {(nodeDetail?.advisories ?? []).map((advisory) => (
                      <div key={advisory.title} className="clone-stack-card">
                        <p className="font-semibold text-[#262626]">{advisory.title}</p>
                        <p className="mt-2 text-sm text-[#737373]">{advisory.summary}</p>
                        <p className="mt-2 text-sm font-medium text-[#404040]">{advisory.recommendation}</p>
                      </div>
                    ))}
                    {detailLoading && !nodeDetail ? <div className="clone-empty-state">Loading live server detail...</div> : null}
                  </div>
                </div>
              </ShellPanel>
            </div>
          ) : null}

          {activeNav === "Runs" ? (
            <div className="space-y-5">
              <ShellPanel title="Fleet Monitoring" subtitle="Live monitoring across every connected server and every reported component family, including fan speed when available.">
                {!runsDetailOpen ? (
                  <>
                    <div className="mb-5 flex items-center justify-between gap-3">
                      <div className="clone-search-input">
                        <span className="icon-search icon-search--small" />
                        <input value={runsSearchText} onChange={(event) => setRunsSearchText(event.target.value)} placeholder="Search monitored servers, IPs, platforms" />
                      </div>
                      <span className="clone-delta-pill">{filteredMonitoringCards.length} tracked</span>
                    </div>
                    <div className="tracker-section-grid">
                      <div className="clone-data-chip clone-data-chip--large"><span>Fleet online</span><strong>{fleetMonitoring.fleet_online}/{fleetMonitoring.fleet_total}</strong></div>
                      <div className="clone-data-chip clone-data-chip--large"><span>Reporting servers</span><strong>{fleetMonitoring.reporting_servers}</strong></div>
                      <div className="clone-data-chip clone-data-chip--large"><span>Active alerts</span><strong>{fleetMonitoring.active_alerts}</strong></div>
                      <div className="clone-data-chip clone-data-chip--large"><span>Average fan speed</span><strong>{fanSummary?.average_value ? `${Math.round(fanSummary.average_value)} RPM` : "Not reported"}</strong></div>
                    </div>
                    <div className="mt-5 tracker-grid">
                      {filteredMonitoringCards.map((card) => (
                        <button
                          key={card.server.server_id}
                          type="button"
                          className="tracker-card"
                          onClick={() => {
                            setRunsSelectedServerId(card.server.server_id);
                            setRunsDetailOpen(true);
                          }}
                        >
                          <div className="tracker-card__top">
                            <div>
                              <p className="tracker-card__name">{card.server.server_name}</p>
                              <p className="tracker-card__subtle">{card.server.platform_label ?? card.server.group}</p>
                            </div>
                            <span className={statusClass(card.overall_health)}>{card.overall_health}</span>
                          </div>
                          <div className="tracker-card__meta">
                            <span>{card.server.primary_ip ?? card.server.group}</span>
                            <span>{card.server.status}</span>
                            <span>{card.collector_issue_count} collector issues</span>
                          </div>
                          <div className="tracker-card__stats">
                            <div className="tracker-card__stat"><span>CPU</span><strong>{compactStat(card.latest_metric?.cpu)}</strong></div>
                            <div className="tracker-card__stat"><span>Memory</span><strong>{compactStat(card.latest_metric?.memory)}</strong></div>
                            <div className="tracker-card__stat"><span>Temp</span><strong>{compactStat(card.latest_metric?.temperature_c, "C")}</strong></div>
                            <div className="tracker-card__stat"><span>Fan</span><strong>{card.fan_speed_rpm ? `${Math.round(card.fan_speed_rpm)} RPM` : "Not reported"}</strong></div>
                          </div>
                          <div className="tracker-card__foot">
                            <span>Hot / failing</span>
                            <strong>{card.hot_component_count}/{card.failing_component_count}</strong>
                          </div>
                        </button>
                      ))}
                      {!filteredMonitoringCards.length ? <div className="clone-empty-state">No live monitoring cards are available until servers start reporting telemetry.</div> : null}
                    </div>
                  </>
                ) : runsSelectedCard ? (
                  <div className="tracker-detail-shell">
                    <button type="button" className="tracker-back" onClick={() => setRunsDetailOpen(false)}>
                      <span className="tracker-back__icon" aria-hidden="true" />
                      Back to fleet
                    </button>
                    <div className="tracker-detail-hero">
                      <div>
                        <p className="tracker-detail-hero__eyebrow">Monitoring cockpit</p>
                        <h2 className="tracker-detail-hero__title">{runsSelectedServer?.server_name}</h2>
                        <p className="tracker-detail-hero__copy">
                          {[
                            runsSelectedServer?.primary_ip ?? "No primary IP",
                            runsSelectedServer?.platform_label ?? runsSelectedServer?.group ?? "Platform not reported",
                            `Last heartbeat ${runsSelectedServer?.last_heartbeat_at ? formatDateTime(runsSelectedServer.last_heartbeat_at) : "Not reported"}`,
                          ].join(" | ")}
                        </p>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={statusClass(runsSelectedServer?.status ?? "offline")}>{statusLabel(runsSelectedServer?.status ?? "offline")}</span>
                        <span className={statusClass(runsSelectedCard.overall_health)}>{runsSelectedCard.overall_health}</span>
                      </div>
                    </div>
                    <div className="tracker-section-grid">
                      <div className="clone-data-chip"><span>CPU</span><strong>{compactStat(runsSelectedLatestMetric?.cpu)}</strong></div>
                      <div className="clone-data-chip"><span>Memory</span><strong>{compactStat(runsSelectedLatestMetric?.memory)}</strong></div>
                      <div className="clone-data-chip"><span>Disk</span><strong>{compactStat(runsSelectedLatestMetric?.disk)}</strong></div>
                      <div className="clone-data-chip"><span>Temperature</span><strong>{compactStat(runsSelectedLatestMetric?.temperature_c, "C")}</strong></div>
                      <div className="clone-data-chip"><span>Fan speed</span><strong>{runsSelectedCard.fan_speed_rpm ? `${Math.round(runsSelectedCard.fan_speed_rpm)} RPM` : "Not reported"}</strong></div>
                      <div className="clone-data-chip"><span>Collector issues</span><strong>{runsSelectedCard.collector_issue_count}</strong></div>
                    </div>
                    <div className="mt-5 grid gap-5 xl:grid-cols-2">
                      <ShellPanel title="Server Monitoring Summary" subtitle="Live posture for the selected host with fleet-wide benchmarks alongside it.">
                        <div className="tracker-section-grid">
                          <div className="clone-data-chip"><span>Primary IP</span><strong>{runsSelectedServer?.primary_ip ?? "Not reported"}</strong></div>
                          <div className="clone-data-chip"><span>Platform</span><strong>{runsSelectedServer?.platform_label ?? "Not reported"}</strong></div>
                          <div className="clone-data-chip"><span>Hot components</span><strong>{runsSelectedCard.hot_component_count}</strong></div>
                          <div className="clone-data-chip"><span>Failing components</span><strong>{runsSelectedCard.failing_component_count}</strong></div>
                          <div className="clone-data-chip"><span>Active alerts</span><strong>{fleetMonitoring.active_alerts}</strong></div>
                          <div className="clone-data-chip"><span>Fleet context</span><strong>{fleetMonitoring.reporting_servers} reporting</strong></div>
                        </div>
                      </ShellPanel>
                      <ResourceUsageChart
                        metrics={
                          runsSelectedLatestMetric
                            ? [{ ...runsSelectedLatestMetric, serverName: runsSelectedServer?.server_name ?? runsSelectedServer?.server_id ?? "Selected server" }]
                            : []
                        }
                      />
                    </div>
                    <div className="mt-5 grid gap-5 xl:grid-cols-2">
                      <ShellPanel title="Component Families" subtitle="Every monitored hardware family reported by this host, with fleet context for coverage and drift.">
                        <div className="space-y-3">
                          {fleetMonitoring.component_summaries.map((summary) => (
                            <div key={summary.key} className="clone-list-row">
                              <div>
                                <p className="font-semibold text-[#262626]">{summary.label}</p>
                                <p className="mt-1 text-sm text-[#a3a3a3]">{summary.reporting_servers} fleet reporters | {summary.unsupported_servers} unsupported</p>
                              </div>
                              <div className="text-sm text-[#737373]">{runsSelectedCard.component_counts[summary.key] ?? 0} on host</div>
                              <div className="text-sm font-semibold text-[#262626]">
                                {summary.average_value !== null ? `${Math.round(summary.average_value)}${summary.unit ? ` ${summary.unit}` : ""}` : "Not reported"}
                              </div>
                              <div>
                                <span className={statusClass(summary.failing_components ? "failed" : summary.warning_components ? "running" : "completed")}>
                                  {summary.failing_components ? "Failing" : summary.warning_components ? "Warning" : "Healthy"}
                                </span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </ShellPanel>
                      <ComponentCoverageChart summaries={fleetMonitoring.component_summaries} />
                    </div>
                    <div className="mt-5 grid gap-5 xl:grid-cols-2">
                      {cpuHistory ? <FleetMetricHistoryChart series={cpuHistory} /> : null}
                      {memoryHistory ? <FleetMetricHistoryChart series={memoryHistory} /> : null}
                      {storageHistory ? <FleetMetricHistoryChart series={storageHistory} /> : null}
                      {networkHistory ? <FleetMetricHistoryChart series={networkHistory} /> : null}
                      {thermalHistory ? <FleetMetricHistoryChart series={thermalHistory} /> : null}
                      {fanHistory ? <FleetMetricHistoryChart series={fanHistory} /> : null}
                      {gpuHistory ? <FleetMetricHistoryChart series={gpuHistory} /> : null}
                    </div>
                    <div className="mt-5 grid gap-5 xl:grid-cols-2">
                      <ShellPanel title="Hot Components" subtitle="Problems and thermal hotspots affecting the selected host right now.">
                        <div className="space-y-3">
                          {runsSelectedHotspots.map((component) => (
                            <div key={component.component_id} className="clone-stack-card">
                              <p className="font-semibold text-[#262626]">{component.name}</p>
                              <p className="mt-2 text-sm text-[#737373]">{[component.component_type, component.vendor, component.model].filter(Boolean).join(" | ")}</p>
                              <p className="mt-2 text-sm font-medium text-[#404040]">Health: {component.health}</p>
                            </div>
                          ))}
                          {!runsSelectedHotspots.length ? <div className="clone-empty-state">No hot or failing components are currently flagged for this host.</div> : null}
                        </div>
                      </ShellPanel>
                      <ShellPanel title="Collector Coverage" subtitle="Unsupported or degraded collectors stay visible here so monitoring gaps are obvious.">
                        <div className="space-y-3">
                          {runsSelectedCollectorIssues.length ? (
                            runsSelectedCollectorIssues.map((collector) => (
                              <div key={`${collector.collector_name}-${collector.recorded_at}`} className="clone-list-row">
                                <div>
                                  <p className="font-semibold text-[#262626]">{nice(collector.collector_name)}</p>
                                  <p className="mt-1 text-sm text-[#a3a3a3]">{collector.capability.state}</p>
                                </div>
                                <div className="text-sm text-[#737373]">{collector.metrics_emitted} metrics</div>
                                <div className="text-sm text-[#737373]">{collector.inventory_items_seen} items</div>
                                <div><span className={statusClass("failed")}>{nice(collector.status)}</span></div>
                              </div>
                            ))
                          ) : (
                            <div className="clone-empty-state">No collector coverage gaps are active for the fleet right now.</div>
                          )}
                        </div>
                      </ShellPanel>
                    </div>
                  </div>
                ) : (
                  <div className="clone-empty-state">No monitoring target is available yet. Connect a reporting server to open the monitoring cockpit.</div>
                )}
              </ShellPanel>
            </div>
          ) : null}

          {activeNav === "Workflows" ? (
            <div className="space-y-5">
              <ShellPanel title="Workflow Launcher" subtitle="Choose a live server first, then launch the tests and workflow templates that machine and OS actually support.">
                {!workflowDetailOpen ? (
                  <>
                    <div className="mb-5 flex items-center justify-between gap-3">
                      <div className="clone-search-input">
                        <span className="icon-search icon-search--small" />
                        <input value={workflowSearchText} onChange={(event) => setWorkflowSearchText(event.target.value)} placeholder="Search servers, IPs, groups, capabilities" />
                      </div>
                      <span className="clone-delta-pill">{filteredWorkflowServers.length} tracked</span>
                    </div>
                    <div className="tracker-grid">
                      {filteredWorkflowServers.map((server) => {
                        const metric = serverMetricMap.get(server.server_id);
                        return (
                          <button
                            key={server.server_id}
                            type="button"
                            className="tracker-card"
                            onClick={() => {
                              setWorkflowSelectedServerId(server.server_id);
                              setWorkflowDetailOpen(true);
                            }}
                          >
                            <div className="tracker-card__top">
                              <div>
                                <div className="flex flex-wrap items-center gap-2">
                                  <p className="tracker-card__name">{server.server_name}</p>
                                  {isNewServer(server) ? <span className="clone-soft-pill">New</span> : null}
                                </div>
                                <p className="tracker-card__subtle">{server.platform_label ?? server.group}</p>
                              </div>
                              <span className={statusClass(server.health)}>{server.health}</span>
                            </div>
                            <div className="tracker-card__meta">
                              <span>{server.primary_ip ?? server.group}</span>
                              <span>{server.status}</span>
                              <span>{dashboard.workflow_templates.filter((workflow) => workflow.steps.every((step) => isTaskSupported(step, server))).length} flows ready</span>
                            </div>
                            <div className="tracker-card__stats">
                              <div className="tracker-card__stat"><span>Tests</span><strong>{dashboard.allowed_tasks.filter((task) => isTaskSupported(task.name, server)).length}</strong></div>
                              <div className="tracker-card__stat"><span>Flows</span><strong>{dashboard.workflow_templates.filter((workflow) => workflow.steps.every((step) => isTaskSupported(step, server))).length}</strong></div>
                              <div className="tracker-card__stat"><span>CPU</span><strong>{compactStat(metric?.cpu)}</strong></div>
                              <div className="tracker-card__stat"><span>Temp</span><strong>{compactStat(metric?.temperature_c, "C")}</strong></div>
                            </div>
                            <div className="tracker-card__foot">
                              <span>Last heartbeat</span>
                              <strong>{server.last_heartbeat_at ? formatDateTime(server.last_heartbeat_at) : "Not reported"}</strong>
                            </div>
                          </button>
                        );
                      })}
                      {!filteredWorkflowServers.length ? <div className="clone-empty-state">No connected servers are available for test or workflow launch yet.</div> : null}
                    </div>
                  </>
                ) : workflowSelectedServer ? (
                  <div className="tracker-detail-shell">
                    <button type="button" className="tracker-back" onClick={() => setWorkflowDetailOpen(false)}>
                      <span className="tracker-back__icon" aria-hidden="true" />
                      Back to fleet
                    </button>
                    <div className="tracker-detail-hero">
                      <div>
                        <p className="tracker-detail-hero__eyebrow">Execution cockpit</p>
                        <h2 className="tracker-detail-hero__title">{workflowSelectedServer.server_name}</h2>
                        <p className="tracker-detail-hero__copy">
                          {[
                            workflowSelectedServer.primary_ip ?? "No primary IP",
                            workflowSelectedServer.platform_label ?? workflowSelectedServer.group,
                            workflowSelectedServer.last_heartbeat_at ? `Last heartbeat ${formatDateTime(workflowSelectedServer.last_heartbeat_at)}` : "Heartbeat not reported",
                          ].join(" | ")}
                        </p>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        {isNewServer(workflowSelectedServer) ? <span className="clone-soft-pill">New server</span> : null}
                        <span className={statusClass(workflowSelectedServer.status)}>{statusLabel(workflowSelectedServer.status)}</span>
                        <span className={statusClass(workflowSelectedServer.health)}>{workflowSelectedServer.health}</span>
                      </div>
                    </div>

                    <div className="tracker-section-grid">
                      <div className="clone-data-chip"><span>Runnable tests</span><strong>{workflowTaskOptions.length}</strong></div>
                      <div className="clone-data-chip"><span>Runnable workflows</span><strong>{workflowTemplateOptions.length}</strong></div>
                      <div className="clone-data-chip"><span>Capabilities</span><strong>{workflowSelectedServer.capabilities.length}</strong></div>
                      <div className="clone-data-chip"><span>CPU</span><strong>{compactStat(workflowServerMetric?.cpu)}</strong></div>
                      <div className="clone-data-chip"><span>Memory</span><strong>{compactStat(workflowServerMetric?.memory)}</strong></div>
                      <div className="clone-data-chip"><span>Temperature</span><strong>{compactStat(workflowServerMetric?.temperature_c, "C")}</strong></div>
                    </div>

                    {actionError ? <div className="clone-warning-banner">{actionError}</div> : null}
                    {actionSuccess ? <div className="clone-success-banner">{actionSuccess}</div> : null}

                    <div className="mt-5 grid gap-5 xl:grid-cols-2">
                      <ShellPanel title="Quick Tests" subtitle="Single benchmarks and checks available on this server right now.">
                        <div className="space-y-3">
                          {workflowTaskOptions.map((task) => (
                            <article key={task.name} className="clone-stack-card">
                              <div className="flex items-start justify-between gap-3">
                                <div>
                                  <p className="text-[1rem] font-bold text-[#262626]">{nice(task.name)}</p>
                                  <p className="mt-2 text-sm text-[#737373]">{task.summary}</p>
                                </div>
                                <span className="clone-soft-pill">{task.default_timeout_seconds}s</span>
                              </div>
                              <div className="mt-4 flex items-center justify-between gap-3">
                                <span className="text-sm text-[#a3a3a3]">Supported on {workflowSelectedServer.platform_label ?? workflowSelectedServer.group}</span>
                                <button
                                  type="button"
                                  className="clone-secondary-action"
                                  disabled={actionPending}
                                  onClick={() => void triggerTask({ server_id: workflowSelectedServer.server_id, task: task.name, requested_by: "web-ui" })}
                                >
                                  {actionPending ? "Running..." : "Run test"}
                                </button>
                              </div>
                            </article>
                          ))}
                          {!workflowTaskOptions.length ? <div className="clone-empty-state">No supported single tests are available for this server.</div> : null}
                        </div>
                      </ShellPanel>

                      <ShellPanel title="Workflow Templates" subtitle="Multi-step validation and benchmarking flows that match this server's capabilities.">
                        <div className="space-y-3">
                          {workflowTemplateOptions.map((workflow) => (
                            <article key={workflow.name} className="clone-stack-card">
                              <div className="flex items-start justify-between gap-3">
                                <div>
                                  <p className="text-[1rem] font-bold text-[#262626]">{nice(workflow.name)}</p>
                                  <p className="mt-2 text-sm text-[#737373]">{workflow.summary}</p>
                                </div>
                                <span className="clone-soft-pill">{workflow.steps.length} steps</span>
                              </div>
                              <div className="mt-4 flex flex-wrap gap-2">
                                {workflow.steps.map((step) => (
                                  <span key={step} className="clone-soft-pill">
                                    {nice(step)}
                                  </span>
                                ))}
                              </div>
                              <div className="mt-4 flex items-center justify-between gap-3">
                                <span className="text-sm text-[#a3a3a3]">Every step is supported on this host</span>
                                <button
                                  type="button"
                                  className="clone-primary-action"
                                  disabled={actionPending}
                                  onClick={() => void triggerWorkflow({ server_id: workflowSelectedServer.server_id, workflow: workflow.name, requested_by: "web-ui" })}
                                >
                                  {actionPending ? "Dispatching..." : "Run workflow"}
                                </button>
                              </div>
                            </article>
                          ))}
                          {!workflowTemplateOptions.length ? <div className="clone-empty-state">No workflow templates fully match this server's capabilities yet.</div> : null}
                        </div>
                      </ShellPanel>
                    </div>

                    <div className="mt-5 grid gap-5 xl:grid-cols-2">
                      <ShellPanel title="Capability Summary" subtitle="Platform and feature coverage detected on this host.">
                        <div className="space-y-3">
                          <div className="clone-data-chip"><span>Platform</span><strong>{workflowSelectedServer.platform_label ?? "Not reported"}</strong></div>
                          <div className="clone-data-chip"><span>Primary IP</span><strong>{workflowSelectedServer.primary_ip ?? "Not reported"}</strong></div>
                          <div className="clone-data-chip"><span>BMC/IPMI</span><strong>{workflowSelectedServer.bmc_address ?? "Not reported"}</strong></div>
                          <div className="flex flex-wrap gap-2">
                            {workflowSelectedServer.capabilities.map((capability) => (
                              <span key={capability} className="clone-soft-pill">{nice(capability)}</span>
                            ))}
                            {!workflowSelectedServer.capabilities.length ? <span className="text-sm text-[#a3a3a3]">No capability tags reported.</span> : null}
                          </div>
                        </div>
                      </ShellPanel>

                      <ShellPanel title="Recent Workflow Runs" subtitle="Latest workflow executions for this server.">
                        <div className="space-y-3">
                          {workflowServerWorkflowRuns.map((workflow) => (
                            <div key={workflow.workflow_id} className="clone-list-row">
                              <div>
                                <p className="font-semibold text-[#262626]">{nice(workflow.workflow)}</p>
                                <p className="mt-1 text-sm text-[#a3a3a3]">Step {workflow.current_step_index + 1}/{Math.max(1, workflow.steps.length)}</p>
                              </div>
                              <div className="text-sm text-[#737373]">{formatDateTime(workflow.updated_at)}</div>
                              <div><span className={statusClass(workflow.status)}>{statusLabel(workflow.status)}</span></div>
                              <div>
                                {workflow.status === "pending" || workflow.status === "running" ? (
                                  <button
                                    type="button"
                                    className="text-sm font-semibold text-[#8b2c2c]"
                                    disabled={actionPending}
                                    onClick={() => void cancelWorkflow(workflow.workflow_id)}
                                  >
                                    Cancel
                                  </button>
                                ) : (
                                  <span className="text-sm text-[#a3a3a3]">?</span>
                                )}
                              </div>
                            </div>
                          ))}
                          {!workflowServerWorkflowRuns.length ? <div className="clone-empty-state">No workflow runs recorded for this server yet.</div> : null}
                        </div>
                      </ShellPanel>
                    </div>

                    <ShellPanel title="Recent Test Runs" subtitle="Latest task and benchmark executions for this same server.">
                      <div className="space-y-3">
                        {workflowServerRuns.map((run) => (
                          <div key={run.task_id} className="clone-list-row">
                            <div>
                              <p className="font-semibold text-[#262626]">{nice(run.task)}</p>
                              <p className="mt-1 text-sm text-[#a3a3a3]">{formatDateTime(run.updated_at)}</p>
                            </div>
                            <div className="text-sm text-[#737373]">Score {run.score ?? "--"}</div>
                            <div><span className={statusClass(run.status)}>{statusLabel(run.status)}</span></div>
                          </div>
                        ))}
                        {!workflowServerRuns.length ? <div className="clone-empty-state">No task runs recorded for this server yet.</div> : null}
                      </div>
                    </ShellPanel>
                  </div>
                ) : (
                  <div className="clone-empty-state">No server is available to open the workflow launcher yet.</div>
                )}
              </ShellPanel>
            </div>
          ) : null}

          {activeNav === "Analytics" ? (
            <div className="space-y-5">
              <ShellPanel title="Analytics Workspace" subtitle="Historical insight, server comparison, regressions, and reporting for the fleet.">
                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                  <ConsoleDropdown
                    label="Period"
                    value={analyticsPeriod}
                    options={PERIODS.map((option) => ({ value: option, label: option }))}
                    onChange={(value) => setAnalyticsPeriod(value as Period)}
                    placeholder="Period"
                  />
                  <ConsoleDropdown
                    label="Group"
                    value={analyticsGroupFilter}
                    options={analyticsGroups.map((group) => ({ value: group, label: group === "all" ? "All groups" : group }))}
                    onChange={setAnalyticsGroupFilter}
                    placeholder="All groups"
                  />
                  <ConsoleDropdown
                    label="Platform"
                    value={analyticsPlatformFilter}
                    options={analyticsPlatforms.map((platform) => ({ value: platform, label: platform === "all" ? "All platforms" : platform }))}
                    onChange={setAnalyticsPlatformFilter}
                    placeholder="All platforms"
                  />
                  <ConsoleDropdown
                    label="Primary server"
                    value={analyticsServer?.server_id ?? ""}
                    options={filteredAnalyticsServers.map((server) => ({ value: server.server_id, label: server.server_name }))}
                    onChange={setAnalyticsServerId}
                    placeholder="Select server"
                  />
                </div>

                <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
                  <div className="tracker-section-grid">
                    <div className="clone-data-chip clone-data-chip--large"><span>Servers in scope</span><strong>{filteredAnalyticsServers.length}</strong></div>
                    <div className="clone-data-chip clone-data-chip--large"><span>Runs in scope</span><strong>{analyticsRunSubset.length}</strong></div>
                    <div className="clone-data-chip clone-data-chip--large"><span>Alerts in scope</span><strong>{analyticsAlertsSubset.length}</strong></div>
                    <div className="clone-data-chip clone-data-chip--large"><span>Average score</span><strong>{analyticsServer ? `${dashboard.average_score}%` : "Not reported"}</strong></div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" className="clone-secondary-action" onClick={() => exportAnalyticsDetails("pdf")}>Export PDF</button>
                    <button type="button" className="clone-secondary-action" onClick={() => exportAnalyticsDetails("csv")}>Export CSV</button>
                    <button type="button" className="clone-secondary-action" onClick={() => exportAnalyticsDetails("json")}>Export JSON</button>
                  </div>
                </div>
                {analyticsExportMessage ? <div className="clone-success-banner">{analyticsExportMessage}</div> : null}
              </ShellPanel>

              {!filteredAnalyticsServers.length ? (
                <div className="clone-empty-state">No servers match the current analytics filters.</div>
              ) : (
                <>
                  <div className="grid gap-5 xl:grid-cols-2">
                    <ShellPanel title="Overview" subtitle="Top historical and operational signals across the current filter scope.">
                      <div className="tracker-section-grid">
                        {analyticsOverviewCards.map((item) => (
                          <div key={item.label} className="clone-data-chip">
                            <span>{item.label}</span>
                            <strong>{item.value}</strong>
                          </div>
                        ))}
                      </div>
                    </ShellPanel>
                    <ReadinessHistoryChart history={analyticsHistory.points} period={analyticsPeriod} />
                  </div>

                  <div className="grid gap-5 xl:grid-cols-2">
                    <ShellPanel title="Server Comparison" subtitle="Compare two servers directly across core metrics and hardware posture.">
                      <div className="grid gap-4 md:grid-cols-2">
                        <ConsoleDropdown
                          label="Primary"
                          value={analyticsServer?.server_id ?? ""}
                          options={filteredAnalyticsServers.map((server) => ({ value: server.server_id, label: server.server_name }))}
                          onChange={setAnalyticsServerId}
                          placeholder="Primary server"
                        />
                        <ConsoleDropdown
                          label="Compare"
                          value={analyticsCompareServer?.server_id ?? ""}
                          options={filteredAnalyticsServers.filter((server) => server.server_id !== analyticsServer?.server_id).map((server) => ({ value: server.server_id, label: server.server_name }))}
                          onChange={setAnalyticsCompareServerId}
                          placeholder="Compare server"
                        />
                      </div>
                      <div className="mt-5 space-y-3">
                        {analyticsComparisonRows.map((row) => (
                          <div key={row.label} className="clone-list-row">
                            <div>
                              <p className="font-semibold text-[#262626]">{row.label}</p>
                              <p className="mt-1 text-sm text-[#a3a3a3]">{analyticsServer?.server_name ?? "Primary"} vs {analyticsCompareServer?.server_name ?? "Compare"}</p>
                            </div>
                            <div className="text-sm text-[#737373]">{formatComparisonValue(row.left, row.suffix)}</div>
                            <div className="text-sm text-[#737373]">{formatComparisonValue(row.right, row.suffix)}</div>
                            <div>
                              <span className={statusClass((row.left ?? 0) >= (row.right ?? 0) ? "completed" : "warning")}>
                                {row.left !== null && row.right !== null ? formatComparisonValue((row.left ?? 0) - (row.right ?? 0), row.suffix) : "Not reported"}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </ShellPanel>
                    <ResourceUsageChart metrics={filteredAnalyticsMetrics} />
                  </div>

                  <div className="grid gap-5 xl:grid-cols-2">
                    <GroupScoreChart groups={dashboard.group_inventory.filter((group) => analyticsGroupFilter === "all" || group.group === analyticsGroupFilter)} />
                    <RunStatusChart runs={analyticsRunSubset} />
                  </div>

                  <div className="grid gap-5 xl:grid-cols-2">
                    {cpuHistory ? <FleetMetricHistoryChart series={cpuHistory} /> : null}
                    {thermalHistory ? <FleetMetricHistoryChart series={thermalHistory} /> : null}
                    {fanHistory ? <FleetMetricHistoryChart series={fanHistory} /> : null}
                    {networkHistory ? <FleetMetricHistoryChart series={networkHistory} /> : null}
                  </div>

                  <div className="grid gap-5 xl:grid-cols-2">
                    <ShellPanel title="Regression Insights" subtitle="Recent score drops and quality regressions based on prior runs.">
                      <div className="space-y-3">
                        {analyticsRegressions.map((item) => (
                          <div key={`${item.serverId}-${item.task}-${item.updatedAt}`} className="clone-list-row">
                            <div>
                              <p className="font-semibold text-[#262626]">{nice(item.task)}</p>
                              <p className="mt-1 text-sm text-[#a3a3a3]">{dashboard.servers.find((server) => server.server_id === item.serverId)?.server_name ?? item.serverId}</p>
                            </div>
                            <div className="text-sm text-[#737373]">Prev {Math.round(item.previousScore)}</div>
                            <div className="text-sm text-[#737373]">Now {Math.round(item.latestScore)}</div>
                            <div><span className={statusClass(item.severity)}>{item.delta >= 0 ? `+${Math.round(item.delta)}` : `${Math.round(item.delta)}`}</span></div>
                          </div>
                        ))}
                        {!analyticsRegressions.length ? <div className="clone-empty-state">No clear score regressions are detected from recent runs.</div> : null}
                      </div>
                    </ShellPanel>
                    <ShellPanel title="Reports" subtitle="Use the current filters to export decision-ready analytics snapshots.">
                      <div className="space-y-3">
                        <div className="clone-helper-copy">
                          <p>The export uses the active period, group, platform, and selected comparison servers.</p>
                          <p>PDF is best for reviews, CSV for spreadsheets, and JSON for integrations.</p>
                        </div>
                        <div className="tracker-section-grid">
                          <div className="clone-data-chip"><span>Period</span><strong>{analyticsPeriod}</strong></div>
                          <div className="clone-data-chip"><span>Group</span><strong>{analyticsGroupFilter === "all" ? "All groups" : analyticsGroupFilter}</strong></div>
                          <div className="clone-data-chip"><span>Platform</span><strong>{analyticsPlatformFilter === "all" ? "All platforms" : analyticsPlatformFilter}</strong></div>
                          <div className="clone-data-chip"><span>Compared</span><strong>{analyticsCompareServer?.server_name ?? "Not selected"}</strong></div>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <button type="button" className="clone-primary-action" onClick={() => exportAnalyticsDetails("pdf")}>Download PDF report</button>
                          <button type="button" className="clone-secondary-action" onClick={() => exportAnalyticsDetails("csv")}>Download CSV</button>
                          <button type="button" className="clone-secondary-action" onClick={() => exportAnalyticsDetails("json")}>Download JSON</button>
                        </div>
                        {analyticsHistoryLoading ? <div className="clone-empty-state">Loading analytics history...</div> : null}
                      </div>
                    </ShellPanel>
                  </div>
                </>
              )}
            </div>
          ) : null}

          {activeNav === "Settings" ? (
            <div className="grid gap-5 xl:grid-cols-[minmax(0,1.5fr)_320px]">
              <ShellPanel title="Environment Settings" subtitle="Operational context and current dashboard bindings without breaking the cloned shell.">
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="clone-data-chip clone-data-chip--large">
                    <span>Connection</span>
                    <strong>{connectionLabel(connection)}</strong>
                  </div>
                  <div className="clone-data-chip clone-data-chip--large">
                    <span>Last update</span>
                    <strong>{formatDateTime(lastUpdated)}</strong>
                  </div>
                  <div className="clone-data-chip clone-data-chip--large">
                    <span>Allowed tasks</span>
                    <strong>{dashboard.allowed_tasks.length}</strong>
                  </div>
                  <div className="clone-data-chip clone-data-chip--large">
                    <span>Workflow templates</span>
                    <strong>{dashboard.workflow_templates.length}</strong>
                  </div>
                  <div className="clone-data-chip clone-data-chip--large">
                    <span>Baselines</span>
                    <strong>{baselines.length}</strong>
                  </div>
                </div>
                <div className="mt-6 grid gap-5 md:grid-cols-2">
                  <div className="space-y-3">
                    <p className="clone-section-title">Schedules</p>
                    <div className="clone-helper-copy">
                      <p>{schedules.length} recurring workflows configured.</p>
                      <p>{activeAlertCount} active alerts currently open.</p>
                    </div>
                    <div className="flex gap-3">
                      <input className="clone-search-input min-w-0" value={scheduleInterval} onChange={(event) => setScheduleInterval(event.target.value)} placeholder="Minutes" />
                      <button
                        className="clone-secondary-action"
                        onClick={() =>
                          selectedServerId &&
                          selectedWorkflow &&
                          void createSchedule({
                            name: `${nice(selectedWorkflow)} every ${scheduleInterval}m`,
                            server_id: selectedServerId,
                            workflow: selectedWorkflow,
                            interval_minutes: Number(scheduleInterval) || 60
                          })
                        }
                      >
                        Add schedule
                      </button>
                    </div>
                    <div className="space-y-2">
                      {schedules.slice(0, 4).map((schedule: ScheduleRecord) => (
                        <div key={schedule.schedule_id} className="clone-data-chip">
                          <span>{schedule.name}</span>
                          <strong>{schedule.interval_minutes}m</strong>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="space-y-3">
                    <p className="clone-section-title">Notifications</p>
                    <div className="flex gap-3">
                      <ConsoleDropdown
                        label="Channel"
                        value={notificationChannel}
                        options={[
                          { value: "webhook", label: "Webhook" },
                          { value: "email", label: "Email" }
                        ]}
                        onChange={(value) => setNotificationChannel(value as "email" | "webhook")}
                        placeholder="Channel"
                      />
                    </div>
                    <div className="clone-search-input">
                      <span className="icon-search icon-search--small" />
                      <input value={notificationTarget} onChange={(event) => setNotificationTarget(event.target.value)} placeholder={notificationChannel === "email" ? "ops@example.com" : "https://hooks.example.com"} />
                    </div>
                    <button
                      className="clone-secondary-action"
                      onClick={() =>
                        notificationTarget &&
                        void createNotificationEndpoint({
                          name: `${notificationChannel.toUpperCase()} endpoint`,
                          channel: notificationChannel,
                          target: notificationTarget
                        })
                      }
                    >
                      Add notification target
                    </button>
                    <div className="space-y-2">
                      {notificationEndpoints.slice(0, 4).map((endpoint) => (
                        <div key={endpoint.endpoint_id} className="clone-data-chip">
                          <span>{endpoint.name}</span>
                          <strong>{endpoint.channel}</strong>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
                <div className="mt-6 space-y-4">
                  <p className="clone-section-title">Alert rules</p>
                  <p className="text-sm text-[#737373]">Threshold rules evaluated against live signals. Requires operator role.</p>
                  <div className="flex flex-wrap gap-3">
                    <div className="clone-search-input min-w-[10rem] flex-1">
                      <input value={ruleName} onChange={(event) => setRuleName(event.target.value)} placeholder="Rule name" />
                    </div>
                    <div className="clone-search-input min-w-[10rem] flex-1">
                      <input value={ruleSignal} onChange={(event) => setRuleSignal(event.target.value)} placeholder="Signal key" />
                    </div>
                    <div className="clone-search-input w-[6rem]">
                      <input value={ruleThreshold} onChange={(event) => setRuleThreshold(event.target.value)} placeholder="%" inputMode="decimal" />
                    </div>
                    <ConsoleDropdown
                      label="Severity"
                      value={ruleSeverity}
                      options={[
                        { value: "info", label: "Info" },
                        { value: "warning", label: "Warning" },
                        { value: "critical", label: "Critical" }
                      ]}
                      onChange={(value) => setRuleSeverity(value as "info" | "warning" | "critical")}
                      placeholder="Severity"
                    />
                    <button
                      type="button"
                      className="clone-secondary-action shrink-0 px-5"
                      disabled={actionPending || !ruleName.trim() || !ruleSignal.trim()}
                      onClick={() =>
                        void createAlertRule({
                          name: ruleName.trim(),
                          signal: ruleSignal.trim(),
                          threshold: Number(ruleThreshold) || 0,
                          severity: ruleSeverity
                        }).then(() => {
                          setRuleName("");
                        })
                      }
                    >
                      Add rule
                    </button>
                  </div>
                  <div className="space-y-2">
                    {alertRules.length ? (
                      alertRules.map((rule) => (
                        <div key={rule.rule_id} className="clone-data-chip">
                          <span>{rule.name}</span>
                          <strong>
                            {rule.signal} &gt; {rule.threshold} ({nice(rule.severity)}) {rule.enabled ? "" : "• off"}
                          </strong>
                        </div>
                      ))
                    ) : (
                      <div className="clone-empty-state">No custom alert rules yet.</div>
                    )}
                  </div>
                </div>
                <div className="mt-6 grid gap-5 md:grid-cols-2">
                  <div className="space-y-3">
                    <p className="clone-section-title">Baseline Policies</p>
                    <div className="flex gap-3">
                      <input className="clone-search-input min-w-0" value={baselineScore} onChange={(event) => setBaselineScore(event.target.value)} placeholder="Minimum score" />
                      <button
                        className="clone-secondary-action"
                        onClick={() =>
                          primaryServer &&
                          selectedTask &&
                          void createBaseline({
                            name: `${primaryServer.group} ${nice(selectedTask)} baseline`,
                            group: primaryServer.group,
                            task: selectedTask,
                            minimum_score: Number(baselineScore) || 85
                          })
                        }
                      >
                        Add baseline
                      </button>
                    </div>
                    <div className="space-y-2">
                      {baselines.slice(0, 4).map((baseline) => (
                        <div key={baseline.baseline_id} className="clone-data-chip">
                          <span>{baseline.name}</span>
                          <strong>{baseline.minimum_score}</strong>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="space-y-3">
                    <p className="clone-section-title">Exports</p>
                    <div className="clone-helper-copy">
                      <p>Downloadable benchmark and run exports now have JSON endpoints.</p>
                      <p>Use export to feed CI/CD, reports, or downstream analytics.</p>
                    </div>
                    <button
                      className="clone-secondary-action"
                      onClick={() =>
                        void exportBenchmarks().then((payload) => {
                          const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
                          const url = URL.createObjectURL(blob);
                          const anchor = document.createElement("a");
                          anchor.href = url;
                          anchor.download = "prometheus-benchmarks.json";
                          anchor.click();
                          URL.revokeObjectURL(url);
                        })
                      }
                    >
                      Export benchmark JSON
                    </button>
                  </div>
                </div>
              </ShellPanel>

              <ControlHub
                dashboard={dashboard}
                selectedServerId={selectedServerId}
                setSelectedServerId={setSelectedServerId}
                selectedTask={selectedTask}
                setSelectedTask={setSelectedTask}
                selectedWorkflow={selectedWorkflow}
                setSelectedWorkflow={setSelectedWorkflow}
                actionPending={actionPending}
                actionError={actionError}
                actionSuccess={actionSuccess}
                triggerTask={triggerTask}
                triggerWorkflow={triggerWorkflow}
              />
            </div>
          ) : null}
        </main>
      </div>

      {overlayOpen ? (
        <div className="clone-overlay-backdrop" onClick={() => setControlsOpen(false)}>
          <div
            ref={overlayPanelRef}
            id="execution-console"
            role="dialog"
            aria-modal="true"
            aria-label="Execution console"
            className="clone-overlay-shell"
            onClick={(event) => event.stopPropagation()}
            tabIndex={-1}
          >
            <ControlHub
              dashboard={dashboard}
              selectedServerId={selectedServerId}
              setSelectedServerId={setSelectedServerId}
              selectedTask={selectedTask}
              setSelectedTask={setSelectedTask}
              selectedWorkflow={selectedWorkflow}
              setSelectedWorkflow={setSelectedWorkflow}
              actionPending={actionPending}
              actionError={actionError}
              actionSuccess={actionSuccess}
              triggerTask={triggerTask}
              triggerWorkflow={triggerWorkflow}
              onClose={() => setControlsOpen(false)}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}

export { App };
