// MetricBar + MetricCard: top header metric cards wired to /metrics.
// Falls back to placeholder values if the fetch fails.

import { useEffect, useState } from "react";
import { getMetrics } from "../api/client.js";

// Fallback static values shown while loading or on error.
const FALLBACK = {
  runs_24h: 18,
  pass_rate: 0.67,
  contained_pct: 100,
  determinism_rate: 1.0,
};

function buildMetrics(data) {
  return [
    {
      label: "RUNS · 24H",
      value: String(data.runs_24h),
      color: "var(--accent)",
      pts: "0,18 8,12 16,15 24,8 32,11 40,5 48,9",
    },
    {
      label: "PASS RATE",
      value: Math.round(data.pass_rate * 100) + "%",
      color: "var(--pass)",
      pts: "0,14 8,10 16,16 24,8 32,12 40,6 48,10",
    },
    {
      label: "CONTAINED",
      value: data.contained_pct + "%",
      color: "var(--accent)",
      pts: "0,20 8,18 16,20 24,18 32,20 40,18 48,20",
    },
    {
      label: "DETERMINISM",
      value: Math.round(data.determinism_rate * 100) + "%",
      color: "var(--accent)",
      pts: "0,20 8,18 16,20 24,18 32,20 40,18 48,20",
    },
  ];
}

function MetricCard({ label, value, color, pts }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 11,
        background: "var(--bg2)",
        border: "1px solid var(--bd)",
        borderRadius: 12,
        padding: "8px 13px",
        minWidth: 0,
      }}
    >
      <div>
        <div
          style={{
            font: "600 8.5px var(--mono)",
            letterSpacing: ".1em",
            color: "var(--fg2)",
            whiteSpace: "nowrap",
          }}
        >
          {label}
        </div>
        <div
          style={{
            font: "700 16px var(--mono)",
            letterSpacing: "-.02em",
            color,
            lineHeight: 1.1,
            marginTop: 1,
          }}
        >
          {value}
        </div>
      </div>
      <svg
        width="48"
        height="22"
        viewBox="0 0 48 22"
        style={{ flex: "none", overflow: "visible" }}
      >
        <polyline
          points={pts}
          fill="none"
          stroke={color}
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
          opacity=".8"
        />
      </svg>
    </div>
  );
}

export default function MetricBar({ pageTitle, pageSub, onThemeToggle, theme }) {
  const [metrics, setMetrics] = useState(() => buildMetrics(FALLBACK));

  useEffect(() => {
    let cancelled = false;
    getMetrics()
      .then((data) => {
        if (!cancelled) setMetrics(buildMetrics(data));
      })
      .catch(() => {
        // keep fallback; MetricBar must be resilient
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <header
      style={{
        height: 68,
        borderBottom: "1px solid var(--bd)",
        background: "var(--bg1)",
        display: "flex",
        alignItems: "center",
        gap: 18,
        padding: "0 24px",
        flex: "none",
      }}
    >
      <div style={{ flex: "none" }}>
        <div
          style={{
            font: "600 14.5px var(--ui)",
            letterSpacing: "-.01em",
            color: "var(--fg0)",
          }}
        >
          {pageTitle || "Execution trace"}
        </div>
        <div
          style={{
            font: "450 11px var(--mono)",
            color: "var(--fg2)",
            marginTop: 1,
          }}
        >
          {pageSub || "RUN-7f3a · triage-agent"}
        </div>
      </div>

      <div
        style={{
          marginLeft: "auto",
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        {metrics.map((m) => (
          <MetricCard key={m.label} {...m} />
        ))}

        {/* Theme toggle */}
        <button
          onClick={onThemeToggle}
          title="Toggle theme"
          style={{
            width: 40,
            height: 40,
            flex: "none",
            background: "var(--bg2)",
            border: "1px solid var(--bd)",
            borderRadius: 11,
            cursor: "pointer",
            color: "var(--fg1)",
            display: "grid",
            placeItems: "center",
          }}
        >
          {theme === "dark" ? (
            <svg
              width="17"
              height="17"
              viewBox="0 0 20 20"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="10" cy="10" r="3.5" />
              <path d="M10 1v2M10 17v2M1 10h2M17 10h2M3.5 3.5l1.4 1.4M15.1 15.1l1.4 1.4M3.5 16.5l1.4-1.4M15.1 4.9l1.4-1.4" />
            </svg>
          ) : (
            <svg
              width="17"
              height="17"
              viewBox="0 0 20 20"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M17.5 12.5A7.5 7.5 0 017.5 2.5a7.5 7.5 0 100 15 7.5 7.5 0 0010-5z" />
            </svg>
          )}
        </button>
      </div>
    </header>
  );
}
