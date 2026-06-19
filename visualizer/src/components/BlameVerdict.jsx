export default function BlameVerdict({ blame }) {
  if (!blame) return null;

  const confidencePct = Math.round(blame.confidence * 100);
  const isConfident = blame.confidence >= 0.6;

  return (
    <div className="shrink-0 rounded-lg border border-zinc-800 bg-zinc-900/70 px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {/* Verdict sentence */}
        <p className="flex-1 text-sm font-medium text-zinc-100 min-w-0">
          {blame.verdict}
        </p>

        {/* Chips row */}
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          {/* Confidence badge */}
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${
              isConfident
                ? "bg-emerald-500/10 text-emerald-400 ring-emerald-500/20"
                : "bg-amber-500/10 text-amber-400 ring-amber-500/20"
            }`}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-current opacity-80" />
            {isConfident ? "confident" : "needs review"} &middot; {confidencePct}%
          </span>

          {/* Root cause chip */}
          {blame.root_cause_step_id != null && (
            <span className="inline-flex items-center rounded-full bg-red-500/10 px-2.5 py-0.5 text-xs font-medium text-red-400 ring-1 ring-inset ring-red-500/20">
              root cause: step {blame.root_cause_step_id}
            </span>
          )}

          {/* Failed at chip */}
          {blame.failed_step_id != null && (
            <span className="inline-flex items-center rounded-full bg-zinc-500/10 px-2.5 py-0.5 text-xs font-medium text-zinc-400 ring-1 ring-inset ring-zinc-500/20">
              failed at: step {blame.failed_step_id}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
