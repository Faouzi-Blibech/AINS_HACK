// RunInspector v2 -- the hero trace view, wired to the live FastAPI backend.
// Layout: transport bar > side-effects banner > tape strip > memory banner > root-cause panel > graph+inspector

import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getTrace, getBlame, getLibrary, getStep } from "../api/client.js";
import { getMetrics } from "../api/client.js";
import TapeStrip from "../components/TapeStrip.jsx";
import MemoryBanner from "../components/MemoryBanner.jsx";
import RootCausePanel from "../components/RootCausePanel.jsx";
import SideEffectsBanner from "../components/SideEffectsBanner.jsx";
import StepInspector from "../StepInspector.jsx";

// Transport controls: REC / PLAY / OVER (visual only)
function TransportControls({ isPlaying, onPlay }) {
  const [isRec, setIsRec] = useState(false);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 7,
        background: "var(--bg2)",
        border: "1px solid var(--bd)",
        borderRadius: 13,
        padding: 6,
      }}
    >
      {/* REC */}
      <button
        onClick={() => setIsRec((v) => !v)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          padding: "7px 12px",
          borderRadius: 9,
          border: "none",
          background: isRec ? "var(--fail-dim)" : "transparent",
          color: isRec ? "var(--rec)" : "var(--fg2)",
          font: "600 11px var(--mono)",
          letterSpacing: ".05em",
          cursor: "pointer",
          transition: "background 0.12s, color 0.12s",
        }}
      >
        <span
          style={{
            width: 7,
            height: 7,
            borderRadius: "50%",
            background: isRec ? "var(--rec)" : "var(--fg2)",
            display: "block",
            animation: isRec ? "recpulse 1s ease-in-out infinite" : "none",
            flex: "none",
          }}
        />
        REC
      </button>

      {/* PLAY */}
      <button
        onClick={onPlay}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 5,
          padding: "7px 12px",
          borderRadius: 9,
          border: "none",
          background: isPlaying ? "var(--pass-dim)" : "transparent",
          color: isPlaying ? "var(--pass)" : "var(--fg1)",
          font: "600 11px var(--mono)",
          letterSpacing: ".05em",
          cursor: "pointer",
          transition: "background 0.12s, color 0.12s",
        }}
      >
        <svg width="11" height="11" viewBox="0 0 12 12" style={{ marginRight: 2 }}>
          <path d="M3 2l7 4-7 4z" fill="currentColor" />
        </svg>
        {isPlaying ? "STOP" : "PLAY"}
      </button>

      {/* OVER */}
      <button
        style={{
          display: "flex",
          alignItems: "center",
          gap: 5,
          padding: "7px 12px",
          borderRadius: 9,
          border: "none",
          background: "transparent",
          color: "var(--fg2)",
          font: "600 11px var(--mono)",
          letterSpacing: ".05em",
          cursor: "pointer",
          transition: "background 0.12s, color 0.12s",
        }}
        onMouseEnter={(e) => { e.currentTarget.style.background = "var(--hover)"; e.currentTarget.style.color = "var(--fg0)"; }}
        onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--fg2)"; }}
      >
        <svg width="13" height="13" viewBox="0 0 16 16" style={{ marginRight: 2 }}>
          <path d="M5 3v6a3 3 0 003 3h3M11 9l3 3-3 3" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        OVER
      </button>
    </div>
  );
}

export default function RunInspector() {
  const { runId } = useParams();
  const [trace, setTrace] = useState(null);
  const [blame, setBlame] = useState(null);
  const [library, setLibrary] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [selectedStepId, setSelectedStepId] = useState(null);
  const [resolvedStep, setResolvedStep] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const rootCauseRef = useRef(null);

  // Resolve the effective run id -- "latest" maps to first available or fixture
  const effectiveRunId = runId === "latest" ? "run-fixture-001" : runId;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setTrace(null);
    setBlame(null);
    setLibrary(null);
    setResolvedStep(null);

    Promise.all([
      getTrace(effectiveRunId),
      getBlame(effectiveRunId).catch(() => null),
      getLibrary().catch(() => null),
      getMetrics().catch(() => null),
    ])
      .then(([traceData, blameData, libraryData, metricsData]) => {
        if (cancelled) return;
        setTrace(traceData);
        setBlame(blameData);
        setLibrary(libraryData);
        setMetrics(metricsData);

        // Default selection: blame root_cause_step_id, else step 1
        const defaultStep =
          blameData?.root_cause_step_id ??
          traceData?.steps?.[0]?.step_id ??
          null;
        setSelectedStepId(defaultStep);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [effectiveRunId]);

  // Fetch resolved step content whenever selected step changes
  useEffect(() => {
    if (!effectiveRunId || selectedStepId == null) return;
    let cancelled = false;
    setResolvedStep(null);
    getStep(effectiveRunId, selectedStepId)
      .then((data) => { if (!cancelled) setResolvedStep(data); })
      .catch(() => { /* silently fall back to null */ });
    return () => { cancelled = true; };
  }, [effectiveRunId, selectedStepId]);

  // Playback: step through steps on interval
  const playIntervalRef = useRef(null);
  const handlePlayToggle = useCallback(() => {
    if (isPlaying) {
      clearInterval(playIntervalRef.current);
      setIsPlaying(false);
    } else if (trace?.steps?.length) {
      setIsPlaying(true);
      let idx = trace.steps.findIndex((s) => s.step_id === selectedStepId);
      if (idx < 0) idx = 0;
      playIntervalRef.current = setInterval(() => {
        idx = (idx + 1) % trace.steps.length;
        setSelectedStepId(trace.steps[idx].step_id);
        if (idx === trace.steps.length - 1) {
          clearInterval(playIntervalRef.current);
          setIsPlaying(false);
        }
      }, 900);
    }
  }, [isPlaying, trace, selectedStepId]);

  useEffect(() => {
    return () => clearInterval(playIntervalRef.current);
  }, []);

  const scrollToRootCause = () => {
    rootCauseRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  // Memory match: only a real match -- library entry whose blame_step equals blame.root_cause_step_id.
  // Returns null when no match exists so the badge and banner never appear for unmatched runs.
  const memoryEntry = (() => {
    if (!library?.entries?.length) return null;
    const rootStep = blame?.root_cause_step_id;
    if (rootStep == null) return null;
    const match = library.entries.find((e) => e.blame_step === rootStep);
    if (!match) return null;
    return { entry: match, idx: library.entries.indexOf(match) };
  })();

  const memoryLabel = memoryEntry
    ? memoryEntry.entry.id ?? "FM-" + String(memoryEntry.idx + 1).padStart(3, "0")
    : null;

  if (loading) {
    return (
      <div
        style={{
          flex: 1,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          font: "450 13px var(--ui)",
          color: "var(--fg2)",
        }}
      >
        <svg width="22" height="22" viewBox="0 0 24 24" style={{ marginRight: 10, animation: "reelspin 1s linear infinite" }}>
          <circle cx="12" cy="12" r="9" fill="none" stroke="var(--accent)" strokeWidth="2" strokeDasharray="28 56" />
        </svg>
        Loading trace...
      </div>
    );
  }

  if (error) {
    return (
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 10,
          font: "450 13px var(--ui)",
          color: "var(--fail)",
        }}
      >
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 2l10 18H2z" />
          <path d="M12 8v5" />
          <circle cx="12" cy="16.5" r="1" fill="currentColor" />
        </svg>
        <div>Failed to load trace: {error}</div>
        <div style={{ font: "450 11px var(--mono)", color: "var(--fg2)" }}>
          Make sure the backend is running at {import.meta.env.VITE_API_URL ?? "http://localhost:8000"}
        </div>
        <Link
          to="/"
          style={{
            marginTop: 6,
            font: "500 12px var(--ui)",
            color: "var(--accent)",
            textDecoration: "none",
          }}
        >
          Back to runs
        </Link>
      </div>
    );
  }

  if (!trace) {
    return (
      <div
        style={{
          flex: 1,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          font: "450 13px var(--ui)",
          color: "var(--fg2)",
        }}
      >
        No trace data.
      </div>
    );
  }

  const agentLabel = trace.agent ?? "agent";
  const runSummary = "Checkout 500 -> wrong team assignment";

  return (
    <div
      style={{
        flex: 1,
        minHeight: 0,
        overflowY: "auto",
        overflowX: "hidden",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* ===== TRANSPORT BAR ===== */}
      <div
        style={{
          position: "sticky",
          top: 0,
          zIndex: 20,
          padding: "12px 24px",
          borderBottom: "1px solid var(--bd)",
          background: "var(--bg1)",
          display: "flex",
          alignItems: "center",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        {/* Back button */}
        <Link
          to="/"
          style={{
            width: 36,
            height: 36,
            background: "var(--bg2)",
            border: "1px solid var(--bd)",
            borderRadius: 10,
            display: "grid",
            placeItems: "center",
            cursor: "pointer",
            color: "var(--fg1)",
            flex: "none",
            textDecoration: "none",
            transition: "background 0.12s",
          }}
          title="Back to runs"
        >
          <svg width="16" height="16" viewBox="0 0 16 16">
            <path d="M10 3L5 8l5 5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </Link>

        {/* Run identity */}
        <div style={{ flex: "none" }}>
          <div
            style={{
              font: "600 15px var(--ui)",
              color: "var(--fg0)",
              display: "flex",
              alignItems: "center",
              gap: 10,
            }}
          >
            <span style={{ fontFamily: "var(--mono)", fontSize: 13 }}>{trace.run_id}</span>
            <span
              style={{
                font: "500 10.5px var(--mono)",
                color: "var(--accent2)",
                background: "var(--accent-dim)",
                border: "1px solid var(--accent-bd)",
                borderRadius: 6,
                padding: "2px 8px",
              }}
            >
              {agentLabel}
            </span>
          </div>
          <div style={{ font: "450 11px var(--ui)", color: "var(--fg1)", marginTop: 3 }}>
            {runSummary}
          </div>
        </div>

        {/* Transport controls */}
        <div style={{ marginLeft: "auto" }}>
          <TransportControls isPlaying={isPlaying} onPlay={handlePlayToggle} />
        </div>

        {/* Root-cause pill */}
        {blame?.root_cause_step_id != null && (
          <button
            onClick={scrollToRootCause}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "8px 14px",
              borderRadius: 10,
              border: "1px solid var(--root)",
              background: "var(--fail-dim)",
              color: "var(--root)",
              font: "600 11px var(--mono)",
              letterSpacing: ".04em",
              cursor: "pointer",
              transition: "background 0.12s",
            }}
          >
            <svg width="13" height="13" viewBox="0 0 16 16">
              <path d="M8 1.5l6 11H2z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
              <path d="M8 6v3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              <circle cx="8" cy="11" r=".9" fill="currentColor" />
            </svg>
            Root-cause
          </button>
        )}

        {/* Preventive-warning badge -- shown when a failure-memory match exists */}
        {memoryEntry && (
          <button
            onClick={() => {
              // Scroll to the MemoryBanner (same pattern as scrollToRootCause)
              rootCauseRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
            }}
            title="A preventive warning was injected because this run matched a known failure pattern"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "8px 14px",
              borderRadius: 10,
              border: "1px solid var(--warn)",
              background: "var(--warn-dim)",
              color: "var(--warn)",
              font: "700 10px var(--mono)",
              letterSpacing: ".06em",
              cursor: "pointer",
              transition: "background 0.12s",
              whiteSpace: "nowrap",
            }}
          >
            {/* Shield icon */}
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
              <path d="M8 1.5L2 4v4c0 3.3 2.5 6.2 6 7 3.5-.8 6-3.7 6-7V4z" />
              <path d="M5.5 8l2 2 3-3" />
            </svg>
            PREVENTIVE WARNING INJECTED
          </button>
        )}
      </div>

      {/* ===== SIDE-EFFECTS-CONTAINED BANNER ===== */}
      <SideEffectsBanner />

      {/* ===== TAPE STEP-STRIP ===== */}
      <TapeStrip
        steps={trace.steps}
        selectedStepId={selectedStepId}
        onSelectStep={setSelectedStepId}
        durationMs={trace.duration_ms}
      />

      {/* ===== FAILURE-MEMORY BANNER ===== */}
      {memoryEntry && (
        <MemoryBanner entry={memoryEntry.entry} label={memoryLabel} />
      )}

      {/* ===== ROOT-CAUSE PANEL ===== */}
      <div ref={rootCauseRef}>
        <RootCausePanel blame={blame} metrics={metrics} />
      </div>

      {/* ===== GRAPH + STEP INSPECTOR ROW ===== */}
      <div
        style={{
          display: "flex",
          overflow: "hidden",
          marginTop: 14,
          minHeight: 560,
          borderTop: "1px solid var(--bd)",
        }}
      >
        {/* Left: trace info / step list (replaces React Flow DAG) */}
        <div
          style={{
            flex: 1,
            minWidth: 0,
            display: "flex",
            flexDirection: "column",
            background: "var(--bg0)",
            backgroundImage: "radial-gradient(var(--bd) .9px, transparent .9px)",
            backgroundSize: "24px 24px",
            overflow: "auto",
            padding: "24px 28px",
          }}
        >
          {/* Section label */}
          <div
            style={{
              font: "600 9.5px var(--mono)",
              letterSpacing: ".14em",
              color: "var(--fg2)",
              marginBottom: 16,
            }}
          >
            EXECUTION STEPS
          </div>

          {/* Step cards */}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {trace.steps.map((step) => {
              const isSelected = step.step_id === selectedStepId;
              const isError = step.status === "error";
              const isSideEffect = step.side_effecting;
              const blameEntry = blame?.steps?.find((b) => b.step_id === step.step_id);
              const isRootCause = blame?.root_cause_step_id === step.step_id;
              const blameScore = blameEntry?.blame_score ?? 0;

              return (
                <div
                  key={step.step_id}
                  onClick={() => setSelectedStepId(step.step_id)}
                  style={{
                    position: "relative",
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "12px 14px",
                    borderRadius: 13,
                    background: isSelected ? "var(--bg2)" : "var(--bg1)",
                    border: isSelected
                      ? "1.5px solid var(--accent-bd)"
                      : isRootCause
                      ? "1px solid var(--root)"
                      : "1px solid var(--bd)",
                    cursor: "pointer",
                    boxShadow: isSelected ? "var(--shadow-sm)" : "none",
                    transition: "background 0.12s, border-color 0.12s",
                    animation: "fadeup .25s ease",
                  }}
                >
                  {/* Left color rail */}
                  <div
                    style={{
                      position: "absolute",
                      left: 0,
                      top: "15%",
                      bottom: "15%",
                      width: 3,
                      borderRadius: "0 3px 3px 0",
                      background: isRootCause
                        ? "var(--root)"
                        : isError
                        ? "var(--fail)"
                        : isSideEffect
                        ? "var(--warn)"
                        : isSelected
                        ? "var(--accent)"
                        : "transparent",
                    }}
                  />

                  {/* Icon tile */}
                  <div
                    style={{
                      width: 32,
                      height: 32,
                      borderRadius: 9,
                      background:
                        step.type === "llm_call" ? "var(--accent-dim)" : "var(--bg3)",
                      border: "1px solid var(--bd2)",
                      display: "grid",
                      placeItems: "center",
                      flex: "none",
                    }}
                  >
                    {step.type === "llm_call" ? (
                      <svg width="15" height="15" viewBox="0 0 20 20" fill="none" stroke="var(--accent)" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M4 6h12M4 10h8M4 14h10" />
                      </svg>
                    ) : (
                      <svg width="15" height="15" viewBox="0 0 20 20" fill="none" stroke={isSideEffect ? "var(--warn)" : "var(--fg1)"} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M5 3v6a3 3 0 003 3h3M11 9l3 3-3 3" />
                      </svg>
                    )}
                  </div>

                  {/* Info */}
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                      <span style={{ font: "600 9.5px var(--mono)", color: isSelected ? "var(--accent)" : "var(--fg2)" }}>
                        {step.step_id.toString().padStart(2, "0")}
                      </span>
                      <span
                        style={{
                          font: "600 13px var(--ui)",
                          color: "var(--fg0)",
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                        }}
                      >
                        {step.type === "llm_call"
                          ? step.model ?? "LLM call"
                          : step.tool ?? "tool call"}
                      </span>
                    </div>
                    <div
                      style={{
                        font: "450 10px var(--mono)",
                        color: "var(--fg2)",
                        marginTop: 2,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {step.type}
                      {step.latency_ms != null ? ` · ${step.latency_ms}ms` : ""}
                      {step.confidence != null
                        ? ` · conf ${Math.round(step.confidence * 100)}%`
                        : ""}
                    </div>
                    {/* Blame bar */}
                    {blameScore > 0 && (
                      <div style={{ height: 3, borderRadius: 3, background: "var(--bg3)", marginTop: 7, overflow: "hidden" }}>
                        <div
                          style={{
                            width: `${Math.round(blameScore * 100)}%`,
                            height: "100%",
                            borderRadius: 3,
                            background: isRootCause ? "var(--root)" : "var(--warn)",
                          }}
                        />
                      </div>
                    )}
                  </div>

                  {/* Right badges */}
                  <div style={{ flex: "none", display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 5 }}>
                    {isError && (
                      <span
                        style={{
                          font: "700 8px var(--mono)",
                          color: "#fff",
                          background: "var(--fail)",
                          borderRadius: 5,
                          padding: "2px 5px",
                          letterSpacing: ".04em",
                        }}
                      >
                        FAIL
                      </span>
                    )}
                    {isRootCause && (
                      <span
                        style={{
                          font: "700 8px var(--mono)",
                          color: "#fff",
                          background: "var(--root)",
                          borderRadius: 5,
                          padding: "2px 5px",
                          letterSpacing: ".04em",
                        }}
                      >
                        ROOT
                      </span>
                    )}
                    <div style={{ display: "flex", gap: 5, alignItems: "center" }}>
                      {isSideEffect && (
                        <span
                          title="side-effecting"
                          style={{
                            width: 9,
                            height: 9,
                            borderRadius: 3,
                            background: "var(--warn)",
                            boxShadow: "0 0 0 3px var(--warn-dim)",
                          }}
                        />
                      )}
                      {step.confidence != null && step.confidence < 0.7 && (
                        <span
                          title="low confidence"
                          style={{
                            width: 9,
                            height: 9,
                            borderRadius: "50%",
                            border: "1px solid var(--warn)",
                            background: "repeating-linear-gradient(45deg, var(--warn), var(--warn) 2px, transparent 2px, transparent 4px)",
                          }}
                        />
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right: Step inspector */}
        <StepInspector
          trace={trace}
          stepId={selectedStepId}
          blame={blame}
          resolvedStep={resolvedStep}
          memoryMatch={memoryEntry ? { label: memoryLabel, blameStep: memoryEntry.entry.blame_step } : null}
        />
      </div>
    </div>
  );
}
