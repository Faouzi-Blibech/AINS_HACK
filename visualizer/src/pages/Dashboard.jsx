import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import StatusBadge from "../components/StatusBadge.jsx";
import { listRuns } from "../api/client.js";
import { formatTimestamp, truncateRunId } from "../utils/format.js";

function LoadingRows() {
  return Array.from({ length: 5 }).map((_, i) => (
    <tr key={i} style={{ borderBottom: "1px solid var(--bd)" }}>
      {[120, 90, 110, 40, 70].map((w, j) => (
        <td key={j} style={{ padding: "14px 16px" }}>
          <span
            style={{
              display: "inline-block",
              height: 12,
              width: w,
              borderRadius: 6,
              background: "var(--bg3)",
              opacity: 0.6,
            }}
          />
        </td>
      ))}
    </tr>
  ));
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [runs, setRuns] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    listRuns()
      .then((data) => {
        setRuns(data.runs ?? []);
        setTotal(data.total ?? (data.runs ?? []).length);
      })
      .catch((err) => setError(err.message ?? "Failed to load runs."))
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
      <div style={{ marginBottom: 20 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <h1
            style={{
              margin: 0,
              font: "700 22px var(--ui)",
              letterSpacing: "-.02em",
              color: "var(--fg0)",
            }}
          >
            Runs
          </h1>
          {!loading && !error && (
            <span
              style={{
                font: "500 11px var(--mono)",
                color: "var(--fg2)",
                background: "var(--bg3)",
                border: "1px solid var(--bd)",
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
          Recorded agent executions. Select a run to inspect its trace.
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

      {/* Runs table */}
      {!error && (
        <div
          style={{
            background: "var(--bg1)",
            border: "1px solid var(--bd)",
            borderRadius: 16,
            overflow: "hidden",
            boxShadow: "var(--shadow-sm)",
          }}
        >
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              font: "450 13px var(--ui)",
            }}
          >
            <thead>
              <tr
                style={{
                  borderBottom: "1px solid var(--bd)",
                }}
              >
                {["Run ID", "Agent", "Recorded", "Steps", "Status"].map(
                  (col) => (
                    <th
                      key={col}
                      style={{
                        padding: "11px 16px",
                        textAlign: "left",
                        font: "600 9px var(--mono)",
                        letterSpacing: ".12em",
                        color: "var(--fg2)",
                        textTransform: "uppercase",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {col}
                    </th>
                  )
                )}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <LoadingRows />
              ) : runs.length === 0 ? null : (
                runs.map((run) => (
                  <tr
                    key={run.run_id}
                    onClick={() => navigate(`/runs/${run.run_id}`)}
                    style={{
                      borderBottom: "1px solid var(--bd)",
                      cursor: "pointer",
                      transition: "background .12s",
                    }}
                    onMouseEnter={(e) =>
                      (e.currentTarget.style.background = "var(--hover)")
                    }
                    onMouseLeave={(e) =>
                      (e.currentTarget.style.background = "transparent")
                    }
                  >
                    {/* Run ID */}
                    <td style={{ padding: "13px 16px" }}>
                      <span
                        style={{
                          fontFamily: "var(--mono)",
                          fontSize: 12,
                          color: "var(--accent2)",
                          background: "var(--accent-dim)",
                          border: "1px solid var(--accent-bd)",
                          borderRadius: 7,
                          padding: "2px 8px",
                          whiteSpace: "nowrap",
                        }}
                        title={run.run_id}
                      >
                        {truncateRunId(run.run_id)}
                      </span>
                    </td>

                    {/* Agent */}
                    <td
                      style={{
                        padding: "13px 16px",
                        font: "550 13px var(--ui)",
                        color: "var(--fg0)",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {run.agent}
                    </td>

                    {/* Recorded */}
                    <td
                      style={{
                        padding: "13px 16px",
                        font: "450 12px var(--mono)",
                        color: "var(--fg2)",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {formatTimestamp(run.created_at_ms)}
                    </td>

                    {/* Steps */}
                    <td
                      style={{
                        padding: "13px 16px",
                        font: "600 13px var(--mono)",
                        color: "var(--fg1)",
                        textAlign: "center",
                      }}
                    >
                      {run.step_count}
                    </td>

                    {/* Status */}
                    <td style={{ padding: "13px 16px" }}>
                      <StatusBadge status={run.status} />
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>

          {/* Empty state inside card */}
          {!loading && runs.length === 0 && (
            <div
              style={{
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
                width="36"
                height="36"
                viewBox="0 0 20 20"
                fill="none"
                stroke="var(--bd3)"
                strokeWidth="1.4"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <rect x="3" y="3" width="14" height="14" rx="3" />
                <path d="M7 10h6M10 7v6" />
              </svg>
              <span>No recorded runs yet.</span>
            </div>
          )}
        </div>
      )}

      {/* Chevron column helper: spacer for arrow */}
      {!loading && !error && runs.length > 0 && (
        <p
          style={{
            margin: "10px 0 0",
            font: "450 11px var(--mono)",
            color: "var(--fg2)",
            textAlign: "right",
          }}
        >
          {total} run{total !== 1 ? "s" : ""} total
        </p>
      )}
    </div>
  );
}
