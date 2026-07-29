import type { WorkflowRun, WorkflowTemplate } from "../types";

interface WorkflowPanelProps {
  workflows: WorkflowRun[];
  templates: WorkflowTemplate[];
}

export function WorkflowPanel({ workflows, templates }: WorkflowPanelProps) {
  return (
    <div className="glass-panel h-full p-6">
      <div className="mb-6">
        <p className="text-xs uppercase tracking-[0.25em] text-mist">Automation Spine</p>
        <h3 className="mt-2 font-display text-2xl text-white">Workflow execution state</h3>
      </div>

      <div className="space-y-4">
        {workflows.map((workflow) => {
          const progress = ((workflow.current_step_index + 1) / workflow.steps.length) * 100;
          return (
            <article key={workflow.workflow_id} className="rounded-3xl border border-white/10 bg-white/5 p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h4 className="font-display text-xl text-white">{workflow.workflow}</h4>
                  <p className="mt-2 text-sm text-mist">
                    Step {Math.min(workflow.current_step_index + 1, workflow.steps.length)} of {workflow.steps.length}
                  </p>
                </div>
                <span
                  className={`rounded-full px-3 py-1 text-[10px] uppercase tracking-[0.22em] ${
                    workflow.status === "completed"
                      ? "bg-signal/15 text-signal"
                      : workflow.status === "failed"
                        ? "bg-danger/15 text-danger"
                        : "bg-ember/15 text-ember"
                  }`}
                >
                  {workflow.status}
                </span>
              </div>
              <div className="mt-4 h-2 overflow-hidden rounded-full bg-white/8">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-signal via-ember to-white/60"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                {workflow.steps.map((step, index) => (
                  <span
                    key={`${workflow.workflow_id}-${step}`}
                    className={`rounded-full px-3 py-1 text-xs ${
                      index <= workflow.current_step_index
                        ? "bg-signal/12 text-signal"
                        : "border border-white/10 text-mist"
                    }`}
                  >
                    {step}
                  </span>
                ))}
              </div>
            </article>
          );
        })}
      </div>

      <div className="mt-8 border-t border-white/10 pt-6">
        <p className="text-xs uppercase tracking-[0.25em] text-mist">Templates</p>
        <div className="mt-4 grid gap-3">
          {templates.map((template) => (
            <div key={template.name} className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="flex items-center justify-between gap-3">
                <p className="font-display text-lg text-white">{template.name}</p>
                <span className="font-mono text-xs text-mist">{template.steps.length} steps</span>
              </div>
              <p className="mt-2 text-sm leading-6 text-mist">{template.summary}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

