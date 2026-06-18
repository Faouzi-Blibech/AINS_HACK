// TraceGraph — the execution DAG / trajectory tree view.
//
// Day 2: lay out steps as a graph (D3), color by blame score.
// For now: placeholder that lists steps and supports selection.

export default function TraceGraph({ trace, selectedStepId, onSelectStep }) {
  return (
    <div className="flex h-full min-h-0 flex-col rounded-lg border border-zinc-800 bg-zinc-900/50">
      <div className="shrink-0 border-b border-zinc-800 px-4 py-3">
        <h2 className="text-sm font-medium text-zinc-200">Trace Graph</h2>
        <p className="mt-0.5 font-mono text-xs text-zinc-500">
          {trace.run_id}
        </p>
      </div>

      <div className="flex flex-1 flex-col items-center justify-center overflow-auto p-6">
        <p className="mb-4 text-xs uppercase tracking-wider text-zinc-600">
          Graph canvas — Day 2
        </p>
        <div className="flex w-full max-w-md flex-col gap-2">
          {trace.steps.map((step) => {
            const isSelected = step.step_id === selectedStepId;
            const label =
              step.type === "llm_call"
                ? `LLM · ${step.model ?? "unknown"}`
                : `Tool · ${step.tool ?? "unknown"}`;

            return (
              <button
                key={step.step_id}
                type="button"
                onClick={() => onSelectStep(step.step_id)}
                className={[
                  "flex items-center justify-between rounded-md border px-4 py-3 text-left text-sm transition-colors",
                  isSelected
                    ? "border-sky-500/50 bg-sky-500/10 text-sky-100"
                    : "border-zinc-700 bg-zinc-800/50 text-zinc-300 hover:border-zinc-600 hover:bg-zinc-800",
                ].join(" ")}
              >
                <span>
                  <span className="font-mono text-zinc-500">
                    #{step.step_id}
                  </span>{" "}
                  {label}
                </span>
                {step.side_effecting && (
                  <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-xs text-amber-400">
                    side-effect
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
