import type { AllowedTask } from "../types";

interface TaskCatalogProps {
  tasks: AllowedTask[];
}

export function TaskCatalog({ tasks }: TaskCatalogProps) {
  return (
    <div className="glass-panel h-full p-6">
      <div className="mb-6">
        <p className="text-xs uppercase tracking-[0.25em] text-mist">Execution Catalog</p>
        <h3 className="mt-2 font-display text-2xl text-white">Whitelisted task library</h3>
      </div>

      <div className="grid gap-4">
        {tasks.map((task) => (
          <article key={task.name} className="rounded-3xl border border-white/10 bg-white/5 p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h4 className="font-display text-xl text-white">{task.name}</h4>
              <span className="font-mono text-xs text-mist">{task.default_timeout_seconds}s timeout</span>
            </div>
            <p className="mt-3 text-sm leading-6 text-mist">{task.summary}</p>
            <div className="mt-4 rounded-2xl border border-white/10 bg-night/60 p-3 font-mono text-xs text-signal/90">
              {JSON.stringify(task.sample_params)}
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

