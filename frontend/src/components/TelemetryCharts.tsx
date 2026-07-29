import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { DashboardSummary, FleetComponentSummary, FleetMetricHistorySeries, HistoryPoint, MetricSnapshot } from "../types";

type ThemePalette = {
  axis: string;
  label: string;
  grid: string;
  tooltipBackground: string;
  tooltipBorder: string;
  primary: string;
  primarySoft: string;
  secondary: string;
  warning: string;
  danger: string;
  neutral: string;
  textPrimary: string;
  textSecondary: string;
  statusColors: Record<string, string>;
};

function ChartFrame({
  minHeight = 240,
  children,
}: {
  minHeight?: number;
  children: (size: { width: number; height: number }) => ReactNode;
}) {
  const frameRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 0, height: minHeight });

  useEffect(() => {
    const element = frameRef.current;
    if (!element) return;

    const updateSize = () => {
      const width = element.clientWidth;
      const height = element.clientHeight;
      setSize({
        width: Math.max(width, 0),
        height: Math.max(height, minHeight),
      });
    };

    updateSize();

    const observer = new ResizeObserver(() => updateSize());
    observer.observe(element);
    return () => observer.disconnect();
  }, [minHeight]);

  return (
    <div ref={frameRef} className="clone-chart-frame" style={{ minHeight, height: "100%" }}>
      {size.width > 0 && size.height > 0 ? children(size) : null}
    </div>
  );
}

function cssVar(name: string, fallback: string) {
  if (typeof window === "undefined") {
    return fallback;
  }
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function chartPalette(): ThemePalette {
  const primary = cssVar("--chart-primary", "#111111");
  const secondary = cssVar("--chart-secondary", "#e1306c");
  const warning = cssVar("--chart-warning", "#f59e0b");
  const danger = cssVar("--chart-danger", "#ef4444");
  const neutral = cssVar("--chart-neutral", "#a3a3a3");
  return {
    axis: cssVar("--chart-axis", "#8a8a8a"),
    label: cssVar("--chart-label", "#525252"),
    grid: cssVar("--chart-grid", "#e5e5e5"),
    tooltipBackground: cssVar("--chart-tooltip-bg", "#111111"),
    tooltipBorder: cssVar("--chart-tooltip-border", "rgba(255,255,255,0.08)"),
    primary,
    primarySoft: cssVar("--chart-primary-soft", "rgba(17, 17, 17, 0.18)"),
    secondary,
    warning,
    danger,
    neutral,
    textPrimary: cssVar("--text-primary", "#262626"),
    textSecondary: cssVar("--text-secondary", "#737373"),
    statusColors: {
      completed: secondary,
      running: primary,
      pending: warning,
      failed: danger,
      cancelled: neutral,
    },
  };
}

function chartTooltipStyle(palette: ThemePalette) {
  return {
    backgroundColor: palette.tooltipBackground,
    border: `1px solid ${palette.tooltipBorder}`,
    borderRadius: "18px",
    color: "#ffffff",
    boxShadow: "0 18px 34px rgba(9,78,88,0.22)",
  };
}

function formatTooltipValue(value: unknown) {
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  if (typeof value === "number") {
    return String(Math.round(value));
  }
  if (typeof value === "string") {
    return value;
  }
  return "--";
}

export function ReadinessHistoryChart({
  history,
  period,
}: {
  history: HistoryPoint[];
  period: string;
}) {
  const palette = chartPalette();
  return (
    <article className="clone-chart-card">
      <div className="clone-chart-card__header">
        <div>
          <p className="clone-section-title">Readiness Trend</p>
          <p className="clone-chart-card__caption">Real {period.toLowerCase()} history from recorded benchmark runs.</p>
        </div>
      </div>
      <div className="clone-chart-card__body">
        <ChartFrame minHeight={240}>
          {({ width, height }) => (
          <ResponsiveContainer width={width} height={height} minWidth={0} minHeight={240}>
            <AreaChart data={history} margin={{ top: 18, right: 10, left: -18, bottom: 0 }}>
              <defs>
                <linearGradient id="readinessFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={palette.primary} stopOpacity={0.42} />
                  <stop offset="95%" stopColor={palette.primary} stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke={palette.grid} strokeDasharray="4 4" vertical={false} />
              <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: palette.axis, fontSize: 12 }} />
              <YAxis domain={[0, 100]} tickLine={false} axisLine={false} tick={{ fill: palette.axis, fontSize: 12 }} width={32} />
              <Tooltip
                contentStyle={chartTooltipStyle(palette)}
                formatter={(value, name) =>
                  name === "value" ? [`${formatTooltipValue(value)}%`, "Readiness"] : [formatTooltipValue(value), "Completed runs"]
                }
              />
              <Area type="monotone" dataKey="value" stroke={palette.primary} strokeWidth={3} fill="url(#readinessFill)" activeDot={{ r: 5 }} />
            </AreaChart>
          </ResponsiveContainer>
          )}
        </ChartFrame>
      </div>
    </article>
  );
}

export function ResourceUsageChart({
  metrics,
}: {
  metrics: Array<MetricSnapshot & { serverName: string }>;
}) {
  const palette = chartPalette();
  const chartData = metrics.slice(0, 6).map((metric) => ({
    name: metric.serverName.length > 10 ? `${metric.serverName.slice(0, 10)}...` : metric.serverName,
    cpu: Math.round(metric.cpu),
    memory: Math.round(metric.memory),
    disk: Math.round(metric.disk),
  }));

  return (
    <article className="clone-chart-card">
      <div className="clone-chart-card__header">
        <div>
          <p className="clone-section-title">Resource Pressure</p>
          <p className="clone-chart-card__caption">CPU, memory, and disk pressure across the hottest visible nodes.</p>
        </div>
      </div>
      <div className="clone-chart-card__body">
        <ChartFrame minHeight={240}>
          {({ width, height }) => (
          <ResponsiveContainer width={width} height={height} minWidth={0} minHeight={240}>
            <BarChart data={chartData} margin={{ top: 18, right: 10, left: -18, bottom: 0 }} barGap={6}>
              <CartesianGrid stroke={palette.grid} strokeDasharray="4 4" vertical={false} />
              <XAxis dataKey="name" tickLine={false} axisLine={false} tick={{ fill: palette.axis, fontSize: 12 }} />
              <YAxis domain={[0, 100]} tickLine={false} axisLine={false} tick={{ fill: palette.axis, fontSize: 12 }} width={32} />
              <Tooltip contentStyle={chartTooltipStyle(palette)} />
              <Bar dataKey="cpu" fill={palette.primary} radius={[6, 6, 0, 0]} />
              <Bar dataKey="memory" fill={palette.secondary} radius={[6, 6, 0, 0]} />
              <Bar dataKey="disk" fill={palette.warning} radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
          )}
        </ChartFrame>
      </div>
    </article>
  );
}

export function RunStatusChart({
  runs,
}: {
  runs: DashboardSummary["recent_runs"];
}) {
  const palette = chartPalette();
  const order = ["completed", "running", "pending", "failed", "cancelled"];
  const chartData = order
    .map((status) => ({
      name: status,
      value: runs.filter((run) => run.status === status).length,
      color: palette.statusColors[status],
    }))
    .filter((item) => item.value > 0);

  return (
    <article className="clone-chart-card">
      <div className="clone-chart-card__header">
        <div>
          <p className="clone-section-title">Run Status Mix</p>
          <p className="clone-chart-card__caption">Current composition of the recent execution ledger.</p>
        </div>
      </div>
      <div className="clone-chart-card__body clone-chart-card__body--compact">
        <ChartFrame minHeight={200}>
          {({ width, height }) => (
          <ResponsiveContainer width={width} height={height} minWidth={0} minHeight={200}>
            <PieChart>
              <Pie data={chartData} dataKey="value" nameKey="name" innerRadius={58} outerRadius={88} paddingAngle={3}>
                {chartData.map((entry) => (
                  <Cell key={entry.name} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip contentStyle={chartTooltipStyle(palette)} formatter={(value, name) => [formatTooltipValue(value), String(name)]} />
            </PieChart>
          </ResponsiveContainer>
          )}
        </ChartFrame>
      </div>
      <div className="clone-chart-legend">
        {chartData.map((entry) => (
          <div key={entry.name} className="clone-chart-legend__item">
            <span className="clone-chart-legend__swatch" style={{ backgroundColor: entry.color }} />
            <span>{entry.name}</span>
            <strong>{entry.value}</strong>
          </div>
        ))}
      </div>
    </article>
  );
}

export function GroupScoreChart({
  groups,
}: {
  groups: DashboardSummary["group_inventory"];
}) {
  const palette = chartPalette();
  const chartData = groups.slice(0, 6).map((group) => ({
    group: group.group,
    score: Math.round(group.average_score),
    alerts: group.active_alerts,
  }));

  return (
    <article className="clone-chart-card">
      <div className="clone-chart-card__header">
        <div>
          <p className="clone-section-title">Group Readiness</p>
          <p className="clone-chart-card__caption">Average score and alert pressure by server group.</p>
        </div>
      </div>
      <div className="clone-chart-card__body">
        <ChartFrame minHeight={240}>
          {({ width, height }) => (
          <ResponsiveContainer width={width} height={height} minWidth={0} minHeight={240}>
            <BarChart data={chartData} layout="vertical" margin={{ top: 8, right: 10, left: 18, bottom: 0 }}>
              <CartesianGrid stroke={palette.grid} strokeDasharray="4 4" horizontal={false} />
              <XAxis type="number" domain={[0, 100]} tickLine={false} axisLine={false} tick={{ fill: palette.axis, fontSize: 12 }} />
              <YAxis type="category" dataKey="group" tickLine={false} axisLine={false} tick={{ fill: palette.label, fontSize: 12 }} width={84} />
              <Tooltip contentStyle={chartTooltipStyle(palette)} />
              <Bar dataKey="score" fill={palette.primary} radius={[0, 8, 8, 0]} />
            </BarChart>
          </ResponsiveContainer>
          )}
        </ChartFrame>
      </div>
    </article>
  );
}

export function InfrastructureHealthChart({
  score,
  onlineRatio,
  completedRatio,
  alertPressure,
}: {
  score: number;
  onlineRatio: number;
  completedRatio: number;
  alertPressure: number;
}) {
  const palette = chartPalette();
  const chartData = [
    { name: "Availability", value: Math.max(0, Math.min(onlineRatio, 100)), color: palette.secondary },
    { name: "Run completion", value: Math.max(0, Math.min(completedRatio, 100)), color: palette.warning },
    { name: "Alert resistance", value: Math.max(8, Math.min(100 - alertPressure, 100)), color: palette.primary },
  ];

  return (
    <div className="clone-donut-wrap">
      <ChartFrame minHeight={260}>
        {({ width, height }) => (
        <ResponsiveContainer width={width} height={height} minWidth={0} minHeight={260}>
          <PieChart>
            <Pie
              data={chartData}
              dataKey="value"
              nameKey="name"
              innerRadius={76}
              outerRadius={102}
              startAngle={90}
              endAngle={-270}
              stroke="none"
              paddingAngle={6}
              cornerRadius={12}
            >
              {chartData.map((entry) => (
                <Cell key={entry.name} fill={entry.color} />
              ))}
            </Pie>
            <Tooltip contentStyle={chartTooltipStyle(palette)} formatter={(value, name) => [`${formatTooltipValue(value)}%`, String(name)]} />
            <text x="50%" y="42%" textAnchor="middle" dominantBaseline="middle" fill={palette.textSecondary} fontSize="12" letterSpacing="3">
              FLEET
            </text>
            <text x="50%" y="54%" textAnchor="middle" dominantBaseline="middle" fill={palette.textPrimary} fontSize="32" fontWeight="800">
              {`${Math.round(score)}%`}
            </text>
            <text x="50%" y="67%" textAnchor="middle" dominantBaseline="middle" fill={palette.textSecondary} fontSize="14">
              health index
            </text>
          </PieChart>
        </ResponsiveContainer>
        )}
      </ChartFrame>
    </div>
  );
}

export function FleetMetricHistoryChart({
  series,
}: {
  series: FleetMetricHistorySeries;
}) {
  const palette = chartPalette();
  return (
    <article className="clone-chart-card">
      <div className="clone-chart-card__header">
        <div>
          <p className="clone-section-title">{series.label}</p>
          <p className="clone-chart-card__caption">Short fleet history across reporting components.</p>
        </div>
      </div>
      <div className="clone-chart-card__body">
        <ChartFrame minHeight={240}>
          {({ width, height }) => (
          <ResponsiveContainer width={width} height={height} minWidth={0} minHeight={240}>
            <LineChart data={series.points} margin={{ top: 18, right: 10, left: -18, bottom: 0 }}>
              <CartesianGrid stroke={palette.grid} strokeDasharray="4 4" vertical={false} />
              <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: palette.axis, fontSize: 12 }} />
              <YAxis tickLine={false} axisLine={false} tick={{ fill: palette.axis, fontSize: 12 }} width={42} />
              <Tooltip
                contentStyle={chartTooltipStyle(palette)}
                formatter={(value, name) => [
                  `${formatTooltipValue(value)}${series.unit ? ` ${series.unit}` : ""}`,
                  name === "average_value" ? "Average" : "Peak",
                ]}
              />
              <Line type="monotone" dataKey="average_value" stroke={palette.primary} strokeWidth={3} dot={false} />
              <Line type="monotone" dataKey="max_value" stroke={palette.warning} strokeWidth={2} dot={false} strokeDasharray="5 5" />
            </LineChart>
          </ResponsiveContainer>
          )}
        </ChartFrame>
      </div>
    </article>
  );
}

export function ComponentCoverageChart({
  summaries,
}: {
  summaries: FleetComponentSummary[];
}) {
  const palette = chartPalette();
  const chartData = summaries.map((summary) => ({
    name: summary.label.length > 14 ? `${summary.label.slice(0, 14)}...` : summary.label,
    healthy: summary.healthy_components,
    warning: summary.warning_components,
    failing: summary.failing_components,
  }));
  return (
    <article className="clone-chart-card">
      <div className="clone-chart-card__header">
        <div>
          <p className="clone-section-title">Component Coverage</p>
          <p className="clone-chart-card__caption">Healthy, warning, and failing components across all monitored families.</p>
        </div>
      </div>
      <div className="clone-chart-card__body">
        <ChartFrame minHeight={240}>
          {({ width, height }) => (
          <ResponsiveContainer width={width} height={height} minWidth={0} minHeight={240}>
            <BarChart data={chartData} margin={{ top: 18, right: 10, left: -18, bottom: 0 }}>
              <CartesianGrid stroke={palette.grid} strokeDasharray="4 4" vertical={false} />
              <XAxis dataKey="name" tickLine={false} axisLine={false} tick={{ fill: palette.axis, fontSize: 12 }} />
              <YAxis tickLine={false} axisLine={false} tick={{ fill: palette.axis, fontSize: 12 }} width={32} />
              <Tooltip contentStyle={chartTooltipStyle(palette)} />
              <Bar dataKey="healthy" stackId="a" fill={palette.secondary} radius={[6, 6, 0, 0]} />
              <Bar dataKey="warning" stackId="a" fill={palette.warning} radius={[6, 6, 0, 0]} />
              <Bar dataKey="failing" stackId="a" fill={palette.danger} radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
          )}
        </ChartFrame>
      </div>
    </article>
  );
}
