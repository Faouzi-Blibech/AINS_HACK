// Dock.jsx -- Analysis dock (Debug agent / Counterfactuals / Divergence tabs)
// Matches the ANALYSIS DOCK design in "ui design/Cassette v1.dc.html" lines 372-467.
// Uses inline styles + var(--*) tokens only. No Tailwind classes.

import { useState } from "react";
import { Link } from "react-router-dom";
import {
  getTrace,
  postInject,
  postDiverge,
  postCounterfactual,
  postRecordOver,
} from "../api/client.js";
import DivergenceDiff from "../DivergenceDiff.jsx";

// Runs from these local agents can be re-run live from the fork (record-over).
const RERUNNABLE_AGENTS = new Set(["agent.ops_incident_agent"]);

// ---- Tab bar ----

const TAB_LABELS = ["Debug agent", "Counterfactuals", "Divergence"];

function TabBar({ active, onChange }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 3,
        padding: "0 14px",
        borderBottom: "1px solid var(--bd)",
        flexShrink: 0,
      }}
    >
      {TAB_LABELS.map((label) => {
        const isActive = active === label;
        return (
          <button
            key={label}
            onClick={() => onChange(label)}
            style={{
              background: "transparent",
              border: "none",
              borderBottom: isActive ? "2px solid var(--accent)" : "2px solid transparent",
              padding: "10px 12px 9px",
              font: `${isActive ? 600 : 450} 12px var(--ui)`,
              color: isActive ? "var(--fg0)" : "var(--fg2)",
              cursor: "pointer",
              transition: "color 0.12s",
              whiteSpace: "nowrap",
            }}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

// ---- Shared helpers ----

function Spinner() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      style={{ animation: "reelspin 1s linear infinite", display: "block" }}
    >
      <circle
        cx="12"
        cy="12"
        r="9"
        fill="none"
        stroke="var(--accent)"
        strokeWidth="2.5"
        strokeDasharray="28 56"
      />
    </svg>
  );
}

// ---- Debug agent tab ----

const FAIL_STATES = ["error", "failed", "timeout", "aborted"];
const OK_STATES = ["ok", "passed"];

function LegacyDebugAgentTab({ runId, selectedStepId, steps, originalStatus }) {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [injectResult, setInjectResult] = useState(null); // null | {available, injection?, rationale?, detail?}
  const [divergeResult, setDivergeResult] = useState(null); // null | {fork_run_id, final_status, side_effect_count}
  const [divergeLoading, setDivergeLoading] = useState(false);

  // Determine the step number to label the button
  const injStep =
    injectResult?.injection?.step_id ??
    selectedStepId ??
    (steps?.[0]?.step_id ?? "N");

  const handleLegacyFire = async () => {
    if (!text.trim()) return;
    setLoading(true);
    setError(null);
    setInjectResult(null);
    setDivergeResult(null);
    try {
      const result = await postInject(runId, text.trim());
      setInjectResult(result);

      // If injection is available, also call diverge
      if (result.available && result.injection) {
        const inj = result.injection;
        const target = inj.target ?? "result";
        setDivergeLoading(true);
        try {
          const dr = await postDiverge(runId, {
            step_id: inj.step_id,
            target,
            value: inj.value,
          });
          setDivergeResult(dr);
        } catch (de) {
          // Surface diverge error inline but don't overwrite injection result
          setDivergeResult({ _error: de.message });
        } finally {
          setDivergeLoading(false);
        }
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const injectionJson =
    injectResult?.available && injectResult.injection
      ? JSON.stringify(injectResult.injection, null, 2)
      : null;

  const notAvailableMsg =
    injectResult && !injectResult.available
      ? injectResult.detail ?? "Injection not available (no key configured)."
      : null;

  // Verdict: compare the original run status to the forked replay status so the
  // user gets a clear "did my fix work?" answer, not just a raw status string.
  const verdict = (() => {
    if (!divergeResult || divergeResult._error) return null;
    const fs = divergeResult.final_status;
    const origFailed = FAIL_STATES.includes(originalStatus);
    const forkOk = OK_STATES.includes(fs);
    if (origFailed && forkOk)
      return { tone: "good", text: `Fix resolves the failure — run now passes (was ${originalStatus} → ${fs}).` };
    if (origFailed && !forkOk)
      return { tone: "bad", text: `Fix does not resolve the failure — still ${fs} (was ${originalStatus}).` };
    if (!origFailed && forkOk)
      return { tone: "neutral", text: `Original run already passed; the fork also passes (${fs}). No failure to resolve here.` };
    return { tone: "bad", text: `This edit breaks a previously passing run (now ${fs}).` };
  })();

  return (
    <div style={{ display: "flex", gap: 22, height: "100%" }}>
      {/* Left column */}
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        <div style={{ font: "600 12.5px var(--ui)", color: "var(--fg0)" }}>
          Describe the fix in plain English
        </div>
        <div
          style={{
            font: "450 11px var(--ui)",
            color: "var(--fg1)",
            marginTop: 3,
            marginBottom: 11,
          }}
        >
          Cassette compiles your intent into a structurally-valid injection and forks the replay
          from that step.
        </div>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="e.g. at step 2, priority should have been high, not medium"
          style={{
            flex: 1,
            resize: "none",
            background: "var(--bg2)",
            border: "1px solid var(--bd)",
            borderRadius: 10,
            padding: "13px 14px",
            font: "450 13px var(--ui)",
            color: "var(--fg0)",
            outline: "none",
            lineHeight: 1.5,
          }}
        />
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            marginTop: 12,
          }}
        >
          <button
            onClick={handleLegacyFire}
            disabled={loading || !text.trim()}
            style={{
              background: loading || !text.trim() ? "var(--bg3)" : "var(--accent)",
              color: loading || !text.trim() ? "var(--fg2)" : "#fff",
              border: "none",
              borderRadius: 9,
              padding: "10px 16px",
              font: "600 12.5px var(--ui)",
              cursor: loading || !text.trim() ? "default" : "pointer",
              display: "flex",
              alignItems: "center",
              gap: 8,
              transition: "background 0.12s",
            }}
          >
            {loading ? (
              <Spinner />
            ) : (
              <svg width="13" height="13" viewBox="0 0 16 16">
                <path
                  d="M5 3v6a3 3 0 003 3h3M11 9l3 3-3 3"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            )}
            Fire replay from step {injStep}
          </button>
          <div style={{ font: "450 10.5px var(--mono)", color: "var(--fg2)" }}>
            deterministic · 0 live calls
          </div>
        </div>

        {/* Diverge confirmation */}
        {divergeLoading && (
          <div
            style={{
              marginTop: 10,
              font: "450 11px var(--ui)",
              color: "var(--fg2)",
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <Spinner />
            Forking replay...
          </div>
        )}
        {verdict && (
          <div
            style={{
              marginTop: 12,
              padding: "11px 14px",
              borderRadius: 10,
              border: `1px solid ${
                verdict.tone === "good"
                  ? "var(--pass)"
                  : verdict.tone === "bad"
                  ? "var(--fail)"
                  : "var(--bd2)"
              }`,
              background:
                verdict.tone === "good"
                  ? "var(--pass-dim)"
                  : verdict.tone === "bad"
                  ? "var(--fail-dim)"
                  : "var(--bg2)",
              color:
                verdict.tone === "good"
                  ? "var(--pass)"
                  : verdict.tone === "bad"
                  ? "var(--fail)"
                  : "var(--fg1)",
              font: "600 12px var(--ui)",
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            <span style={{ fontSize: 14, flex: "none" }}>
              {verdict.tone === "good" ? "✓" : verdict.tone === "bad" ? "✗" : "•"}
            </span>
            <span>{verdict.text}</span>
          </div>
        )}
        {divergeResult && !divergeResult._error && (
          <div
            style={{
              marginTop: 10,
              font: "450 11px var(--ui)",
              color: "var(--fg1)",
              display: "flex",
              gap: 10,
              flexWrap: "wrap",
            }}
          >
            <span>
              Fork run:{" "}
              <span style={{ fontFamily: "var(--mono)", fontSize: 10.5 }}>
                {divergeResult.fork_run_id}
              </span>
            </span>
            <span>
              Status:{" "}
              <span
                style={{
                  fontFamily: "var(--mono)",
                  fontSize: 10.5,
                  color: OK_STATES.includes(divergeResult.final_status)
                    ? "var(--pass)"
                    : FAIL_STATES.includes(divergeResult.final_status)
                    ? "var(--fail)"
                    : "var(--fg1)",
                }}
              >
                {divergeResult.final_status ?? "unknown"}
              </span>
            </span>
            <span>
              Side effects:{" "}
              <span style={{ fontFamily: "var(--mono)", fontSize: 10.5 }}>
                {divergeResult.side_effect_count ?? 0}
              </span>
            </span>
          </div>
        )}
        {divergeResult?._error && (
          <div style={{ marginTop: 8, font: "450 11px var(--ui)", color: "var(--fail)" }}>
            Fork error: {divergeResult._error}
          </div>
        )}
        {error && (
          <div style={{ marginTop: 8, font: "450 11px var(--ui)", color: "var(--fail)" }}>
            {error}
          </div>
        )}
      </div>

      {/* Right column */}
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 9,
          }}
        >
          <span
            style={{
              font: "600 9.5px var(--mono)",
              letterSpacing: ".1em",
              color: "var(--fg2)",
            }}
          >
            GENERATED INJECTION
          </span>
          {injectionJson && (
            <span
              style={{
                font: "600 9px var(--mono)",
                color: "var(--pass)",
                background: "var(--pass-dim)",
                border: "1px solid var(--pass)",
                borderRadius: 5,
                padding: "1px 6px",
              }}
            >
              SCHEMA VALID
            </span>
          )}
        </div>
        <pre
          style={{
            flex: 1,
            margin: 0,
            background: "var(--bg2)",
            border: "1px solid var(--bd)",
            borderRadius: 10,
            padding: "13px 14px",
            overflow: "auto",
            whiteSpace: "pre",
            font: "450 12px var(--mono)",
            lineHeight: 1.65,
            color: injectionJson
              ? "var(--fg0)"
              : notAvailableMsg
              ? "var(--warn)"
              : "var(--fg2)",
          }}
        >
          {injectionJson
            ? injectionJson
            : notAvailableMsg
            ? notAvailableMsg
            : "// Injection will appear here after firing replay."}
        </pre>
      </div>
    </div>
  );
}

function DebugAgentTab({ runId, selectedStepId, steps, originalStatus }) {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [injectResult, setInjectResult] = useState(null);
  const [draftInjection, setDraftInjection] = useState(null);
  const [divergeResult, setDivergeResult] = useState(null);
  const [forkTrace, setForkTrace] = useState(null);
  const [divergeLoading, setDivergeLoading] = useState(false);

  const stepOptions = steps ?? [];
  const hasDraftStepOption =
    draftInjection &&
    stepOptions.some((step) => String(step.step_id) === String(draftInjection.step_id));

  const normalizedDraftInjection = draftInjection
    ? {
        step_id: draftInjection.step_id === "" ? "" : Number(draftInjection.step_id),
        target: draftInjection.target,
        value: draftInjection.value,
      }
    : null;

  const injectionJson = normalizedDraftInjection
    ? JSON.stringify(normalizedDraftInjection, null, 2)
    : null;

  const canRunFork = Boolean(
    draftInjection &&
      !divergeLoading &&
      draftInjection.step_id !== "" &&
      draftInjection.target &&
      draftInjection.value !== ""
  );

  const stepOptionLabel = (step) => {
    const kind =
      step.type === "llm_call"
        ? `LLM ${step.model ?? "model"}`
        : step.type === "tool_call"
        ? `Tool ${step.tool ?? "tool"}`
        : step.type ?? "step";
    return `Step ${step.step_id} - ${kind}`;
  };

  const updateDraft = (field, value) => {
    setDraftInjection((prev) => (prev ? { ...prev, [field]: value } : prev));
    setDivergeResult(null);
    setForkTrace(null);
  };

  const handleGenerateInjection = async () => {
    if (!text.trim()) return;
    setLoading(true);
    setError(null);
    setInjectResult(null);
    setDraftInjection(null);
    setDivergeResult(null);
    setForkTrace(null);

    try {
      const result = await postInject(runId, text.trim());
      setInjectResult(result);

      if (result.available && result.injection) {
        const inj = result.injection;
        setDraftInjection({
          step_id: String(inj.step_id ?? selectedStepId ?? stepOptions?.[0]?.step_id ?? ""),
          target: inj.target ?? "result",
          value: inj.value ?? "",
        });
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleRunFork = async () => {
    if (!canRunFork) return;
    setDivergeLoading(true);
    setError(null);
    setDivergeResult(null);
    setForkTrace(null);

    try {
      const dr = await postDiverge(runId, {
        step_id: Number(draftInjection.step_id),
        target: draftInjection.target,
        value: draftInjection.value,
      });
      const fork = await getTrace(dr.fork_run_id);
      setDivergeResult(dr);
      setForkTrace(fork);
    } catch (err) {
      setDivergeResult({ _error: err.message });
    } finally {
      setDivergeLoading(false);
    }
  };

  const notAvailableMsg =
    injectResult && !injectResult.available
      ? injectResult.detail ?? "Injection not available (no key configured)."
      : null;

  const verdict = (() => {
    if (!divergeResult || divergeResult._error) return null;
    const fs = divergeResult.final_status;
    const origFailed = FAIL_STATES.includes(originalStatus);
    const forkOk = OK_STATES.includes(fs);
    if (origFailed && forkOk) {
      return { tone: "good", text: `Fix resolves the failure: run now passes (was ${originalStatus} -> ${fs}).` };
    }
    if (origFailed && !forkOk) {
      return { tone: "bad", text: `Fix does not resolve the failure: still ${fs} (was ${originalStatus}).` };
    }
    if (!origFailed && forkOk) {
      return { tone: "neutral", text: `Original run already passed; the fork also passes (${fs}).` };
    }
    return { tone: "bad", text: `This edit breaks a previously passing run (now ${fs}).` };
  })();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, minHeight: "100%" }}>
      <div style={{ display: "flex", gap: 22, minHeight: 262 }}>
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
          <div style={{ font: "600 12.5px var(--ui)", color: "var(--fg0)" }}>
            Describe the fix in plain English
          </div>
          <div
            style={{
              font: "450 11px var(--ui)",
              color: "var(--fg1)",
              marginTop: 3,
              marginBottom: 11,
            }}
          >
            Cassette compiles your intent into a structured injection for review.
          </div>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="e.g. at step 2, priority should have been high, not medium"
            style={{
              flex: 1,
              minHeight: 156,
              resize: "none",
              background: "var(--bg2)",
              border: "1px solid var(--bd)",
              borderRadius: 10,
              padding: "13px 14px",
              font: "450 13px var(--ui)",
              color: "var(--fg0)",
              outline: "none",
              lineHeight: 1.5,
            }}
          />
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              marginTop: 12,
            }}
          >
            <button
              onClick={handleGenerateInjection}
              disabled={loading || !text.trim()}
              style={{
                background: loading || !text.trim() ? "var(--bg3)" : "var(--accent)",
                color: loading || !text.trim() ? "var(--fg2)" : "#fff",
                border: "none",
                borderRadius: 9,
                padding: "10px 16px",
                font: "600 12.5px var(--ui)",
                cursor: loading || !text.trim() ? "default" : "pointer",
                display: "flex",
                alignItems: "center",
                gap: 8,
                transition: "background 0.12s",
              }}
            >
              {loading ? (
                <Spinner />
              ) : (
                <svg width="13" height="13" viewBox="0 0 16 16">
                  <path
                    d="M8 1.8l1.3 3.1 3.4.3-2.6 2.2.8 3.3L8 8.9l-2.9 1.8.8-3.3-2.6-2.2 3.4-.3z"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.4"
                    strokeLinejoin="round"
                  />
                </svg>
              )}
              Generate injection
            </button>
            <div style={{ font: "450 10.5px var(--mono)", color: "var(--fg2)" }}>
              deterministic / 0 live calls
            </div>
          </div>
          {error && (
            <div style={{ marginTop: 8, font: "450 11px var(--ui)", color: "var(--fail)" }}>
              {error}
            </div>
          )}
        </div>

        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 9,
            }}
          >
            <span
              style={{
                font: "600 9.5px var(--mono)",
                letterSpacing: ".1em",
                color: "var(--fg2)",
              }}
            >
              GENERATED INJECTION
            </span>
            {injectionJson && (
              <span
                style={{
                  font: "600 9px var(--mono)",
                  color: "var(--pass)",
                  background: "var(--pass-dim)",
                  border: "1px solid var(--pass)",
                  borderRadius: 5,
                  padding: "1px 6px",
                }}
              >
                SCHEMA VALID
              </span>
            )}
          </div>

          {draftInjection ? (
            <>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "minmax(120px, .85fr) minmax(120px, .65fr)",
                  gap: 10,
                  marginBottom: 10,
                }}
              >
                <label style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                  <span style={{ font: "600 10px var(--mono)", color: "var(--fg2)" }}>
                    STEP
                  </span>
                  <select
                    value={draftInjection.step_id}
                    onChange={(e) => updateDraft("step_id", e.target.value)}
                    style={{
                      background: "var(--bg2)",
                      border: "1px solid var(--bd)",
                      borderRadius: 9,
                      color: "var(--fg0)",
                      font: "450 12px var(--ui)",
                      padding: "9px 10px",
                      outline: "none",
                    }}
                  >
                    <option value="">Select step</option>
                    {stepOptions.map((step) => (
                      <option key={step.step_id} value={String(step.step_id)}>
                        {stepOptionLabel(step)}
                      </option>
                    ))}
                    {draftInjection.step_id && !hasDraftStepOption && (
                      <option value={draftInjection.step_id}>
                        Step {draftInjection.step_id}
                      </option>
                    )}
                  </select>
                </label>

                <label style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                  <span style={{ font: "600 10px var(--mono)", color: "var(--fg2)" }}>
                    TARGET
                  </span>
                  <select
                    value={draftInjection.target}
                    onChange={(e) => updateDraft("target", e.target.value)}
                    style={{
                      background: "var(--bg2)",
                      border: "1px solid var(--bd)",
                      borderRadius: 9,
                      color: "var(--fg0)",
                      font: "450 12px var(--ui)",
                      padding: "9px 10px",
                      outline: "none",
                    }}
                  >
                    {["prompt", "response", "args", "result"].map((target) => (
                      <option key={target} value={target}>
                        {target}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <label style={{ display: "flex", flexDirection: "column", gap: 5, flex: 1 }}>
                <span style={{ font: "600 10px var(--mono)", color: "var(--fg2)" }}>
                  VALUE
                </span>
                <textarea
                  value={draftInjection.value}
                  onChange={(e) => updateDraft("value", e.target.value)}
                  style={{
                    flex: 1,
                    minHeight: 88,
                    resize: "vertical",
                    background: "var(--bg2)",
                    border: "1px solid var(--bd)",
                    borderRadius: 10,
                    padding: "11px 12px",
                    font: "450 12px var(--mono)",
                    color: "var(--fg0)",
                    outline: "none",
                    lineHeight: 1.55,
                  }}
                />
              </label>

              <pre
                style={{
                  margin: "10px 0 0",
                  maxHeight: 112,
                  background: "var(--bg2)",
                  border: "1px solid var(--bd)",
                  borderRadius: 10,
                  padding: "11px 12px",
                  overflow: "auto",
                  whiteSpace: "pre",
                  font: "450 11px var(--mono)",
                  lineHeight: 1.55,
                  color: "var(--fg1)",
                }}
              >
                {injectionJson}
              </pre>

              {injectResult?.rationale && (
                <div
                  style={{
                    marginTop: 8,
                    font: "450 11px var(--ui)",
                    color: "var(--fg1)",
                    lineHeight: 1.45,
                  }}
                >
                  {injectResult.rationale}
                </div>
              )}

              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  marginTop: 12,
                  flexWrap: "wrap",
                }}
              >
                <button
                  onClick={handleRunFork}
                  disabled={!canRunFork}
                  style={{
                    background: canRunFork ? "var(--accent)" : "var(--bg3)",
                    color: canRunFork ? "#fff" : "var(--fg2)",
                    border: "none",
                    borderRadius: 9,
                    padding: "10px 16px",
                    font: "600 12.5px var(--ui)",
                    cursor: canRunFork ? "pointer" : "default",
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    transition: "background 0.12s",
                  }}
                >
                  {divergeLoading ? (
                    <Spinner />
                  ) : (
                    <svg width="13" height="13" viewBox="0 0 16 16">
                      <path
                        d="M5 3v6a3 3 0 003 3h3M11 9l3 3-3 3"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.6"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  )}
                  Run new forked run
                </button>
                <span style={{ font: "450 10.5px var(--mono)", color: "var(--fg2)" }}>
                  fork @ step {draftInjection.step_id || "?"}
                </span>
              </div>
            </>
          ) : (
            <pre
              style={{
                flex: 1,
                margin: 0,
                background: "var(--bg2)",
                border: "1px solid var(--bd)",
                borderRadius: 10,
                padding: "13px 14px",
                overflow: "auto",
                whiteSpace: "pre-wrap",
                font: "450 12px var(--mono)",
                lineHeight: 1.65,
                color: notAvailableMsg ? "var(--warn)" : "var(--fg2)",
              }}
            >
              {notAvailableMsg ?? "// Injection fields will appear here after generation."}
            </pre>
          )}
        </div>
      </div>

      {divergeLoading && (
        <div
          style={{
            font: "450 11px var(--ui)",
            color: "var(--fg2)",
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <Spinner />
          Forking replay...
        </div>
      )}
      {verdict && (
        <div
          style={{
            padding: "11px 14px",
            borderRadius: 10,
            border: `1px solid ${
              verdict.tone === "good"
                ? "var(--pass)"
                : verdict.tone === "bad"
                ? "var(--fail)"
                : "var(--bd2)"
            }`,
            background:
              verdict.tone === "good"
                ? "var(--pass-dim)"
                : verdict.tone === "bad"
                ? "var(--fail-dim)"
                : "var(--bg2)",
            color:
              verdict.tone === "good"
                ? "var(--pass)"
                : verdict.tone === "bad"
                ? "var(--fail)"
                : "var(--fg1)",
            font: "600 12px var(--ui)",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <span style={{ fontSize: 14, flex: "none" }}>
            {verdict.tone === "good" ? "OK" : verdict.tone === "bad" ? "!" : "i"}
          </span>
          <span>{verdict.text}</span>
        </div>
      )}
      {divergeResult && !divergeResult._error && (
        <div
          style={{
            font: "450 11px var(--ui)",
            color: "var(--fg1)",
            display: "flex",
            gap: 10,
            flexWrap: "wrap",
          }}
        >
          <span>
            Fork run:{" "}
            <span style={{ fontFamily: "var(--mono)", fontSize: 10.5 }}>
              {divergeResult.fork_run_id}
            </span>
          </span>
          <span>
            Status:{" "}
            <span
              style={{
                fontFamily: "var(--mono)",
                fontSize: 10.5,
                color: OK_STATES.includes(divergeResult.final_status)
                  ? "var(--pass)"
                  : FAIL_STATES.includes(divergeResult.final_status)
                  ? "var(--fail)"
                  : "var(--fg1)",
              }}
            >
              {divergeResult.final_status ?? "unknown"}
            </span>
          </span>
          <span>
            Side effects:{" "}
            <span style={{ fontFamily: "var(--mono)", fontSize: 10.5 }}>
              {divergeResult.side_effect_count ?? 0}
            </span>
          </span>
        </div>
      )}
      {divergeResult?._error && (
        <div style={{ font: "450 11px var(--ui)", color: "var(--fail)" }}>
          Fork error: {divergeResult._error}
        </div>
      )}
      {divergeResult && forkTrace && (
        <DivergenceDiff
          originalTrace={{ run_id: runId, steps }}
          forkTrace={forkTrace}
          forkStepId={divergeResult.diff?.fork_step_id}
          editedFields={divergeResult.diff?.edited_fields ?? []}
          finalStatus={divergeResult.final_status}
          sideEffectCount={divergeResult.side_effect_count}
        />
      )}
    </div>
  );
}

// ---- Counterfactuals tab ----

function CounterfactualsTab({ runId, selectedStepId, blame }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null); // null | {available, variants?, winner?, rationale?}

  const rootStepId = selectedStepId ?? blame?.root_cause_step_id ?? null;

  const handleRun = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await postCounterfactual(runId, { step_id: rootStepId, n: 4 });
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const variants = result?.available ? (result.variants ?? []) : [];
  const winner = result?.winner;
  const rationale = result?.rationale;

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 13,
        }}
      >
        <div>
          <div style={{ font: "600 12.5px var(--ui)", color: "var(--fg0)" }}>
            Counterfactual ranking
          </div>
          <div style={{ font: "450 11px var(--ui)", color: "var(--fg1)", marginTop: 2 }}>
            {rootStepId != null
              ? `Exploring alternatives from step ${rootStepId}`
              : "Select a step to explore alternatives"}
          </div>
        </div>
        {!result && !loading && (
          <button
            onClick={handleRun}
            disabled={loading}
            style={{
              background: "var(--accent)",
              color: "#fff",
              border: "none",
              borderRadius: 9,
              padding: "9px 15px",
              font: "600 12px var(--ui)",
              cursor: "pointer",
            }}
          >
            Replay 4 variants in parallel
          </button>
        )}
        {loading && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--fg2)", font: "450 12px var(--ui)" }}>
            <Spinner />
            Running variants...
          </div>
        )}
      </div>

      {error && (
        <div
          style={{
            padding: "10px 14px",
            background: "var(--fail-dim)",
            border: "1px solid var(--fail)",
            borderRadius: 10,
            font: "450 12px var(--ui)",
            color: "var(--fail)",
            marginBottom: 12,
          }}
        >
          {error}
        </div>
      )}

      {result && !result.available && (
        <div
          style={{
            padding: "10px 14px",
            background: "var(--warn-dim)",
            border: "1px solid var(--warn)",
            borderRadius: 10,
            font: "450 12px var(--ui)",
            color: "var(--warn)",
          }}
        >
          {result.detail ?? "Counterfactual analysis not available."}
        </div>
      )}

      {variants.length > 0 && (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(4, 1fr)",
              gap: 12,
            }}
          >
            {variants.map((v) => {
              const isWinner = v.variant_id === winner;
              const resolved = v.resolved ?? false;
              const score = typeof v.score === "number" ? v.score : 0;
              const scoreColor = resolved ? "var(--pass)" : "var(--warn)";

              return (
                <div
                  key={v.variant_id}
                  style={{
                    background: isWinner ? "var(--pass-dim)" : "var(--bg2)",
                    border: `1px solid ${isWinner ? "var(--pass)" : "var(--bd)"}`,
                    borderRadius: 10,
                    padding: "12px 13px",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                    }}
                  >
                    <span
                      style={{
                        font: "600 10px var(--mono)",
                        letterSpacing: ".06em",
                        color: "var(--fg2)",
                      }}
                    >
                      {v.variant_id}
                    </span>
                    {isWinner && (
                      <span
                        style={{
                          font: "600 8.5px var(--mono)",
                          color: "#fff",
                          background: "var(--pass)",
                          borderRadius: 5,
                          padding: "2px 6px",
                          letterSpacing: ".06em",
                        }}
                      >
                        WINNER
                      </span>
                    )}
                  </div>

                  <div
                    style={{
                      font: "550 12px var(--ui)",
                      color: "var(--fg0)",
                      margin: "8px 0 10px",
                      lineHeight: 1.4,
                      minHeight: 50,
                      overflow: "hidden",
                      display: "-webkit-box",
                      WebkitLineClamp: 3,
                      WebkitBoxOrient: "vertical",
                    }}
                  >
                    {v.prompt ?? "(no prompt)"}
                  </div>

                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: 6,
                      borderTop: "1px solid var(--bd)",
                      paddingTop: 9,
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <span style={{ font: "450 10.5px var(--ui)", color: "var(--fg2)" }}>
                        Completed
                      </span>
                      <span
                        style={{
                          font: "550 10.5px var(--mono)",
                          color: resolved ? "var(--pass)" : "var(--fail)",
                        }}
                      >
                        {resolved ? "yes" : "no"}
                      </span>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <span style={{ font: "450 10.5px var(--ui)", color: "var(--fg2)" }}>
                        Steps changed
                      </span>
                      <span style={{ font: "550 10.5px var(--mono)", color: "var(--fg1)" }}>
                        {v.steps_changed ?? 0}
                      </span>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <span style={{ font: "450 10.5px var(--ui)", color: "var(--fg2)" }}>
                        Side effects
                      </span>
                      <span style={{ font: "550 10.5px var(--mono)", color: "var(--fg1)" }}>
                        {v.side_effect_count ?? 0}
                      </span>
                    </div>
                  </div>

                  <div style={{ marginTop: 10 }}>
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        marginBottom: 4,
                      }}
                    >
                      <span
                        style={{
                          font: "600 8.5px var(--mono)",
                          letterSpacing: ".08em",
                          color: "var(--fg2)",
                        }}
                      >
                        SCORE
                      </span>
                      <span
                        style={{ font: "600 11px var(--mono)", color: scoreColor }}
                      >
                        {score.toFixed(2)}
                      </span>
                    </div>
                    <div
                      style={{
                        height: 5,
                        borderRadius: 4,
                        background: "var(--bg3)",
                        overflow: "hidden",
                      }}
                    >
                      <div
                        style={{
                          height: "100%",
                          width: `${Math.min(100, score * 100)}%`,
                          background: scoreColor,
                          borderRadius: 4,
                          transition: "width 0.4s",
                        }}
                      />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {rationale && (
            <div
              style={{
                marginTop: 13,
                padding: "11px 14px",
                border: "1px solid var(--pass)",
                background: "var(--pass-dim)",
                borderRadius: 10,
                font: "450 12px var(--ui)",
                color: "var(--fg0)",
              }}
            >
              {rationale}
            </div>
          )}
        </>
      )}

      {result?.available && variants.length === 0 && (
        <div style={{ font: "450 12px var(--ui)", color: "var(--fg2)" }}>
          No variants returned.
        </div>
      )}
    </div>
  );
}

// ---- Divergence tab ----

function DivergenceTab({ runId, selectedStepId, trace, steps }) {
  // Re-runnable runs (recorded by a local Cassette agent) do a LIVE record-over:
  // the agent re-runs from its decision and can take a genuinely different path.
  // Others fall back to a faithful-replay fork.
  const rerunnable = RERUNNABLE_AGENTS.has(trace?.agent);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [whatIf, setWhatIf] = useState(rerunnable ? "SEV-4" : "high");
  const [forkTrace, setForkTrace] = useState(null);

  // Determine step to fork at and pick target type
  const forkStepId = selectedStepId ?? steps?.[0]?.step_id ?? null;
  const selectedStep = steps?.find((s) => s.step_id === forkStepId);
  const target = selectedStep?.type === "tool_call" ? "result" : "response";

  const handleFork = async () => {
    if (!rerunnable && forkStepId == null) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setForkTrace(null);
    try {
      const data = rerunnable
        ? await postRecordOver(runId, { value: whatIf, step_id: forkStepId })
        : await postDiverge(runId, { step_id: forkStepId, target, value: whatIf });
      setResult(data);
      const fork = await getTrace(data.fork_run_id);
      setForkTrace(fork);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const diff = result?.diff;
  const originalSteps = diff?.original_steps ?? [];
  const forkedSteps = diff?.forked_steps ?? [];
  const editedFields = diff?.edited_fields ?? [];
  const forkStepLabel = diff?.fork_step_id ?? forkStepId ?? "?";
  const editedLabel = editedFields.length > 0 ? editedFields.join(", ") : target;

  // Build diff rows: pair original and forked steps side by side
  const maxRows = Math.max(originalSteps.length, forkedSteps.length);
  const diffRows = Array.from({ length: maxRows }, (_, i) => ({
    n: i + 1,
    orig: originalSteps[i],
    fork: forkedSteps[i],
  }));

  const cellBase = {
    padding: "8px 12px",
    font: "450 11.5px var(--ui)",
    color: "var(--fg1)",
    borderLeft: "1px solid var(--bd)",
    borderBottom: "1px solid var(--bd)",
  };

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          marginBottom: 12,
        }}
      >
        <div style={{ font: "600 12.5px var(--ui)", color: "var(--fg0)" }}>
          Trajectory diff
        </div>
        <span style={{ font: "450 11px var(--mono)", color: "var(--fg2)" }}>
          original {runId}
        </span>
        <svg
          width="16"
          height="12"
          viewBox="0 0 16 12"
          style={{ color: "var(--fg2)", flexShrink: 0 }}
        >
          <path
            d="M1 6h12M9 2l4 4-4 4"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <span style={{ font: "450 11px var(--mono)", color: "var(--accent)" }}>
          {rerunnable
            ? (result ? `record-over · ${editedLabel}` : "record-over · re-runs the agent")
            : (result ? `fork @ step ${forkStepLabel} · ${editedLabel}` : `fork @ step ${forkStepId ?? "?"} · ${target}`)}
        </span>

        {!result && (
          <input
            value={whatIf}
            onChange={(e) => setWhatIf(e.target.value)}
            placeholder={rerunnable ? "new severity, e.g. SEV-4" : "what-if value"}
            title={rerunnable ? "Re-run the agent with this decision value" : "The alternative value to inject at this step"}
            style={{
              marginLeft: "auto",
              width: 170,
              background: "var(--bg2)",
              border: "1px solid var(--bd)",
              borderRadius: 9,
              padding: "8px 11px",
              font: "450 12px var(--mono)",
              color: "var(--fg0)",
              outline: "none",
            }}
          />
        )}
        {!result && (
          <button
            onClick={handleFork}
            disabled={loading || (!rerunnable && forkStepId == null)}
            style={{
              marginLeft: 8,
              background:
                loading || (!rerunnable && forkStepId == null) ? "var(--bg3)" : "var(--accent)",
              color: loading || (!rerunnable && forkStepId == null) ? "var(--fg2)" : "#fff",
              border: "none",
              borderRadius: 9,
              padding: "8px 14px",
              font: "600 12px var(--ui)",
              cursor: loading || (!rerunnable && forkStepId == null) ? "default" : "pointer",
              display: "flex",
              alignItems: "center",
              gap: 6,
              transition: "background 0.12s",
            }}
          >
            {loading ? <Spinner /> : null}
            {rerunnable ? `Re-run as ${whatIf}` : `Fork at step ${forkStepId ?? "?"}`}
          </button>
        )}
      </div>

      {error && (
        <div
          style={{
            padding: "10px 14px",
            background: "var(--fail-dim)",
            border: "1px solid var(--fail)",
            borderRadius: 10,
            font: "450 12px var(--ui)",
            color: "var(--fail)",
            marginBottom: 12,
          }}
        >
          {error}
        </div>
      )}

      {!result && !loading && !error && (
        <div
          style={{
            font: "450 12px var(--ui)",
            color: "var(--fg2)",
            padding: "20px 0",
          }}
        >
          Click "Fork at step {forkStepId ?? "?"}" to generate the trajectory diff.
        </div>
      )}

      {loading && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            font: "450 12px var(--ui)",
            color: "var(--fg2)",
            padding: "20px 0",
          }}
        >
          <Spinner />
          Forking trajectory...
        </div>
      )}

      {result && (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "24px 1fr 1fr",
              gap: 0,
              border: "1px solid var(--bd)",
              borderRadius: 10,
              overflow: "hidden",
            }}
          >
            {/* Header row */}
            <div
              style={{
                background: "var(--bg2)",
                borderBottom: "1px solid var(--bd)",
              }}
            />
            <div
              style={{
                background: "var(--bg2)",
                borderBottom: "1px solid var(--bd)",
                borderLeft: "1px solid var(--bd)",
                padding: "8px 12px",
                font: "600 9.5px var(--mono)",
                letterSpacing: ".08em",
                color: "var(--fg2)",
              }}
            >
              ORIGINAL · {(result.diff?.original_steps?.length > 0
                ? "ORIGINAL"
                : trace?.final_status ?? "ORIGINAL"
              ).toUpperCase()}
            </div>
            <div
              style={{
                background: "var(--bg2)",
                borderBottom: "1px solid var(--bd)",
                borderLeft: "1px solid var(--bd)",
                padding: "8px 12px",
                font: "600 9.5px var(--mono)",
                letterSpacing: ".08em",
                color: "var(--accent)",
              }}
            >
              FORKED · {(result.final_status ?? "FORKED").toUpperCase()}
            </div>

            {/* Data rows */}
            {diffRows.map((row, i) => (
              <>
                <div
                  key={`n-${i}`}
                  style={{
                    background: "var(--bg2)",
                    borderBottom: i < diffRows.length - 1 ? "1px solid var(--bd)" : "none",
                    padding: "7px 6px",
                    font: "600 10px var(--mono)",
                    color: "var(--fg2)",
                    textAlign: "center",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  {row.n}
                </div>
                <div
                  key={`orig-${i}`}
                  style={{
                    ...cellBase,
                    borderBottom: i < diffRows.length - 1 ? "1px solid var(--bd)" : "none",
                  }}
                >
                  {row.orig != null ? (
                    <>
                      <span style={{ fontWeight: 600 }}>
                        {typeof row.orig === "object"
                          ? (row.orig.type ?? row.orig.tool ?? "step")
                          : String(row.orig)}
                      </span>
                      {typeof row.orig === "object" && row.orig.tool_name && (
                        <span
                          style={{
                            fontFamily: "var(--mono)",
                            fontSize: 10.5,
                            color: "var(--fg2)",
                            marginLeft: 7,
                          }}
                        >
                          {row.orig.tool_name}
                        </span>
                      )}
                    </>
                  ) : (
                    <span style={{ color: "var(--fg2)", fontStyle: "italic" }}>-</span>
                  )}
                </div>
                <div
                  key={`fork-${i}`}
                  style={{
                    ...cellBase,
                    borderBottom: i < diffRows.length - 1 ? "1px solid var(--bd)" : "none",
                    color:
                      row.fork != null && row.orig != null
                        ? JSON.stringify(row.fork) !== JSON.stringify(row.orig)
                          ? "var(--pass)"
                          : "var(--fg1)"
                        : "var(--fg2)",
                  }}
                >
                  {row.fork != null ? (
                    <>
                      <span style={{ fontWeight: 600 }}>
                        {typeof row.fork === "object"
                          ? (row.fork.type ?? row.fork.tool ?? "step")
                          : String(row.fork)}
                      </span>
                      {typeof row.fork === "object" && row.fork.tool_name && (
                        <span
                          style={{
                            fontFamily: "var(--mono)",
                            fontSize: 10.5,
                            color: "var(--fg2)",
                            marginLeft: 7,
                          }}
                        >
                          {row.fork.tool_name}
                        </span>
                      )}
                    </>
                  ) : (
                    <span style={{ color: "var(--fg2)", fontStyle: "italic" }}>-</span>
                  )}
                </div>
              </>
            ))}

            {/* No rows fallback */}
            {diffRows.length === 0 && (
              <>
                <div
                  style={{
                    background: "var(--bg2)",
                    gridColumn: "1 / -1",
                    padding: "12px",
                    font: "450 11.5px var(--ui)",
                    color: "var(--fg2)",
                    borderTop: "1px solid var(--bd)",
                  }}
                >
                  No step diff available.
                </div>
              </>
            )}
          </div>

          {editedFields.length > 0 && (
            <div
              style={{
                marginTop: 10,
                font: "450 11px var(--mono)",
                color: "var(--fg2)",
              }}
            >
              Edited fields: {editedFields.join(", ")}
            </div>
          )}
          {result.fork_run_id && (
            <div style={{ marginTop: 8, font: "450 11px var(--ui)", color: "var(--fg1)" }}>
              Forked run{" "}
              <Link
                to={`/runs/${result.fork_run_id}`}
                style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--accent)" }}
              >
                {result.fork_run_id}
              </Link>{" "}
              · outcome{" "}
              <span style={{ fontFamily: "var(--mono)", fontSize: 10.5 }}>
                {result.final_status ?? "?"}
              </span>
              {rerunnable && " · the agent re-ran and took this path"}
            </div>
          )}
          <div
            style={{
              marginTop: 6,
              font: "450 11px var(--mono)",
              color: "var(--fg2)",
            }}
          >
            side effects: {result.side_effect_count ?? 0}
          </div>
        </>
      )}
    </div>
  );
}

function DivergenceTab({ runId, selectedStepId, trace, steps }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [forkTrace, setForkTrace] = useState(null);
  const [whatIf, setWhatIf] = useState("high");

  const forkStepId = selectedStepId ?? steps?.[0]?.step_id ?? null;
  const selectedStep = steps?.find((step) => step.step_id === forkStepId);
  const target = selectedStep?.type === "tool_call" ? "result" : "response";

  const handleFork = async () => {
    if (forkStepId == null) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setForkTrace(null);

    try {
      const data = await postDiverge(runId, {
        step_id: forkStepId,
        target,
        value: whatIf,
      });
      const fork = await getTrace(data.fork_run_id);
      setResult(data);
      setForkTrace(fork);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const editedFields = result?.diff?.edited_fields ?? [];
  const forkStepLabel = result?.diff?.fork_step_id ?? forkStepId ?? "?";
  const editedLabel = editedFields.length > 0 ? editedFields.join(", ") : target;

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          marginBottom: 12,
          flexWrap: "wrap",
        }}
      >
        <div style={{ font: "600 12.5px var(--ui)", color: "var(--fg0)" }}>
          Manual what-if
        </div>
        <span style={{ font: "450 11px var(--mono)", color: "var(--fg2)" }}>
          original {runId}
        </span>
        <span style={{ font: "450 11px var(--mono)", color: "var(--accent)" }}>
          {result
            ? `fork @ step ${forkStepLabel} / ${editedLabel}`
            : `fork @ step ${forkStepId ?? "?"} / ${target}`}
        </span>

        {!result && (
          <input
            value={whatIf}
            onChange={(e) => setWhatIf(e.target.value)}
            placeholder="what-if value"
            title="The alternative value to inject at this step"
            style={{
              marginLeft: "auto",
              width: 170,
              background: "var(--bg2)",
              border: "1px solid var(--bd)",
              borderRadius: 9,
              padding: "8px 11px",
              font: "450 12px var(--mono)",
              color: "var(--fg0)",
              outline: "none",
            }}
          />
        )}
        {!result && (
          <button
            onClick={handleFork}
            disabled={loading || forkStepId == null}
            style={{
              marginLeft: 8,
              background:
                loading || forkStepId == null ? "var(--bg3)" : "var(--accent)",
              color: loading || forkStepId == null ? "var(--fg2)" : "#fff",
              border: "none",
              borderRadius: 9,
              padding: "8px 14px",
              font: "600 12px var(--ui)",
              cursor: loading || forkStepId == null ? "default" : "pointer",
              display: "flex",
              alignItems: "center",
              gap: 6,
              transition: "background 0.12s",
            }}
          >
            {loading ? <Spinner /> : null}
            Fork at step {forkStepId ?? "?"}
          </button>
        )}
      </div>

      {error && (
        <div
          style={{
            padding: "10px 14px",
            background: "var(--fail-dim)",
            border: "1px solid var(--fail)",
            borderRadius: 10,
            font: "450 12px var(--ui)",
            color: "var(--fail)",
            marginBottom: 12,
          }}
        >
          {error}
        </div>
      )}

      {!result && !loading && !error && (
        <div
          style={{
            font: "450 12px var(--ui)",
            color: "var(--fg2)",
            padding: "20px 0",
          }}
        >
          Click "Fork at step {forkStepId ?? "?"}" to generate the trajectory diff.
        </div>
      )}

      {loading && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            font: "450 12px var(--ui)",
            color: "var(--fg2)",
            padding: "20px 0",
          }}
        >
          <Spinner />
          Forking trajectory...
        </div>
      )}

      {result && forkTrace && (
        <DivergenceDiff
          originalTrace={trace}
          forkTrace={forkTrace}
          forkStepId={result.diff?.fork_step_id}
          editedFields={result.diff?.edited_fields ?? []}
          finalStatus={result.final_status}
          sideEffectCount={result.side_effect_count}
        />
      )}
    </div>
  );
}

// ---- Dock (main export) ----

export default function Dock({ trace, blame, selectedStepId, activeTab: activeTabProp, onTabChange }) {
  // Controlled when a parent passes activeTab/onTabChange (e.g. the OVER button
  // focuses the Divergence tab); otherwise self-managed.
  const [internalTab, setInternalTab] = useState("Debug agent");
  const activeTab = activeTabProp ?? internalTab;
  const setActiveTab = onTabChange ?? setInternalTab;

  const runId = trace?.run_id;
  const steps = trace?.steps ?? [];

  if (!runId) return null;

  return (
    <div
      style={{
        flexShrink: 0,
        borderTop: "1px solid var(--bd)",
        background: "var(--bg1)",
        minHeight: 252,
        display: "flex",
        flexDirection: "column",
      }}
    >
      <TabBar active={activeTab} onChange={setActiveTab} />
      <div
        style={{
          flex: 1,
          overflow: "auto",
          padding: "16px 20px",
        }}
      >
        {activeTab === "Debug agent" && (
          <DebugAgentTab
            runId={runId}
            selectedStepId={selectedStepId}
            steps={steps}
            originalStatus={trace?.status}
          />
        )}
        {activeTab === "Counterfactuals" && (
          <CounterfactualsTab
            runId={runId}
            selectedStepId={selectedStepId}
            blame={blame}
          />
        )}
        {activeTab === "Divergence" && (
          <DivergenceTab
            runId={runId}
            selectedStepId={selectedStepId}
            trace={trace}
            steps={steps}
          />
        )}
      </div>
    </div>
  );
}
