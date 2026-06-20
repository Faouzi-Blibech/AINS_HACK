const STATUS_CONFIG = {
  ok: {
    color: "var(--pass)",
    bg: "var(--pass-dim)",
    border: "rgba(70, 217, 138, .28)",
  },
  error: {
    color: "var(--fail)",
    bg: "var(--fail-dim)",
    border: "rgba(255, 107, 107, .26)",
  },
  timeout: {
    color: "var(--warn)",
    bg: "var(--warn-dim)",
    border: "rgba(255, 180, 84, .28)",
  },
  aborted: {
    color: "var(--fg2)",
    bg: "var(--bg3)",
    border: "var(--bd2)",
  },
};

export default function StatusBadge({ status }) {
  const cfg = STATUS_CONFIG[status] ?? STATUS_CONFIG.aborted;

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        borderRadius: 999,
        padding: "3px 9px",
        font: "600 9.5px var(--mono)",
        letterSpacing: ".08em",
        textTransform: "uppercase",
        color: cfg.color,
        background: cfg.bg,
        border: `1px solid ${cfg.border}`,
        whiteSpace: "nowrap",
      }}
    >
      <span
        style={{
          width: 5,
          height: 5,
          borderRadius: "50%",
          background: cfg.color,
          flex: "none",
          opacity: 0.85,
        }}
      />
      {status}
    </span>
  );
}
