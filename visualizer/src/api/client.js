// Cassette API client
// Base URL from VITE_API_URL env var; falls back to localhost:8000.

const BASE = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

async function _get(path) {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    throw new Error(`API ${path} returned ${res.status} ${res.statusText}`);
  }
  return res.json();
}

/** List all run summaries. */
export function listRuns() {
  return _get("/runs");
}

/** Return the full Trace for a run. */
export function getTrace(runId) {
  return _get(`/runs/${encodeURIComponent(runId)}`);
}

/** Return a single ResolvedStepDetail (blobs inlined). */
export function getStep(runId, stepId) {
  return _get(`/runs/${encodeURIComponent(runId)}/steps/${encodeURIComponent(stepId)}`);
}

/** Return the BlameGraphResponse for a run. */
export function getBlame(runId) {
  return _get(`/runs/${encodeURIComponent(runId)}/blame`);
}

/** Query the failure library. Optional substring filter. */
export function getLibrary(q) {
  const qs = q ? `?q=${encodeURIComponent(q)}` : "";
  return _get(`/library${qs}`);
}

/** Return top-level metric cards. */
export function getMetrics() {
  return _get("/metrics");
}
