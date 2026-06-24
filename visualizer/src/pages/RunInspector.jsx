// RunInspector v2 -- the hero trace view, wired to the live FastAPI backend.
// Layout: transport bar > side-effects banner > tape strip > memory banner > root-cause panel > graph+inspector

import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getTrace, getBlame, getLibrary, getStep, getRunMemory } from "../api/client.js";
import { getMetrics } from "../api/client.js";
import TapeStrip from "../components/TapeStrip.jsx";
import MemoryBanner from "../components/MemoryBanner.jsx";
import RootCausePanel from "../components/RootCausePanel.jsx";
import SideEffectsBanner from "../components/SideEffectsBanner.jsx";
import Trajectory from "../components/Trajectory.jsx";
import StepInspector from "../StepInspector.jsx";
import Dock from "../components/Dock.jsx";

// Transport controls: REC (visual) / PLAY (steps the tape) / OVER (record-over:
// jumps to the Divergence tab where you inject a change and fork the trajectory).
function TransportControls({ isPlaying, onPlay, onOver, overActive }) {
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
    </div>
  );
}

export default function RunInspector() {
  const { runId } = useParams();
  const [trace, setTrace] = useState(null);
  const [blame, setBlame] = useState(null);
  const [library, setLibrary] = useState(null);
  const [memory, setMemory] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [selectedStepId, setSelectedStepId] = useState(null);
  const [resolvedStep, setResolvedStep] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const rootCauseRef = useRef(null);
  const dockRef = useRef(null);
  const [dockTab, setDockTab] = useState("Debug agent");
  const [overActive, setOverActive] = useState(false);

  // Resolve the effective run id -- "latest" maps to first available or fixture
  const effectiveRunId = runId === "latest" ? "run-fixture-001" : runId;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setTrace(null);
    setBlame(null);
    setLibrary(null);
    setMemory(null);
    setResolvedStep(null);

    Promise.all([
      getTrace(effectiveRunId),
      getBlame(effectiveRunId).catch(() => null),
      getLibrary().catch(() => null),
      getMetrics().catch(() => null),
      getRunMemory(effectiveRunId).catch(() => null),
    ])
      .then(([traceData, blameData, libraryData, metricsData, memoryData]) => {
        if (cancelled) return;
        setTrace(traceData);
        setBlame(blameData);
        setLibrary(libraryData);
        setMetrics(metricsData);
        setMemory(memoryData);

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

  // OVER = record-over: focus the Divergence tab (inject a change + fork the
  // trajectory) and scroll the analysis dock into view.
  const handleOver = () => {
    setOverActive(true);
    setDockTab("Divergence");
    dockRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  // Memory match: semantic recall from /runs/{id}/memory -- the AI ranks prior
  // failures by meaning (not by step number) and we surface the top match only
  // when it clears the relevance threshold (memory.available).
  const memoryTop = memory?.available && memory.matches?.length ? memory.matches[0] : null;
  const memoryEntry = memoryTop
    ? { entry: memoryTop, score: memoryTop.score, rationale: memory.rationale }
    : null;
  const memoryLabel = memoryTop ? `FM-${memoryTop.id}` : null;

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
  const stepCount = trace.steps?.length ?? 0;
  const runSummary = `${stepCount} step${stepCount === 1 ? "" : "s"} · ${trace.status ?? trace.mode ?? "record"}`;

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
          <TransportControls isPlaying={isPlaying} onPlay={handlePlayToggle} onOver={handleOver} overActive={overActive} />
        </div>


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
        <MemoryBanner
          entry={memoryEntry.entry}
          label={memoryLabel}
          score={memoryEntry.score}
          rationale={memoryEntry.rationale}
        />
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
        {/* Left: execution trajectory graph */}
        <Trajectory
          trace={trace}
          blame={blame}
          selectedStepId={selectedStepId}
          onSelectStep={setSelectedStepId}
        />

        {/* Right: Step inspector */}
        <StepInspector
          trace={trace}
          stepId={selectedStepId}
          blame={blame}
          resolvedStep={resolvedStep}
          memoryMatch={memoryEntry ? { label: memoryLabel, blameStep: memoryEntry.entry.blame_step } : null}
        />
      </div>

      {/* ===== ANALYSIS DOCK ===== */}
      <div ref={dockRef}>
        <Dock
          trace={trace}
          blame={blame}
          selectedStepId={selectedStepId}
          activeTab={dockTab}
          onTabChange={setDockTab}
        />
      </div>
    </div>
  );
}
