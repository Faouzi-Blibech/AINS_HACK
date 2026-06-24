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
      : "var(--fg0)";

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

// --- Dashboard pieces -------------------------------------------------------

function HeroTile({ label, value, sub, color, accent }) {
  return (
    <div style={{ flex: "1 1 180px", minWidth: 150 }}>
      <div
        style={{
          font: "600 9px var(--mono)",
          letterSpacing: ".14em",
          color: "var(--fg2)",
          textTransform: "uppercase",
        }}
      >
        {label}
      </div>
      <div
        style={{
          font: "700 32px var(--mono)",
          letterSpacing: "-.03em",
          color: color || "var(--fg0)",
          lineHeight: 1.05,
          marginTop: 6,
        }}
      >
        {value}
      </div>
      {sub && (
        <div
          style={{
            font: "450 11px var(--ui)",
            color: accent || "var(--fg2)",
            marginTop: 4,
          }}
        >
          {sub}
        </div>
      )}
    </div>
  );
}

function HeroScorecard({ byKey }) {
  const runs = byKey.runs_evaluated;
  const det = byKey.determinism_rate;
  const intercepted = byKey.side_effecting_intercepted;
  const executed = byKey.side_effect_containment;
  const rel = byKey.ai_reliability;

  return (
    <div
      style={{
        background:
          "linear-gradient(180deg, var(--bg2), var(--bg1))",
        border: "1px solid var(--accent-bd)",
        borderRadius: 18,
        padding: "22px 26px",
        marginBottom: 26,
        display: "flex",
        flexWrap: "wrap",
        gap: 24,
        boxShadow: "var(--glow)",
        animation: "fadeup .25s ease",
      }}
    >
      <HeroTile
        label="Runs evaluated"
        value={runs ? formatValue(runs.value, "count") : "0"}
        sub="primary runs, forks excluded"
      />
      <HeroTile
        label="Deterministic replay"
        value={det ? formatValue(det.value, "fraction") : "n/a"}
        color="var(--pass)"
        sub="reproduced via real replay"
        accent="var(--pass)"
      />
      <HeroTile
        label="Side-effects contained"
        value={
          intercepted ? formatValue(intercepted.value, "count") : "0"
        }
        color="var(--accent2)"
        sub={`intercepted · ${
          executed ? formatValue(executed.value, "count") : "0"
        } executed live`}
        accent="var(--accent2)"
      />
      <HeroTile
        label="AI reliability"
        value={rel ? formatValue(rel.value, "fraction") : "n/a"}
        color="var(--pass)"
        sub="correct on repeat runs"
        accent="var(--pass)"
      />
    </div>
  );
}

function SectionHeading({ children }) {
  return (
    <h2
      style={{
        margin: "0 0 12px",
        font: "600 10px var(--mono)",
        letterSpacing: ".16em",
        color: "var(--fg2)",
        textTransform: "uppercase",
      }}
    >
      {children}
    </h2>
  );
}

function MetricGrid({ metrics }) {
  if (!metrics.length) return null;
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
        gap: 14,
        marginBottom: 26,
      }}
    >
      {metrics.map((m) => (
        <MetricCard key={m.key} metric={m} />
      ))}
    </div>
  );
}

const CHECK_LABELS = {
  debug_agent: "Debug agent (NL → injection)",
  blame_verdict: "Blame verdict (root cause)",
  counterfactual: "Counterfactual repair",
  semantic_matcher: "Semantic matcher",
};

function ReliabilityBreakdown({ checks }) {
  if (!checks || !checks.length) return null;
  return (
    <div style={{ marginBottom: 26 }}>
      <SectionHeading>AI reliability &mdash; consistency across repeat runs</SectionHeading>
      <div
        style={{
          background: "var(--bg1)",
          border: "1px solid var(--bd)",
          borderRadius: 16,
          padding: "20px 22px",
          display: "flex",
          flexDirection: "column",
          gap: 16,
          boxShadow: "var(--shadow-sm)",
          animation: "fadeup .25s ease",
        }}
      >
        {checks.map((c) => {
          const pct = c.rate != null ? Math.round(c.rate * 100) : null;
          const good = c.rate != null && c.rate >= 0.9;
          return (
            <div key={c.check}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "baseline",
                  marginBottom: 6,
                  gap: 12,
                }}
              >
                <span
                  style={{
                    font: "500 12.5px var(--ui)",
                    color: "var(--fg1)",
                  }}
                >
                  {CHECK_LABELS[c.check] || c.check}
                </span>
                <span
                  style={{
                    font: "700 12px var(--mono)",
                    color: good ? "var(--pass)" : "var(--warn)",
                  }}
                >
                  {pct != null ? pct + "%" : "n/a"}
                  <span
                    style={{
                      font: "450 10px var(--mono)",
                      color: "var(--fg2)",
                      marginLeft: 8,
                    }}
                  >
                    {c.correct}/{c.total}
                    {c.errored ? ` · ${c.errored} excl.` : ""}
                  </span>
                </span>
              </div>
              <div
                style={{
                  height: 7,
                  borderRadius: 99,
                  background: "var(--bg3)",
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    height: "100%",
                    width: (pct != null ? pct : 0) + "%",
                    borderRadius: 99,
                    background: good ? "var(--pass)" : "var(--warn)",
                    transition: "width .4s ease",
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// --- Page -------------------------------------------------------------------

const SAFETY_KEYS = [
  "runs_evaluated",
  "pass_rate",
  "determinism_rate",
  "side_effect_containment",
  "side_effecting_intercepted",
  "avg_steps",
];
const QUALITY_KEYS = [
  "semantic_match_precision",
  "semantic_match_recall",
  "root_cause_accuracy",
  "ai_reliability",
];

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
  const byKey = Object.fromEntries(metrics.map((m) => [m.key, m]));
  const order = (keys) =>
    keys.map((k) => byKey[k]).filter(Boolean);
  const safetyMetrics = order(SAFETY_KEYS);
  const qualityMetrics = order(QUALITY_KEYS);
  // Any metric not in either group still shows under Replay & Safety.
  const known = new Set([...SAFETY_KEYS, ...QUALITY_KEYS]);
  const extra = metrics.filter((m) => !known.has(m.key));

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
        <p
          style={{
            margin: "5px 0 0",
            font: "450 12.5px var(--ui)",
            color: "var(--fg2)",
          }}
        >
          Live replay-and-safety metrics plus AI-quality metrics from the test set.
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
            gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
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

      {/* Dashboard */}
      {!loading && !error && report?.available && metrics.length > 0 && (
        <>
          <HeroScorecard byKey={byKey} />

          {(safetyMetrics.length > 0 || extra.length > 0) && (
            <>
              <SectionHeading>Replay &amp; safety &mdash; live from recorded runs</SectionHeading>
              <MetricGrid metrics={[...safetyMetrics, ...extra]} />
            </>
          )}

          {qualityMetrics.length > 0 && (
            <>
              <SectionHeading>AI quality &mdash; from the synthetic test set</SectionHeading>
              <MetricGrid metrics={qualityMetrics} />
            </>
          )}

          <ReliabilityBreakdown checks={report.reliability_checks} />

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
