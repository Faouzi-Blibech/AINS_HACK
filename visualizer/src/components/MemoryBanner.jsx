// MemoryBanner -- amber banner shown when a run semantically matches a prior
// failure pattern (from /runs/{id}/memory). The match is by meaning, ranked by
// the AI, not by step number.
// Props:
//   entry     -- MemoryMatch { id, failure_pattern, fix_that_worked, blame_step, score }
//   label     -- display id, e.g. "FM-014"
//   score     -- 0..1 relevance score
//   rationale -- one-line explanation of why it matched

export default function MemoryBanner({ entry, label, score, rationale }) {
  if (!entry) return null;

  const displayLabel = label ?? "FM-000";
  const pattern = entry.failure_pattern ?? "";
  const fix = entry.fix_that_worked ?? "";
  const pct = score != null ? Math.round(score * 100) + "%" : null;

  return (
    <div
      style={{
        margin: "14px 24px 0",
        padding: "13px 16px",
        border: "1px solid var(--warn)",
        background: "var(--warn-dim)",
        borderRadius: 14,
        display: "flex",
        alignItems: "flex-start",
        gap: 13,
        animation: "fadeup .3s ease",
      }}
    >
      <span
        style={{
          font: "600 9px var(--mono)",
          letterSpacing: ".08em",
          color: "var(--warn)",
          border: "1px solid var(--warn)",
          borderRadius: 6,
          padding: "3px 7px",
          flex: "none",
          whiteSpace: "nowrap",
          marginTop: 1,
        }}
      >
        MEMORY
      </span>
      <div style={{ font: "450 12.5px var(--ui)", color: "var(--fg0)", lineHeight: 1.55 }}>
        Cassette has seen a similar failure before:{" "}
        <b style={{ fontWeight: 600 }}>{displayLabel}</b>
        {pct && (
          <span
            style={{
              font: "600 10px var(--mono)",
              color: "var(--warn)",
              marginLeft: 6,
            }}
          >
            {pct} match
          </span>
        )}
        .{" "}
        <span style={{ color: "var(--fg1)" }}>{pattern}</span>
        <div style={{ marginTop: 4 }}>
          <span style={{ font: "600 10px var(--mono)", color: "var(--fg2)", letterSpacing: ".06em" }}>
            FIX THAT WORKED:{" "}
          </span>
          <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--warn)" }}>
            {fix}
          </span>
        </div>
        {rationale && (
          <div style={{ marginTop: 4, font: "450 11px var(--ui)", color: "var(--fg2)" }}>
            {rationale}
          </div>
        )}
      </div>
    </div>
  );
}
