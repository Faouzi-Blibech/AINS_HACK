// TapeStrip -- TAPE step-strip: the primary trace visualization replacing React Flow DAG.
// Shows a row of numbered step chips; selected chip is highlighted with accent color.
// Error steps get a red dot; side-effecting steps get an amber dot.

export default function TapeStrip({ steps, selectedStepId, onSelectStep, durationMs }) {
  if (!steps || steps.length === 0) return null;

  const durationLabel = durationMs != null
    ? (durationMs / 1000).toFixed(2) + "s"
    : null;

  return (
    <div
      style={{
        margin: "16px 24px 0",
        padding: "14px 18px",
        background: "var(--bg1)",
        border: "1px solid var(--bd)",
        borderRadius: 16,
        display: "flex",
        alignItems: "center",
        gap: 18,
        boxShadow: "var(--shadow-sm)",
      }}
    >
      {/* Cassette icon + TAPE label */}
      <div style={{ display: "flex", alignItems: "center", gap: 13, flex: "none" }}>
        <svg width="44" height="26" viewBox="0 0 44 26">
          <rect x="1" y="1" width="42" height="24" rx="6" fill="var(--bg3)" stroke="var(--bd2)" />
          <g style={{ animation: "reelspin 4s linear infinite", transformOrigin: "14px 13px" }}>
            <circle cx="14" cy="13" r="6" fill="none" stroke="var(--accent)" strokeWidth="2" />
            <circle cx="14" cy="13" r="1.5" fill="var(--accent)" />
          </g>
          <g style={{ animation: "reelspin 4s linear infinite", transformOrigin: "30px 13px" }}>
            <circle cx="30" cy="13" r="6" fill="none" stroke="var(--accent)" strokeWidth="2" />
            <circle cx="30" cy="13" r="1.5" fill="var(--accent)" />
          </g>
        </svg>
        <div>
          <div style={{ font: "600 9px var(--mono)", letterSpacing: ".12em", color: "var(--fg2)" }}>
            TAPE
          </div>
          <div style={{ font: "600 13px var(--mono)", color: "var(--fg0)", marginTop: 1 }}>
            STEP {selectedStepId ?? "?"} / {steps.length}
          </div>
        </div>
      </div>

      {/* Step chips */}
      <div
        style={{
          flex: 1,
          minWidth: 0,
          display: "flex",
          gap: 5,
          alignItems: "center",
          overflowX: "auto",
          paddingBottom: 2,
        }}
      >
        {steps.map((step) => {
          const isSelected = step.step_id === selectedStepId;
          const isError = step.status === "error";
          const isSideEffect = step.side_effecting;

          return (
            <button
              key={step.step_id}
              onClick={() => onSelectStep(step.step_id)}
              title={`Step ${step.step_id}${step.type ? " · " + step.type : ""}${isError ? " · ERROR" : ""}${isSideEffect ? " · side-effecting" : ""}`}
              style={{
                position: "relative",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                width: 46,
                height: 54,
                flexShrink: 0,
                borderRadius: 10,
                background: isSelected ? "var(--accent-dim)" : "var(--bg2)",
                border: isSelected ? "1.5px solid var(--accent-bd)" : "1px solid var(--bd)",
                cursor: "pointer",
                transition: "background 0.13s, border-color 0.13s, box-shadow 0.13s",
                boxShadow: isSelected
                  ? "0 0 0 2px var(--accent-bd), 0 0 18px rgba(51,225,212,.12)"
                  : "none",
                outline: "none",
              }}
            >
              {/* Error or side-effecting dot in top-right */}
              {(isError || isSideEffect) && (
                <span
                  style={{
                    position: "absolute",
                    top: 5,
                    right: 5,
                    width: 6,
                    height: 6,
                    borderRadius: 2,
                    background: isError ? "var(--fail)" : "var(--warn)",
                    boxShadow: isError
                      ? "0 0 0 2px var(--fail-dim)"
                      : "0 0 0 2px var(--warn-dim)",
                  }}
                />
              )}

              {/* Step number */}
              <span
                style={{
                  font: "600 13px var(--mono)",
                  color: isSelected
                    ? "var(--accent)"
                    : isError
                    ? "var(--fail)"
                    : "var(--fg1)",
                  lineHeight: 1,
                }}
              >
                {step.step_id}
              </span>

              {/* Active underline bar */}
              <span
                style={{
                  position: "absolute",
                  bottom: 5,
                  left: "20%",
                  right: "20%",
                  height: 2,
                  borderRadius: 2,
                  background: isSelected ? "var(--accent)" : "transparent",
                  transition: "background 0.13s",
                }}
              />
            </button>
          );
        })}
      </div>

      {/* Duration */}
      {durationLabel && (
        <div style={{ flex: "none", textAlign: "right" }}>
          <div
            style={{
              font: "600 9px var(--mono)",
              letterSpacing: ".1em",
              color: "var(--fg2)",
            }}
          >
            DURATION
          </div>
          <div
            style={{
              font: "600 13px var(--mono)",
              color: "var(--fg1)",
              marginTop: 1,
            }}
          >
            {durationLabel}
          </div>
        </div>
      )}
    </div>
  );
}
