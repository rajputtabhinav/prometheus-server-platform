import type { MetricSnapshot, ServerRecord } from "../types";

interface FleetPanelProps {
  servers: ServerRecord[];
  latestMetrics: MetricSnapshot[];
}

function MetricBar({ label, value, accent }: { label: string; value: string; accent: string }) {
  const numericValue = Number.parseFloat(value);
  const width = Number.isFinite(numericValue) ? Math.min(numericValue, 100) : 0;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs text-mist">
        <span>{label}</span>
        <span className="font-mono text-white">{value}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-white/8">
        <div className={`h-full rounded-full ${accent}`} style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}

export function FleetPanel({ servers, latestMetrics }: FleetPanelProps) {
  const metricsByServer = new Map(latestMetrics.map((metric) => [metric.server_id, metric]));

  return (
    <div className="glass-panel h-full p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-mist">Fleet Surface</p>
          <h3 className="mt-2 font-display text-2xl text-white">Live server posture</h3>
        </div>
        <p className="rounded-full border border-white/10 px-3 py-1 text-xs text-mist">
          {servers.length} tracked nodes
        </p>
      </div>

      <div className="space-y-4">
        {servers.map((server) => {
          const metric = metricsByServer.get(server.server_id);
          return (
            <article key={server.server_id} className="rounded-3xl border border-white/10 bg-white/5 p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="flex items-center gap-3">
                    <h4 className="font-display text-xl text-white">{server.server_name}</h4>
                    <span
                      className={`rounded-full px-2 py-1 text-[10px] uppercase tracking-[0.22em] ${
                        server.status === "online"
                          ? "bg-signal/15 text-signal"
                          : "bg-danger/15 text-danger"
                      }`}
                    >
                      {server.status}
                    </span>
                    <span
                      className={`rounded-full px-2 py-1 text-[10px] uppercase tracking-[0.22em] ${
                        server.health === "PASS"
                          ? "bg-signal/15 text-signal"
                          : server.health === "WARNING"
                            ? "bg-ember/15 text-ember"
                            : "bg-danger/15 text-danger"
                      }`}
                    >
                      {server.health}
                    </span>
                  </div>
                  <p className="mt-2 text-sm text-mist">
                    Group: <span className="text-white">{server.group}</span>
                  </p>
                </div>

                <div className="flex flex-wrap gap-2">
                  {server.tags.map((tag) => (
                    <span key={tag} className="rounded-full border border-white/10 px-3 py-1 text-xs text-mist">
                      {tag}
                    </span>
                  ))}
                </div>
              </div>

              <div className="mt-5 grid gap-4 md:grid-cols-2">
                <MetricBar
                  label="CPU"
                  value={`${metric?.cpu ?? 0}%`}
                  accent="bg-gradient-to-r from-signal to-signal/60"
                />
                <MetricBar
                  label="Memory"
                  value={`${metric?.memory ?? 0}%`}
                  accent="bg-gradient-to-r from-ember to-ember/60"
                />
                <MetricBar
                  label="Disk"
                  value={`${metric?.disk ?? 0}%`}
                  accent="bg-gradient-to-r from-white/70 to-white/30"
                />
                <MetricBar
                  label="Net"
                  value={`${metric?.network_mbps ?? 0} Mbps`}
                  accent="bg-gradient-to-r from-signal/70 to-white/30"
                />
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}

