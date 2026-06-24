// Cassette API client
// Base URL from VITE_API_URL env var; falls back to localhost:8000.

const BASE = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

async function _extractDetail(res, path) {
  try {
    const data = await res.clone().json();
    if (data && data.detail) {
      return typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail);
    }
  } catch (_) {
    // Body was not JSON -- fall through.
  }
  return `API ${path} returned ${res.status} ${res.statusText}`;
}

async function _get(path) {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    throw new Error(await _extractDetail(res, path));
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

/** Return the eval report (4 metrics vs targets). */
export function getEval() {
  return _get("/eval");
}

// ---- POST helpers ----

async function _post(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(await _extractDetail(res, path));
  }
  return res.json();
}

/** POST /runs/{run_id}/inject  ->  {available, injection?, confidence?, rationale?} | {available:false, detail} */
export function postInject(runId, instruction) {
  return _post(`/runs/${encodeURIComponent(runId)}/inject`, { instruction });
}

/** POST /runs/{run_id}/diverge  ->  {fork_run_id, diff, final_status, side_effect_count} */
export function postDiverge(runId, { step_id, target, value }) {
  return _post(`/runs/${encodeURIComponent(runId)}/diverge`, { step_id, target, value });
}

/** POST /runs/{run_id}/record-over  ->  re-run the agent live from the fork with a new value */
export function postRecordOver(runId, { value, step_id }) {
  return _post(`/runs/${encodeURIComponent(runId)}/record-over`, { value, step_id });
}

/** POST /runs/{run_id}/counterfactual  ->  {available, variants?, winner?, confidence?, rationale?} */
export function postCounterfactual(runId, { step_id, n }) {
  return _post(`/runs/${encodeURIComponent(runId)}/counterfactual`, { step_id, n });
}

/** POST /agents/run  ->  {run_id, status, steps} */
export function postAgentRun(body) {
  return _post("/agents/run", body);
}

/** GET /agents/connect-info  ->  ConnectInfo{http, mcp, sdk} */
export function getConnectInfo() {
  return _get("/agents/connect-info");
}
