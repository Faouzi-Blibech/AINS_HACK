// RootCausePanel -- red verdict panel showing root-cause analysis from /blame.
// Shows "Step X is where it failed. Step Y is why." with verdict, determinism, confidence.

export default function RootCausePanel({ blame, metrics }) {
  if (!blame) return null;

  // No failure detected case
  if (blame.root_cause_step_id == null) {
    return (
      <div
        id="root-cause-panel"
        style={{
          margin: "14px 24px 0",
          padding: "16px 18px",
          border: "1px solid var(--bd)",
          background: "var(--bg2)",
          borderRadius: 16,
          display: "flex",
          alignItems: "center",
          gap: 14,
          animation: "fadeup .3s ease",
        }}
      >
        <svg width="20" height="20" viewBox="0 0 20 20">
          <circle cx="10" cy="10" r="8" fill="none" stroke="var(--pass)" strokeWidth="1.8" />
          <path d="M6.5 10l2.5 2.5 4.5-5" fill="none" stroke="var(--pass)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span style={{ font: "500 13px var(--ui)", color: "var(--fg1)" }}>
          No failure detected in this run.
        </span>
      </div>
    );
  }

  const determinism = metrics?.determinism_rate != null
    ? Math.round(metrics.determinism_rate * 100) + "%"
    : "100%";

  const confidence = blame.confidence ?? 0;
  const confidencePct = Math.round(confidence * 100);
  const needsReview = confidence < 0.6;

  return (
    <div
      id="root-cause-panel"
      style={{
        margin: "14px 24px 0",
        padding: "16px 18px",
        border: "1px solid var(--root)",
        background: "var(--fail-dim)",
        borderRadius: 16,
        display: "flex",
        alignItems: "center",
        gap: 16,
        animation: "fadeup .3s ease",
        boxShadow: "var(--shadow-sm)",
      }}
    >
      {/* Icon tile */}
      <div
        style={{
          width: 40,
          height: 40,
          borderRadius: 11,
          background: "var(--root)",
          display: "grid",
          placeItems: "center",
          flex: "none",
          boxShadow: "0 0 0 5px var(--fail-dim)",
        }}
      >
        <svg width="19" height="19" viewBox="0 0 18 18">
          <path d="M9 2l7 13H2z" fill="none" stroke="#fff" strokeWidth="1.8" strokeLinejoin="round" />
          <path d="M9 7v4" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" />
          <circle cx="9" cy="13" r="1" fill="#fff" />
        </svg>
      </div>

      {/* Verdict text */}
      <div style={{ flex: 1 }}>
        <div
          style={{
            font: "600 17px var(--ui)",
            color: "var(--fg0)",
            letterSpacing: "-.01em",
            lineHeight: 1.3,
          }}
        >
          Step&nbsp;
          <span style={{ color: "var(--root)" }}>{blame.failed_step_id}</span>
          {" "}is{" "}
          <span style={{ color: "var(--root)" }}>where it failed.</span>
          {" "}Step&nbsp;
          <span style={{ color: "var(--root)" }}>{blame.root_cause_step_id}</span>
          {" "}is{" "}
          <span style={{ color: "var(--root)" }}>why.</span>
        </div>
        {blame.verdict && (
          <div
            style={{
              font: "450 12.5px var(--ui)",
              color: "var(--fg1)",
              marginTop: 5,
              lineHeight: 1.55,
            }}
          >
            {blame.verdict}
          </div>
        )}
        {needsReview && (
          <span
            style={{
              display: "inline-block",
              marginTop: 7,
              font: "600 9px var(--mono)",
              color: "var(--warn)",
              background: "var(--warn-dim)",
              border: "1px solid var(--warn)",
              borderRadius: 6,
              padding: "2px 7px",
              letterSpacing: ".06em",
            }}
          >
            LOW CONFIDENCE -- NEEDS REVIEW
          </span>
        )}
      </div>

      {/* Right: determinism + confidence */}
      <div style={{ flex: "none", textAlign: "right", minWidth: 90 }}>
        <div style={{ font: "600 9px var(--mono)", letterSpacing: ".1em", color: "var(--fg2)" }}>
          DETERMINISM
        </div>
        <div style={{ font: "700 22px var(--mono)", color: "var(--pass)", marginTop: 1 }}>
          {determinism}
        </div>
        <div
          style={{
            font: "600 9px var(--mono)",
            letterSpacing: ".1em",
            color: "var(--fg2)",
            marginTop: 8,
          }}
        >
          CONFIDENCE
        </div>
        <div
          style={{
            font: "700 16px var(--mono)",
            color: needsReview ? "var(--warn)" : "var(--pass)",
            marginTop: 1,
          }}
        >
          {confidencePct}%
        </div>
      </div>
    </div>
  );
}
