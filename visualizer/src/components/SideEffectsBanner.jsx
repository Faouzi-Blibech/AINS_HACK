// SideEffectsBanner -- green safety guarantee banner.
// "Side effects contained · 0 · nothing sent · replay is hermetic"

export default function SideEffectsBanner() {
  return (
    <div
      style={{
        margin: "14px 24px 0",
        padding: "10px 16px",
        border: "1px solid var(--pass)",
        background: "var(--pass-dim)",
        borderRadius: 12,
        display: "flex",
        alignItems: "center",
        gap: 13,
      }}
    >
      {/* Green dot */}
      <span
        style={{
          width: 9,
          height: 9,
          borderRadius: "50%",
          background: "var(--pass)",
          boxShadow: "0 0 0 3px var(--pass-dim)",
          flex: "none",
          display: "block",
        }}
      />
      <span
        style={{
          font: "600 9px var(--mono)",
          letterSpacing: ".1em",
          color: "var(--pass)",
          flex: "none",
          whiteSpace: "nowrap",
        }}
      >
        CONTAINED
      </span>
      <span
        style={{
          font: "450 12px var(--ui)",
          color: "var(--fg1)",
          whiteSpace: "nowrap",
        }}
      >
        Side effects contained &middot; 0 &middot; nothing sent &middot; replay is hermetic
      </span>
    </div>
  );
}
