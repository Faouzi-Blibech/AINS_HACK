// Trajectory -- the execution graph, rendered as a vertical spine of numbered
// nodes on a dotted grid, colored by blame tier, with red dashed causal curves
// linking the root cause through contributors to the failed step. Matches the
// Cassette v1 design (TRAJECTORY panel).

const TIER_BORDER = {
  root: "var(--root)",
  contributor: "var(--contrib)",
  innocent: "var(--bd2)",
  neutral: "var(--bd2)",
};
const TIER_CHIP = {
  root: "var(--root)",
  contributor: "var(--contrib)",
  innocent: "var(--fg1)",
  neutral: "var(--fg1)",
};

function tierOf(stepId, blame) {
  if (!blame) return "neutral";
  if (stepId === blame.root_cause_step_id) return "root";
  const entry = blame.steps?.find((s) => s.step_id === stepId);
  if (!entry) return "neutral";
  return entry.blame_score > 0 ? "contributor" : "innocent";
}

// Canvas geometry
const NODE_W = 248;
const NODE_H = 54;
const GAP = 30;
const X = 104; // node left edge (leaves a left margin for the causal curves)
const TOP = 22;
const CX = X + NODE_W / 2; // spine x (node horizontal center)

const LEGEND = [
  { label: "innocent", swatch: { background: "var(--innocent)", borderRadius: "50%" } },
  { label: "contributed", swatch: { background: "var(--contrib)", borderRadius: "50%" } },
  { label: "root cause", swatch: { background: "var(--root)", borderRadius: "50%" } },
  {
    label: "side-effecting",
    swatch: { background: "var(--fail)", borderRadius: 3, boxShadow: "0 0 0 2px var(--fail-dim)" },
  },
  {
    label: "low confidence",
    swatch: {
      background:
        "repeating-linear-gradient(45deg,var(--warn),var(--warn) 2px,transparent 2px,transparent 4px)",
      border: "1px solid var(--warn)",
      borderRadius: "50%",
    },
  },
];

export default function Trajectory({ trace, blame, selectedStepId, onSelectStep }) {
  const steps = trace.steps ?? [];
  const yOf = (i) => TOP + i * (NODE_H + GAP);
  const midY = (i) => yOf(i) + NODE_H / 2;
  const canvasH = TOP + steps.length * (NODE_H + GAP) + 24;
  const canvasW = X + NODE_W + 60;

  const indexOfStep = (stepId) => steps.findIndex((s) => s.step_id === stepId);

  // Causal chain: root cause -> contributors -> failed step, in execution order.
  const chainIds = steps
    .filter((s) => {
      const t = tierOf(s.step_id, blame);
      return t === "root" || t === "contributor" || s.step_id === blame?.failed_step_id;
    })
    .map((s) => s.step_id);

  const causalPaths = [];
  for (let k = 0; k < chainIds.length - 1; k++) {
    const ai = indexOfStep(chainIds[k]);
    const bi = indexOfStep(chainIds[k + 1]);
    if (ai < 0 || bi < 0) continue;
    const ya = midY(ai);
    const yb = midY(bi);
    // bow out to the left of the node column
    causalPaths.push(
      `M ${X} ${ya} C ${X - 78} ${ya + 26}, ${X - 78} ${yb - 26}, ${X - 4} ${yb}`
    );
  }

  return (
    <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
      {/* Header: TRAJECTORY label + legend */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 16,
          padding: "11px 22px",
          borderBottom: "1px solid var(--bd)",
          flexWrap: "wrap",
          flex: "none",
        }}
      >
        <div style={{ font: "600 10px var(--mono)", letterSpacing: ".1em", color: "var(--fg2)" }}>
          TRAJECTORY
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          {LEGEND.map((lg) => (
            <div key={lg.label} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ width: 11, height: 11, flex: "none", ...lg.swatch }} />
              <span style={{ font: "450 10.5px var(--ui)", color: "var(--fg1)" }}>{lg.label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Canvas: dotted grid */}
      <div
        style={{
          flex: 1,
          overflow: "auto",
          position: "relative",
          background: "var(--bg0)",
          backgroundImage: "radial-gradient(var(--bd) .8px, transparent .8px)",
          backgroundSize: "22px 22px",
        }}
      >
        <div style={{ position: "relative", width: canvasW, height: canvasH, margin: "18px auto 40px" }}>
          {/* Edges + causal overlay */}
          <svg width={canvasW} height={canvasH} style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
            <defs>
              <marker id="tj-arrow" markerWidth="7" markerHeight="7" refX="5.5" refY="3" orient="auto">
                <path d="M0 0l6 3-6 3z" fill="var(--root)" />
              </marker>
            </defs>

            {/* Vertical spine between consecutive nodes */}
            {steps.slice(0, -1).map((s, i) => (
              <line
                key={`spine-${s.step_id}`}
                x1={CX}
                y1={yOf(i) + NODE_H}
                x2={CX}
                y2={yOf(i + 1)}
                stroke="var(--bd3)"
                strokeWidth={1.6}
              />
            ))}

            {/* Causal chain: root -> ... -> failed */}
            {blame &&
              causalPaths.map((d, i) => (
                <path
                  key={`cz-${i}`}
                  d={d}
                  fill="none"
                  stroke="var(--root)"
                  strokeWidth={2}
                  strokeDasharray="5 5"
                  markerEnd="url(#tj-arrow)"
                  opacity={0.85}
                  style={{ animation: "dashflow 1s linear infinite" }}
                />
              ))}
          </svg>

          {/* Nodes */}
          {steps.map((step, i) => {
            const tier = tierOf(step.step_id, blame);
            const selected = step.step_id === selectedStepId;
            const isFailed = blame
              ? step.step_id === blame.failed_step_id
              : step.status === "error";
            const sideEffecting = !!step.side_effecting;
            const needsReview = step.confidence != null && step.confidence < 0.7;

            const title =
              step.type === "llm_call"
                ? step.model ?? "llm call"
                : step.tool ?? "tool call";
            const sub =
              `n${step.step_id} · ${step.type}` +
              (step.latency_ms != null ? ` · ${step.latency_ms}ms` : "");

            const shadow = selected
              ? "0 0 0 2px var(--accent), 0 10px 26px rgba(0,0,0,.34)"
              : tier === "root"
              ? "0 0 0 1px var(--root), 0 0 16px var(--fail-dim)"
              : "none";

            return (
              <div
                key={step.step_id}
                onClick={() => onSelectStep(step.step_id)}
                style={{
                  position: "absolute",
                  left: X,
                  top: yOf(i),
                  width: NODE_W,
                  height: NODE_H,
                  boxSizing: "border-box",
                  cursor: "pointer",
                  background: "var(--bg2)",
                  border: `1px solid ${selected ? "var(--accent-bd)" : TIER_BORDER[tier]}`,
                  borderRadius: 10,
                  padding: "7px 11px",
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  boxShadow: shadow,
                  transform: selected ? "translateY(-1px)" : "none",
                  transition: "box-shadow .16s ease, transform .16s ease, border-color .16s",
                  zIndex: selected ? 6 : 2,
                }}
              >
                {/* Step number chip */}
                <div
                  style={{
                    flex: "none",
                    width: 22,
                    height: 22,
                    borderRadius: 6,
                    display: "grid",
                    placeItems: "center",
                    font: "600 10px var(--mono)",
                    background: "var(--bg3)",
                    color: TIER_CHIP[tier],
                    border: `1px solid ${tier === "innocent" || tier === "neutral" ? "var(--bd)" : TIER_BORDER[tier]}`,
                  }}
                >
                  {step.step_id}
                </div>

                {/* Title + sub */}
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div
                    style={{
                      font: "600 11.5px var(--ui)",
                      color: "var(--fg0)",
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    {title}
                  </div>
                  <div
                    style={{
                      font: "450 9.5px var(--mono)",
                      color: "var(--fg2)",
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      marginTop: 1,
                    }}
                  >
                    {sub}
                  </div>
                </div>

                {/* Indicators */}
                <div style={{ flex: "none", display: "flex", alignItems: "center", gap: 5 }}>
                  {sideEffecting && (
                    <span
                      title="side-effecting tool"
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: 2,
                        background: "var(--fail)",
                        boxShadow: "0 0 0 3px var(--fail-dim)",
                      }}
                    />
                  )}
                  {needsReview && (
                    <span
                      title="low confidence"
                      style={{
                        width: 9,
                        height: 9,
                        borderRadius: "50%",
                        background:
                          "repeating-linear-gradient(45deg,var(--warn),var(--warn) 2px,transparent 2px,transparent 4px)",
                        border: "1px solid var(--warn)",
                      }}
                    />
                  )}
                  {isFailed && (
                    <span
                      style={{
                        font: "700 8px var(--mono)",
                        color: "#fff",
                        background: "var(--fail)",
                        borderRadius: 4,
                        padding: "2px 4px",
                        letterSpacing: ".04em",
                      }}
                    >
                      FAIL
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
