// StepInspector — exact detail for a selected step.
//
// Resolves blob refs to actual content and renders prompt/response/args/result.
// Shows a blame section when a blame prop is provided.

import { resolveBlob } from "./utils/resolveBlob.js";

// Render a single resolved blob value inside a styled card.
function BlobContent({ label, value }) {
  const isNull = value === null || value === undefined;
  return (
    <div className="space-y-1">
      <span className="text-xs font-medium uppercase tracking-wider text-zinc-500">
        {label}
      </span>
      {isNull ? (
        <p className="text-xs text-zinc-600 italic">content unavailable</p>
      ) : typeof value === "object" ? (
        <pre className="overflow-auto rounded bg-zinc-800 p-3 font-mono text-xs text-zinc-300 leading-relaxed">
          {JSON.stringify(value, null, 2)}
        </pre>
      ) : (
        <pre className="overflow-auto rounded bg-zinc-800 p-3 font-mono text-xs text-zinc-300 leading-relaxed whitespace-pre-wrap">
          {value}
        </pre>
      )}
    </div>
  );
}

export default function StepInspector({ trace, stepId, blame }) {
  const step = trace.steps.find((s) => s.step_id === stepId);

  // Resolve blame info for this step.
  const blameEntry =
    blame && blame.steps
      ? blame.steps.find((b) => b.step_id === stepId)
      : null;
  const isRootCause = blame && blame.root_cause_step_id === stepId;
  const isFailedStep = blame && blame.failed_step_id === stepId;
  const isContributor =
    !isRootCause && blameEntry && blameEntry.blame_score > 0;
  const showBlame =
    blame != null && (isRootCause || isFailedStep || isContributor);

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
            {/* --- Metadata --- */}
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

            {/* --- Content section (resolved blobs) --- */}
            <div>
              <dt className="text-xs font-medium uppercase tracking-wider text-zinc-500 mb-2">
                Content
              </dt>
              <dd className="space-y-3">
                {step.type === "llm_call" && (
                  <>
                    <BlobContent
                      label="Prompt"
                      value={resolveBlob(step.prompt_blob)}
                    />
                    <BlobContent
                      label="Response"
                      value={resolveBlob(step.response_blob)}
                    />
                  </>
                )}
                {step.type === "tool_call" && (
                  <>
                    <BlobContent
                      label="Args"
                      value={resolveBlob(step.args_blob)}
                    />
                    <BlobContent
                      label="Result"
                      value={resolveBlob(step.result_blob)}
                    />
                  </>
                )}
              </dd>
            </div>

            {/* --- Blame section (only when blame prop is supplied and this step appears) --- */}
            {showBlame && (
              <div>
                <dt className="text-xs font-medium uppercase tracking-wider text-zinc-500 mb-2">
                  Blame
                </dt>
                <dd className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    {isRootCause && (
                      <span className="rounded-full bg-red-900/60 px-2 py-0.5 text-xs font-semibold text-red-300 ring-1 ring-red-700/50">
                        root cause
                      </span>
                    )}
                    {isContributor && !isRootCause && (
                      <span className="rounded-full bg-amber-900/60 px-2 py-0.5 text-xs font-semibold text-amber-300 ring-1 ring-amber-700/50">
                        contributor
                      </span>
                    )}
                    {isFailedStep && (
                      <span className="rounded-full bg-zinc-700/60 px-2 py-0.5 text-xs font-semibold text-zinc-300 ring-1 ring-zinc-600/50">
                        failed here
                      </span>
                    )}
                    {blameEntry && (
                      <span className="font-mono text-xs text-zinc-400">
                        score: {(blameEntry.blame_score * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                  {blameEntry && blameEntry.rationale && (
                    <p className="text-xs text-zinc-400 leading-relaxed">
                      {blameEntry.rationale}
                    </p>
                  )}
                </dd>
              </div>
            )}
          </dl>
        )}
      </div>
    </div>
  );
}
