// MemoryBanner -- amber banner shown when the current run matched a failure-memory pattern.
// Props:
//   entry  -- FailureLibraryEntry object (or null/undefined to hide)
//   label  -- display id, e.g. "FM-014"

export default function MemoryBanner({ entry, label }) {
  if (!entry) return null;

  const displayLabel = label ?? "FM-000";
  const warningText = entry.fix_that_worked ?? entry.failure_pattern ?? "";

  return (
    <div
      style={{
        margin: "14px 24px 0",
        padding: "13px 16px",
        border: "1px solid var(--warn)",
        background: "var(--warn-dim)",
        borderRadius: 14,
        display: "flex",
        alignItems: "center",
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
        }}
      >
        MEMORY
      </span>
      <div style={{ font: "450 12.5px var(--ui)", color: "var(--fg0)", lineHeight: 1.5 }}>
        This run matched failure pattern{" "}
        <b style={{ fontWeight: 600 }}>{displayLabel}</b>. Cassette injected a preventive warning:{" "}
        <span
          style={{
            fontFamily: "var(--mono)",
            fontSize: 11,
            color: "var(--warn)",
          }}
        >
          &ldquo;{warningText}&rdquo;
        </span>
      </div>
    </div>
  );
}
