import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import BlameVerdict from "../components/BlameVerdict.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import StepInspector from "../StepInspector.jsx";
import TraceGraph from "../TraceGraph.jsx";
import { MOCK_BLAME } from "../mocks/mock_blame.js";
import { truncateRunId } from "../utils/format.js";

export default function RunInspector() {
  const { runId } = useParams();
  const [trace, setTrace] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedStepId, setSelectedStepId] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function loadTrace() {
      setLoading(true);
      setError(null);
      try {
        const url = new URL("../mocks/mock_trace_fixture.json", import.meta.url);
        const response = await fetch(url);
        if (!response.ok) {
          throw new Error(`Failed to load mock trace (${response.status})`);
        }
        const data = await response.json();
        console.log("[RunInspector] mock trace loaded:", data);
        if (!cancelled) {
          setTrace(data);
          setSelectedStepId(data.steps[0]?.step_id ?? null);
        }
      } catch (err) {
        console.error("[RunInspector] failed to load mock trace:", err);
        if (!cancelled) {
          setError(err.message);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    loadTrace();
    return () => {
      cancelled = true;
    };
  }, [runId]);

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center p-6 text-sm text-zinc-500">
        Loading trace…
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-1 items-center justify-center p-6 text-sm text-red-400">
        Error: {error}
      </div>
    );
  }

  if (!trace) {
    return (
      <div className="flex flex-1 items-center justify-center p-6 text-sm text-zinc-500">
        No trace data.
      </div>
    );
  }

  return (
    <div className="flex h-[100dvh] min-h-0 flex-col md:h-auto md:min-h-screen">
      <header className="shrink-0 border-b border-zinc-800 bg-zinc-900/80 px-4 py-3 sm:px-6">
        <Link
          to="/"
          className="text-xs text-zinc-500 transition-colors hover:text-zinc-300"
        >
          ← Dashboard
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="font-mono text-sm text-zinc-100" title={trace.run_id}>
            {truncateRunId(trace.run_id)}
          </h1>
          <span className="text-zinc-600">·</span>
          <span className="text-sm text-zinc-400">{trace.agent}</span>
          <span className="text-zinc-600">·</span>
          <span className="text-sm text-zinc-500">{trace.mode}</span>
          {trace.status && <StatusBadge status={trace.status} />}
        </div>
      </header>

      <div className="shrink-0 px-4 pt-4 lg:px-6 lg:pt-6">
        <BlameVerdict blame={MOCK_BLAME} />
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-hidden p-4 lg:grid-cols-[1fr_22rem] lg:p-6">
        <TraceGraph
          trace={trace}
          selectedStepId={selectedStepId}
          onSelectStep={setSelectedStepId}
          blame={MOCK_BLAME}
        />
        <StepInspector trace={trace} stepId={selectedStepId} blame={MOCK_BLAME} />
      </div>
    </div>
  );
}
