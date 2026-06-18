// StepInspector — exact detail for a selected step.
//
// Day 2: resolve blob refs, render prompt/response/args.
// For now: placeholder showing step metadata from the trace.

export default function StepInspector({ trace, stepId }) {
  const step = trace.steps.find((s) => s.step_id === stepId);

  return (
    <div className="flex h-full min-h-0 flex-col rounded-lg border border-zinc-800 bg-zinc-900/50">
      <div className="shrink-0 border-b border-zinc-800 px-4 py-3">
        <h2 className="text-sm font-medium text-zinc-200">Step Inspector</h2>
        <p className="mt-0.5 text-xs text-zinc-500">
          {step ? `Step ${step.step_id}` : "No step selected"}
        </p>
      </div>

      <div className="flex-1 overflow-auto p-4">
        {!step ? (
          <p className="text-sm text-zinc-500">
            Select a step in the trace graph to inspect it.
          </p>
        ) : (
          <dl className="space-y-4 text-sm">
            <div>
              <dt className="text-xs font-medium uppercase tracking-wider text-zinc-500">
                Type
              </dt>
              <dd className="mt-1 font-mono text-zinc-200">{step.type}</dd>
            </div>

            {step.type === "llm_call" && step.model && (
              <div>
                <dt className="text-xs font-medium uppercase tracking-wider text-zinc-500">
                  Model
                </dt>
                <dd className="mt-1 text-zinc-200">{step.model}</dd>
              </div>
            )}

            {step.type === "tool_call" && (
              <>
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wider text-zinc-500">
                    Tool
                  </dt>
                  <dd className="mt-1 font-mono text-zinc-200">{step.tool}</dd>
                </div>
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wider text-zinc-500">
                    Transport
                  </dt>
                  <dd className="mt-1 font-mono text-zinc-200">
                    {step.transport}
                  </dd>
                </div>
              </>
            )}

            <div>
              <dt className="text-xs font-medium uppercase tracking-wider text-zinc-500">
                Side effecting
              </dt>
              <dd className="mt-1 text-zinc-200">
                {step.side_effecting ? "Yes" : "No"}
              </dd>
            </div>

            {step.confidence != null && (
              <div>
                <dt className="text-xs font-medium uppercase tracking-wider text-zinc-500">
                  Confidence
                </dt>
                <dd className="mt-1 font-mono text-zinc-200">
                  {(step.confidence * 100).toFixed(0)}%
                </dd>
              </div>
            )}

            <div>
              <dt className="text-xs font-medium uppercase tracking-wider text-zinc-500">
                Blob refs
              </dt>
              <dd className="mt-1 space-y-1 font-mono text-xs text-zinc-500">
                {step.prompt_blob && <div>prompt: {step.prompt_blob}</div>}
                {step.response_blob && (
                  <div>response: {step.response_blob}</div>
                )}
                {step.args_blob && <div>args: {step.args_blob}</div>}
                {step.result_blob && <div>result: {step.result_blob}</div>}
              </dd>
            </div>
          </dl>
        )}
      </div>
    </div>
  );
}
