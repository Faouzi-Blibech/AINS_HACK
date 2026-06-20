// StepInspector v2 -- restyled to v2 tokens.
// Accepts either a resolved step object (from getStep API) or falls back to
// resolving blob refs locally if resolvedStep is not provided.
// Props:
//   trace         -- full trace (for step list lookup)
//   stepId        -- currently selected step_id
//   blame         -- BlameGraphResponse (from /blame)
//   resolvedStep  -- ResolvedStepDetail from getStep() (optional; when provided, use its inlined content)

function ConfidenceGauge({ value, color }) {
  const pct = Math.round((value ?? 0) * 100);
  const circumference = 2 * Math.PI * 34;
  const dash = `${(pct / 100) * circumference} ${circumference}`;
  return (
    <div style={{ position: "relative", flex: "none" }}>
      <svg width="84" height="84" viewBox="0 0 84 84" style={{ transform: "rotate(-90deg)" }}>
        <circle cx="42" cy="42" r="34" fill="none" stroke="var(--bg3)" strokeWidth="9" />
        <circle
          cx="42"
          cy="42"
          r="34"
          fill="none"
          stroke={color}
          strokeWidth="9"
          strokeLinecap="round"
          strokeDasharray={dash}
        />
      </svg>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <span style={{ font: "700 19px var(--mono)", color, lineHeight: 1 }}>{pct}%</span>
        <span
          style={{
            font: "600 7.5px var(--mono)",
            letterSpacing: ".1em",
            color: "var(--fg2)",
            marginTop: 1,
          }}
        >
          CONF
        </span>
      </div>
    </div>
  );
}

function ContentBlock({ label, value }) {
  if (value === null || value === undefined) {
    return (
      <div>
        <div
          style={{
            font: "600 9.5px var(--mono)",
            letterSpacing: ".1em",
            color: "var(--fg2)",
            marginBottom: 7,
          }}
        >
          {label}
        </div>
        <p style={{ font: "450 11.5px var(--mono)", color: "var(--fg2)", fontStyle: "italic", margin: 0 }}>
          content unavailable
        </p>
      </div>
    );
  }

  const text = typeof value === "object" ? JSON.stringify(value, null, 2) : String(value);
  return (
    <div>
      <div
        style={{
          font: "600 9.5px var(--mono)",
          letterSpacing: ".1em",
          color: "var(--fg2)",
          marginBottom: 7,
        }}
      >
        {label}
      </div>
      <pre
        style={{
          margin: 0,
          background: "var(--bg2)",
          border: "1px solid var(--bd)",
          borderRadius: 13,
          padding: "13px 14px",
          overflow: "auto",
          whiteSpace: "pre-wrap",
          font: "450 11.5px var(--mono)",
          lineHeight: 1.65,
          color: "var(--fg1)",
        }}
      >
        {text}
      </pre>
    </div>
  );
}

export default function StepInspector({ trace, stepId, blame, resolvedStep }) {
  const step = trace?.steps?.find((s) => s.step_id === stepId);

  const blameEntry =
    blame && blame.steps
      ? blame.steps.find((b) => b.step_id === stepId)
      : null;
  const isRootCause = blame && blame.root_cause_step_id === stepId;
  const isFailedStep = blame && blame.failed_step_id === stepId;
  const isContributor = !isRootCause && blameEntry && blameEntry.blame_score > 0;
  const showBlame = blame != null && (isRootCause || isFailedStep || isContributor);

  if (!step) {
    return (
      <aside
        style={{
          width: 412,
          flex: "none",
          borderLeft: "1px solid var(--bd)",
          background: "var(--bg1)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <span style={{ font: "450 12px var(--ui)", color: "var(--fg2)" }}>
          Select a step to inspect it.
        </span>
      </aside>
    );
  }

  const isLlm = step.type === "llm_call";
  const isTool = step.type === "tool_call";
  const confidence = step.confidence;
  const needsReview = confidence != null && confidence < 0.7;
  const confColor = needsReview ? "var(--warn)" : confidence != null ? "var(--pass)" : "var(--fg2)";

  // Content from resolvedStep (API) if available, else null
  const prompt = resolvedStep?.prompt ?? null;
  const response = resolvedStep?.response ?? null;
  const args = resolvedStep?.args ?? null;
  const result = resolvedStep?.result ?? null;

  const kindLabel = isLlm ? "LLM CALL" : isTool ? "TOOL CALL" : step.type?.toUpperCase() ?? "STEP";

  return (
    <aside
      style={{
        width: 412,
        flex: "none",
        borderLeft: "1px solid var(--bd)",
        borderTop: "1px solid var(--bd)",
        background: "var(--bg1)",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "18px 20px 15px",
          borderBottom: "1px solid var(--bd)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 10,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: 9,
                background: isLlm ? "var(--accent-dim)" : isTool ? "var(--bg3)" : "var(--bg3)",
                border: "1px solid var(--bd2)",
                display: "grid",
                placeItems: "center",
                flex: "none",
              }}
            >
              {isLlm ? (
                <svg width="15" height="15" viewBox="0 0 20 20" fill="none" stroke="var(--accent)" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 6h12M4 10h8M4 14h10" />
                </svg>
              ) : (
                <svg width="15" height="15" viewBox="0 0 20 20" fill="none" stroke="var(--fg1)" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M5 3v6a3 3 0 003 3h3M11 9l3 3-3 3" />
                </svg>
              )}
            </div>
            <div>
              <div style={{ font: "600 9px var(--mono)", letterSpacing: ".08em", color: "var(--fg2)" }}>
                {kindLabel} &middot; STEP {step.step_id}
              </div>
              <h2 style={{ margin: "2px 0 0", font: "600 17px var(--ui)", letterSpacing: "-.01em", color: "var(--fg0)" }}>
                {isLlm ? (step.model ?? "LLM") : (step.tool ?? "Tool")}
              </h2>
            </div>
          </div>

          {/* Blame pill */}
          {isRootCause && (
            <span
              style={{
                font: "600 9px var(--mono)",
                letterSpacing: ".06em",
                color: "#fff",
                background: "var(--root)",
                borderRadius: 8,
                padding: "3px 9px",
                flex: "none",
              }}
            >
              ROOT CAUSE
            </span>
          )}
          {!isRootCause && isContributor && (
            <span
              style={{
                font: "600 9px var(--mono)",
                letterSpacing: ".06em",
                color: "var(--warn)",
                background: "var(--warn-dim)",
                border: "1px solid var(--warn)",
                borderRadius: 8,
                padding: "3px 9px",
                flex: "none",
              }}
            >
              CONTRIBUTOR
            </span>
          )}
          {!isRootCause && isFailedStep && !isContributor && (
            <span
              style={{
                font: "600 9px var(--mono)",
                letterSpacing: ".06em",
                color: "var(--fail)",
                background: "var(--fail-dim)",
                border: "1px solid var(--fail)",
                borderRadius: 8,
                padding: "3px 9px",
                flex: "none",
              }}
            >
              FAILED HERE
            </span>
          )}
        </div>

        <div style={{ font: "450 11px var(--mono)", color: "var(--fg2)", marginTop: 9 }}>
          step_id:{step.step_id}
          {step.type === "tool_call" && step.transport ? ` · ${step.transport}` : ""}
          {step.latency_ms != null ? ` · ${step.latency_ms}ms` : ""}
        </div>
      </div>

      {/* Body */}
      <div
        style={{
          flex: 1,
          overflow: "auto",
          padding: "18px 20px",
          display: "flex",
          flexDirection: "column",
          gap: 18,
        }}
      >
        {/* Confidence gauge + meta */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 18,
            background: "var(--bg2)",
            border: "1px solid var(--bd)",
            borderRadius: 14,
            padding: 16,
          }}
        >
          {confidence != null ? (
            <ConfidenceGauge value={confidence} color={confColor} />
          ) : (
            <div
              style={{
                width: 84,
                height: 84,
                borderRadius: "50%",
                background: "var(--bg3)",
                border: "1px solid var(--bd2)",
                display: "grid",
                placeItems: "center",
                flex: "none",
              }}
            >
              <span style={{ font: "600 8px var(--mono)", color: "var(--fg2)", letterSpacing: ".06em" }}>N/A</span>
            </div>
          )}

          <div style={{ flex: 1, minWidth: 0 }}>
            {needsReview && (
              <span
                style={{
                  font: "600 9px var(--mono)",
                  color: "var(--warn)",
                  background: "var(--warn-dim)",
                  border: "1px solid var(--warn)",
                  borderRadius: 6,
                  padding: "2px 7px",
                  display: "inline-block",
                  marginBottom: 9,
                  letterSpacing: ".04em",
                }}
              >
                NEEDS REVIEW
              </span>
            )}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              <div>
                <div style={{ font: "600 8px var(--mono)", letterSpacing: ".08em", color: "var(--fg2)" }}>TYPE</div>
                <div style={{ font: "550 12px var(--mono)", color: "var(--fg0)", marginTop: 2 }}>{step.type}</div>
              </div>
              <div>
                <div style={{ font: "600 8px var(--mono)", letterSpacing: ".08em", color: "var(--fg2)" }}>STATUS</div>
                <div
                  style={{
                    font: "550 12px var(--mono)",
                    color: step.status === "error" ? "var(--fail)" : step.status === "ok" ? "var(--pass)" : "var(--fg0)",
                    marginTop: 2,
                  }}
                >
                  {step.status ?? "unknown"}
                </div>
              </div>
              <div>
                <div style={{ font: "600 8px var(--mono)", letterSpacing: ".08em", color: "var(--fg2)" }}>SIDE EFFECT</div>
                <div
                  style={{
                    font: "550 12px var(--mono)",
                    color: step.side_effecting ? "var(--warn)" : "var(--pass)",
                    marginTop: 2,
                  }}
                >
                  {step.side_effecting ? "YES" : "NO"}
                </div>
              </div>
              {step.latency_ms != null && (
                <div>
                  <div style={{ font: "600 8px var(--mono)", letterSpacing: ".08em", color: "var(--fg2)" }}>LATENCY</div>
                  <div style={{ font: "550 12px var(--mono)", color: "var(--fg0)", marginTop: 2 }}>{step.latency_ms}ms</div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* LLM call: prompt + response */}
        {isLlm && (
          <>
            <ContentBlock label="PROMPT · CONTEXT WINDOW" value={prompt} />
            <ContentBlock label="RESPONSE" value={response} />
          </>
        )}

        {/* Tool call: tool name + args + result */}
        {isTool && (
          <>
            <div>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 9 }}>
                <span style={{ font: "600 9.5px var(--mono)", letterSpacing: ".1em", color: "var(--fg2)" }}>
                  TOOL CALL
                </span>
                {step.side_effecting && (
                  <span
                    style={{
                      font: "600 8.5px var(--mono)",
                      color: "var(--fail)",
                      background: "var(--fail-dim)",
                      border: "1px solid var(--fail)",
                      borderRadius: 6,
                      padding: "2px 7px",
                      display: "flex",
                      alignItems: "center",
                      gap: 5,
                    }}
                  >
                    <span style={{ width: 6, height: 6, borderRadius: 2, background: "var(--fail)", display: "inline-block" }} />
                    SIDE-EFFECTING &middot; MOCKED ON REPLAY
                  </span>
                )}
              </div>
              <div
                style={{
                  font: "600 13px var(--mono)",
                  color: "var(--accent2)",
                  background: "var(--accent-dim)",
                  border: "1px solid var(--accent-bd)",
                  borderRadius: 10,
                  padding: "10px 13px",
                  marginBottom: 11,
                }}
              >
                {step.tool}()
              </div>
            </div>
            <ContentBlock label="ARGUMENTS" value={args} />
            <ContentBlock label="RESULT" value={result} />
          </>
        )}

        {/* Blame section */}
        {showBlame && blameEntry && (
          <div
            style={{
              background: "var(--bg2)",
              border: "1px solid var(--bd)",
              borderRadius: 13,
              padding: "14px 16px",
            }}
          >
            <div style={{ font: "600 9.5px var(--mono)", letterSpacing: ".1em", color: "var(--fg2)", marginBottom: 10 }}>
              BLAME ANALYSIS
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 10 }}>
              <div
                style={{
                  font: "700 20px var(--mono)",
                  color: isRootCause ? "var(--root)" : isContributor ? "var(--warn)" : "var(--fg1)",
                }}
              >
                {Math.round(blameEntry.blame_score * 100)}%
              </div>
              <div style={{ font: "600 8.5px var(--mono)", letterSpacing: ".06em", color: "var(--fg2)" }}>
                BLAME SCORE
              </div>
            </div>

            {/* Blame bar */}
            <div
              style={{
                height: 5,
                borderRadius: 5,
                background: "var(--bg3)",
                overflow: "hidden",
                marginBottom: 10,
              }}
            >
              <div
                style={{
                  width: `${Math.round(blameEntry.blame_score * 100)}%`,
                  height: "100%",
                  borderRadius: 5,
                  background: isRootCause ? "var(--root)" : isContributor ? "var(--warn)" : "var(--fg2)",
                  transition: "width 0.4s ease",
                }}
              />
            </div>

            {blameEntry.rationale && (
              <p style={{ font: "450 11.5px var(--ui)", color: "var(--fg1)", margin: 0, lineHeight: 1.55 }}>
                {blameEntry.rationale}
              </p>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
