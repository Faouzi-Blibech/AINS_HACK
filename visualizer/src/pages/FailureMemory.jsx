import { useEffect, useState } from "react";
import { getLibrary } from "../api/client.js";

function SkeletonCard() {
  return (
    <div
      style={{
        background: "var(--bg1)",
        border: "1px solid var(--bd)",
        borderRadius: 16,
        padding: "20px 22px",
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      {[180, 260, 140, 200].map((w, i) => (
        <span
          key={i}
          style={{
            display: "inline-block",
            height: 12,
            width: w,
            borderRadius: 6,
            background: "var(--bg3)",
            opacity: 0.55,
          }}
        />
      ))}
    </div>
  );
}

function MemoryCard({ entry, index }) {
  const label = entry.id ?? `FM-${String(index + 1).padStart(3, "0")}`;
  const detRate =
    entry.determinism_rate != null
      ? `${Math.round(entry.determinism_rate * 100)}%`
      : null;

  return (
    <div
      style={{
        background: "var(--bg1)",
        border: "1px solid var(--warn)",
        borderRadius: 16,
        padding: "20px 22px",
        display: "flex",
        flexDirection: "column",
        gap: 14,
        boxShadow: "var(--shadow-sm)",
        animation: "fadeup .25s ease",
      }}
    >
      {/* Card header row */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {/* FM label badge */}
          <span
            style={{
              font: "600 9px var(--mono)",
              letterSpacing: ".1em",
              color: "var(--warn)",
              border: "1px solid var(--warn)",
              borderRadius: 7,
              padding: "3px 8px",
              flex: "none",
              background: "var(--warn-dim)",
            }}
          >
            {label}
          </span>

          {/* Blame step chip */}
          {entry.blame_step != null && (
            <span
              style={{
                font: "500 10px var(--mono)",
                color: "var(--fg2)",
                background: "var(--bg3)",
                border: "1px solid var(--bd2)",
                borderRadius: 6,
                padding: "2px 8px",
                flex: "none",
              }}
            >
              blame: step {entry.blame_step}
            </span>
          )}
        </div>

        {/* Determinism rate */}
        {detRate && (
          <div style={{ textAlign: "right", flex: "none" }}>
            <div
              style={{
                font: "600 8.5px var(--mono)",
                letterSpacing: ".1em",
                color: "var(--fg2)",
              }}
            >
              DETERMINISM
            </div>
            <div
              style={{
                font: "700 18px var(--mono)",
                letterSpacing: "-.02em",
                color:
                  entry.determinism_rate >= 0.8
                    ? "var(--pass)"
                    : entry.determinism_rate >= 0.5
                    ? "var(--warn)"
                    : "var(--fail)",
                lineHeight: 1.1,
                marginTop: 2,
              }}
            >
              {detRate}
            </div>
          </div>
        )}
      </div>

      {/* Failure pattern */}
      <div>
        <div
          style={{
            font: "600 9px var(--mono)",
            letterSpacing: ".12em",
            color: "var(--fg2)",
            marginBottom: 5,
          }}
        >
          FAILURE PATTERN
        </div>
        <div
          style={{
            font: "550 14px var(--ui)",
            color: "var(--fg0)",
            lineHeight: 1.5,
          }}
        >
          {entry.failure_pattern}
        </div>
      </div>

      {/* Fix that worked */}
      {entry.fix_that_worked && (
        <div
          style={{
            background: "var(--warn-dim)",
            border: "1px solid rgba(255,180,84,.22)",
            borderRadius: 11,
            padding: "11px 14px",
          }}
        >
          <div
            style={{
              font: "600 9px var(--mono)",
              letterSpacing: ".12em",
              color: "var(--warn)",
              marginBottom: 5,
            }}
          >
            FIX THAT WORKED
          </div>
          <div
            style={{
              font: "450 12.5px var(--ui)",
              color: "var(--fg1)",
              lineHeight: 1.55,
            }}
          >
            {entry.fix_that_worked}
          </div>
        </div>
      )}

      {/* Agent config */}
      {entry.agent_config && (
        <div>
          <div
            style={{
              font: "600 9px var(--mono)",
              letterSpacing: ".12em",
              color: "var(--fg2)",
              marginBottom: 5,
            }}
          >
            AGENT CONFIG
          </div>
          <code
            style={{
              display: "block",
              fontFamily: "var(--mono)",
              fontSize: 11.5,
              color: "var(--accent2)",
              background: "var(--bg2)",
              border: "1px solid var(--bd)",
              borderRadius: 9,
              padding: "8px 12px",
              whiteSpace: "pre-wrap",
              wordBreak: "break-all",
              lineHeight: 1.6,
            }}
          >
            {typeof entry.agent_config === "string"
              ? entry.agent_config
              : JSON.stringify(entry.agent_config, null, 2)}
          </code>
        </div>
      )}
    </div>
  );
}

export default function FailureMemory() {
  const [entries, setEntries] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getLibrary()
      .then((data) => {
        setEntries(data.entries ?? []);
        setTotal(data.total ?? (data.entries ?? []).length);
      })
      .catch((err) => setError(err.message ?? "Failed to load failure library."))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div
      style={{
        flex: 1,
        overflowY: "auto",
        overflowX: "hidden",
        padding: "28px 28px 48px",
      }}
    >
      {/* Page header */}
      <div style={{ marginBottom: 22 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <h1
            style={{
              margin: 0,
              font: "700 22px var(--ui)",
              letterSpacing: "-.02em",
              color: "var(--fg0)",
            }}
          >
            Failure memory
          </h1>
          {!loading && !error && (
            <span
              style={{
                font: "500 11px var(--mono)",
                color: "var(--warn)",
                background: "var(--warn-dim)",
                border: "1px solid rgba(255,180,84,.28)",
                borderRadius: 6,
                padding: "1px 8px",
              }}
            >
              {total}
            </span>
          )}
        </div>
        <p
          style={{
            margin: "5px 0 0",
            font: "450 12.5px var(--ui)",
            color: "var(--fg2)",
          }}
        >
          Recorded failure patterns Cassette can inject as preventive warnings.
        </p>
      </div>

      {/* Error state */}
      {error && (
        <div
          style={{
            background: "var(--fail-dim)",
            border: "1px solid var(--fail)",
            borderRadius: 14,
            padding: "16px 20px",
            font: "450 13px var(--ui)",
            color: "var(--fail)",
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M8 1.5l6.5 11.5H1.5z" />
            <path d="M8 6.5v3" />
            <circle cx="8" cy="11.5" r=".75" fill="currentColor" />
          </svg>
          {error}
        </div>
      )}

      {/* Loading skeletons */}
      {loading && (
        <div
          style={{ display: "flex", flexDirection: "column", gap: 14 }}
        >
          {[0, 1, 2].map((i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && entries.length === 0 && (
        <div
          style={{
            background: "var(--bg1)",
            border: "1px solid var(--bd)",
            borderRadius: 16,
            padding: "56px 24px",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 12,
            color: "var(--fg2)",
            font: "450 13px var(--ui)",
          }}
        >
          <svg
            width="40"
            height="40"
            viewBox="0 0 20 20"
            fill="none"
            stroke="var(--bd3)"
            strokeWidth="1.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M10 2a5 5 0 00-3.5 8.5L3 14h14l-3.5-3.5A5 5 0 0010 2z" />
          </svg>
          <span>No failure patterns recorded yet.</span>
        </div>
      )}

      {/* Memory cards grid */}
      {!loading && !error && entries.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {entries.map((entry, idx) => (
            <MemoryCard key={idx} entry={entry} index={idx} />
          ))}
        </div>
      )}
    </div>
  );
}
