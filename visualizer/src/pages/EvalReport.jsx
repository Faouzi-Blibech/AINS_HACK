import { useEffect, useState } from "react";
import { getEval } from "../api/client.js";

function SkeletonCard() {
  return (
    <div
      style={{
        background: "var(--bg1)",
        border: "1px solid var(--bd)",
        borderRadius: 16,
        padding: "24px 22px",
        display: "flex",
        flexDirection: "column",
        gap: 14,
      }}
    >
      {[120, 60, 180].map((w, i) => (
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

function formatValue(value, unit) {
  if (value === null || value === undefined) return null;
  if (unit === "fraction") return Math.round(value * 100) + "%";
  if (unit === "count") return String(Math.round(value));
  return String(value);
}

function PassChip({ passed }) {
  if (passed === true) {
    return (
      <span
        style={{
          font: "700 9px var(--mono)",
          letterSpacing: ".12em",
          color: "var(--pass)",
          background: "var(--pass-dim)",
          border: "1px solid rgba(70,217,138,.28)",
          borderRadius: 7,
          padding: "3px 9px",
          flex: "none",
        }}
      >
        PASS
      </span>
    );
  }
  if (passed === false) {
    return (
      <span
        style={{
          font: "700 9px var(--mono)",
          letterSpacing: ".12em",
          color: "var(--fail)",
          background: "var(--fail-dim)",
          border: "1px solid rgba(255,107,107,.28)",
          borderRadius: 7,
          padding: "3px 9px",
          flex: "none",
        }}
      >
        FAIL
      </span>
    );
  }
  return (
    <span
      style={{
        font: "700 9px var(--mono)",
        letterSpacing: ".12em",
        color: "var(--fg2)",
        background: "var(--bg3)",
        border: "1px solid var(--bd2)",
        borderRadius: 7,
        padding: "3px 9px",
        flex: "none",
      }}
    >
      N/A
    </span>
  );
}

function MetricCard({ metric }) {
  const displayValue = formatValue(metric.value, metric.unit);
  const valueColor =
    metric.passed === true
      ? "var(--pass)"
      : metric.passed === false
      ? "var(--fail)"
      : "var(--fg2)";

  return (
    <div
      style={{
        background: "var(--bg1)",
        border: "1px solid var(--bd)",
        borderRadius: 16,
        padding: "22px 24px",
        display: "flex",
        flexDirection: "column",
        gap: 14,
        boxShadow: "var(--shadow-sm)",
        animation: "fadeup .25s ease",
      }}
    >
      {/* Card header */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <span
          style={{
            font: "600 9px var(--mono)",
            letterSpacing: ".14em",
            color: "var(--fg2)",
            textTransform: "uppercase",
          }}
        >
          {metric.label}
        </span>
        <PassChip passed={metric.passed} />
      </div>

      {/* Value */}
      <div
        style={{
          font: "700 36px var(--mono)",
          letterSpacing: "-.03em",
          color: valueColor,
          lineHeight: 1,
        }}
      >
        {displayValue !== null ? (
          displayValue
        ) : (
          <span
            style={{
              font: "450 14px var(--ui)",
              color: "var(--fg2)",
              letterSpacing: 0,
            }}
          >
            unavailable
          </span>
        )}
      </div>

      {/* Target */}
      <div
        style={{
          font: "450 11.5px var(--ui)",
          color: "var(--fg2)",
          lineHeight: 1.5,
        }}
      >
        <span
          style={{
            font: "600 9px var(--mono)",
            letterSpacing: ".1em",
            color: "var(--fg2)",
            marginRight: 6,
          }}
        >
          TARGET
        </span>
        {metric.target_text}
      </div>
    </div>
  );
}

export default function EvalReport() {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getEval()
      .then((data) => setReport(data))
      .catch((err) => setError(err.message ?? "Failed to load evaluation results."))
      .finally(() => setLoading(false));
  }, []);

  const metrics = report?.metrics ?? [];
  const metricCount = metrics.length;

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
            Evaluation
          </h1>
          {!loading && !error && report?.available && metricCount > 0 && (
            <span
              style={{
                font: "500 11px var(--mono)",
                color: "var(--accent)",
                background: "var(--accent-dim)",
                border: "1px solid var(--accent-bd)",
                borderRadius: 6,
                padding: "1px 8px",
              }}
            >
              {metricCount}
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
          Automated metric scores measured against defined targets.
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
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
            gap: 14,
          }}
        >
          {[0, 1, 2, 3].map((i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      )}

      {/* Not run yet empty state */}
      {!loading && !error && report?.available === false && (
        <div
          style={{
            background: "var(--bg1)",
            border: "1px solid var(--bd)",
            borderRadius: 16,
            padding: "56px 24px",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 14,
            color: "var(--fg2)",
            font: "450 13px var(--ui)",
            textAlign: "center",
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
            <circle cx="10" cy="10" r="7.5" />
            <path d="M7 10l2 2 4-4" />
          </svg>
          <div>
            <div
              style={{
                font: "550 14px var(--ui)",
                color: "var(--fg1)",
                marginBottom: 6,
              }}
            >
              Evaluation has not been run yet.
            </div>
            <code
              style={{
                font: "450 12px var(--mono)",
                color: "var(--fg2)",
                background: "var(--bg2)",
                border: "1px solid var(--bd)",
                borderRadius: 8,
                padding: "4px 10px",
              }}
            >
              python -m eval.harness
            </code>
            <div
              style={{
                marginTop: 8,
                font: "450 12px var(--ui)",
                color: "var(--fg2)",
              }}
            >
              to generate results.
            </div>
          </div>
        </div>
      )}

      {/* Metric cards grid */}
      {!loading && !error && report?.available && metrics.length > 0 && (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
              gap: 14,
              marginBottom: 28,
            }}
          >
            {metrics.map((metric) => (
              <MetricCard key={metric.key} metric={metric} />
            ))}
          </div>

          {/* Caveats */}
          {report.caveats && report.caveats.length > 0 && (
            <div
              style={{
                background: "var(--bg1)",
                border: "1px solid var(--bd)",
                borderRadius: 14,
                padding: "16px 20px",
                marginBottom: 14,
              }}
            >
              <div
                style={{
                  font: "600 9px var(--mono)",
                  letterSpacing: ".14em",
                  color: "var(--warn)",
                  marginBottom: 10,
                }}
              >
                CAVEATS
              </div>
              <ul
                style={{
                  margin: 0,
                  padding: "0 0 0 18px",
                  display: "flex",
                  flexDirection: "column",
                  gap: 5,
                }}
              >
                {report.caveats.map((c, i) => (
                  <li
                    key={i}
                    style={{
                      font: "450 12px var(--ui)",
                      color: "var(--fg2)",
                      lineHeight: 1.55,
                    }}
                  >
                    {c}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Generated at */}
          {report.generated_at && (
            <div
              style={{
                font: "450 11px var(--mono)",
                color: "var(--fg2)",
              }}
            >
              Generated: {report.generated_at}
            </div>
          )}
        </>
      )}
    </div>
  );
}
