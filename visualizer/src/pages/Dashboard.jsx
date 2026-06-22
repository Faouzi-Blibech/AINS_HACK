import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listRuns, getLibrary, getBlame } from "../api/client.js";
import { formatTimestamp, truncateRunId } from "../utils/format.js";

function LoadingRows() {
  return Array.from({ length: 5 }).map((_, i) => (
    <div
      key={i}
      style={{
        display: "grid",
        gridTemplateColumns: "106px minmax(150px,1.5fr) 104px 86px 116px 62px",
        gap: 0,
        alignItems: "center",
        padding: "14px 16px",
        borderBottom: "1px solid var(--bd)",
      }}
    >
      {[80, 120, 90, 60, 70, 40].map((w, j) => (
        <div key={j}>
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
        </div>
      ))}
    </div>
  ));
}

const FILTER_ALL = "all";
const FILTER_PASS = "ok";
const FILTER_FAIL = "error";

export default function Dashboard() {
  const navigate = useNavigate();
  const [runs, setRuns] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  // Set of run_ids that have a real failure-library match
  const [fmMatchedIds, setFmMatchedIds] = useState(new Set());
  // Map from run_id to matched library entry id (for tooltip)
  const [fmMatchLabels, setFmMatchLabels] = useState({});

  // Filter + search state
  const [activeFilter, setActiveFilter] = useState(FILTER_ALL);
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    setLoading(true);
    setError(null);
    setFmMatchedIds(new Set());
    setFmMatchLabels({});

    listRuns()
      .then((data) => {
        const runList = data.runs ?? [];
        setRuns(runList);
        setTotal(data.total ?? runList.length);

        // For error runs, fetch library and blame to determine real FM matches.
        // If anything fails, silently show no marker rather than crashing.
        const errorRuns = runList.filter((r) => r.status === "error");
        if (errorRuns.length === 0) return;

        getLibrary()
          .catch(() => null)
          .then((libraryData) => {
            if (!libraryData?.entries?.length) return;
            const entries = libraryData.entries;

            Promise.all(
              errorRuns.map((r) =>
                getBlame(r.run_id)
                  .catch(() => null)
                  .then((blame) => ({ run_id: r.run_id, blame }))
              )
            ).then((results) => {
              const matched = new Set();
              const labels = {};
              for (const { run_id, blame } of results) {
                if (!blame?.root_cause_step_id) continue;
                const entry = entries.find(
                  (e) => e.blame_step === blame.root_cause_step_id
                );
                if (entry) {
                  matched.add(run_id);
                  labels[run_id] = entry.id ?? null;
                }
              }
              setFmMatchedIds(matched);
              setFmMatchLabels(labels);
            });
          });
      })
      .catch((err) => setError(err.message ?? "Failed to load runs."))
      .finally(() => setLoading(false));
  }, []);

  // Derived counts from real data
  const countAll = runs.length;
  const countPass = runs.filter((r) => r.status === "ok").length;
  const countFail = runs.filter((r) => r.status === "error").length;

  // Compose filter + search
  const filteredRuns = runs.filter((r) => {
    const matchesFilter =
      activeFilter === FILTER_ALL ||
      r.status === activeFilter;
    const q = searchQuery.trim().toLowerCase();
    const matchesSearch =
      q === "" ||
      (r.run_id ?? "").toLowerCase().includes(q) ||
      (r.agent ?? "").toLowerCase().includes(q);
    return matchesFilter && matchesSearch;
  });

  const filterTabs = [
    { key: FILTER_ALL, label: "All", count: countAll },
    { key: FILTER_PASS, label: "Succeeded", count: countPass },
    { key: FILTER_FAIL, label: "Failed", count: countFail },
  ];

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
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 20 }}>
          <div>
            <h1
              style={{
                margin: 0,
                font: "600 21px var(--ui)",
                letterSpacing: "-.01em",
                color: "var(--fg0)",
              }}
            >
              Recorded runs
            </h1>
            <p
              style={{
                margin: "5px 0 0",
                font: "450 12.5px var(--ui)",
                color: "var(--fg1)",
              }}
            >
              Every agent trajectory, captured to tape and replayable with zero live calls.
            </p>
          </div>
          <div style={{ display: "flex", gap: 9, alignItems: "center" }}>
            {/* Search input */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 7,
                background: "var(--bg2)",
                border: "1px solid var(--bd)",
                borderRadius: 9,
                padding: "7px 11px",
                width: 230,
              }}
            >
              <svg
                width="13"
                height="13"
                viewBox="0 0 16 16"
                style={{ flex: "none", color: "var(--fg2)" }}
              >
                <circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" strokeWidth="1.5" />
                <path d="M11 11l3.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search runs, agents, ids..."
                style={{
                  border: "none",
                  outline: "none",
                  background: "transparent",
                  font: "450 12px var(--ui)",
                  color: "var(--fg0)",
                  width: "100%",
                }}
              />
            </div>
            {!loading && !error && (
              <span
                style={{
                  font: "500 11px var(--mono)",
                  color: "var(--fg2)",
                  background: "var(--bg3)",
                  border: "1px solid var(--bd)",
                  borderRadius: 6,
                  padding: "1px 8px",
                  whiteSpace: "nowrap",
                }}
              >
                {total} run{total !== 1 ? "s" : ""}
              </span>
            )}
          </div>
        </div>

        {/* Filter tabs */}
        {!loading && !error && (
          <div style={{ display: "flex", gap: 7, marginTop: 14 }}>
            {filterTabs.map((tab) => {
              const active = activeFilter === tab.key;
              return (
                <button
                  key={tab.key}
                  onClick={() => setActiveFilter(tab.key)}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 0,
                    padding: "5px 13px",
                    borderRadius: 8,
                    border: active ? "1px solid var(--accent)" : "1px solid var(--bd)",
                    background: active ? "var(--accent-dim)" : "var(--bg2)",
                    color: active ? "var(--accent)" : "var(--fg1)",
                    font: "500 12.5px var(--ui)",
                    cursor: "pointer",
                    transition: "background 0.12s, color 0.12s, border-color 0.12s",
                  }}
                  onMouseEnter={(e) => {
                    if (!active) {
                      e.currentTarget.style.background = "var(--hover)";
                      e.currentTarget.style.color = "var(--fg0)";
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (!active) {
                      e.currentTarget.style.background = "var(--bg2)";
                      e.currentTarget.style.color = "var(--fg1)";
                    }
                  }}
                >
                  {tab.label}
                  <span
                    style={{
                      opacity: 0.55,
                      marginLeft: 6,
                      fontFamily: "var(--mono)",
                      fontSize: 10,
                    }}
                  >
                    {tab.count}
                  </span>
                </button>
              );
            })}
          </div>
        )}
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

      {/* Runs grid */}
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
          {/* Column header row */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "106px minmax(150px,1.5fr) 104px 86px 116px 62px",
              gap: 0,
              alignItems: "center",
              padding: "13px 16px",
              font: "600 9.5px var(--mono)",
              letterSpacing: ".1em",
              color: "var(--fg2)",
              position: "sticky",
              top: 0,
              background: "var(--bg0)",
              borderBottom: "1px solid var(--bd)",
              zIndex: 2,
            }}
          >
            <div>RUN ID</div>
            <div>AGENT</div>
            <div>RECORDED</div>
            <div>OUTCOME</div>
            <div>MODE</div>
            <div>STEPS</div>
          </div>

          {/* Rows */}
          {loading ? (
            <LoadingRows />
          ) : filteredRuns.length === 0 ? (
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
              <span>
                {runs.length === 0
                  ? "No recorded runs yet."
                  : "No runs match your current filter or search."}
              </span>
            </div>
          ) : (
            filteredRuns.map((run) => {
              const fail = run.status === "error";
              const outcomeLabel = fail ? "fail" : "pass";
              const modeIconMap = { record: "● ", play: "▶ ", "record-over": "⑂ " };
              const modeIcon = modeIconMap[run.mode] ?? "";
              return (
                <div
                  key={run.run_id}
                  onClick={() => navigate(`/runs/${run.run_id}`)}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "106px minmax(150px,1.5fr) 104px 86px 116px 62px",
                    gap: 0,
                    alignItems: "center",
                    padding: "14px 16px",
                    borderBottom: "1px solid var(--bd)",
                    cursor: "pointer",
                    transition: "background .12s",
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = "var(--hover)")}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                >
                  {/* Run ID */}
                  <div style={{ font: "500 12px var(--mono)", color: "var(--fg1)", display: "flex", alignItems: "center", gap: 8 }}>
                    <span
                      style={{
                        width: 7,
                        height: 7,
                        borderRadius: "50%",
                        flex: "none",
                        background: fail ? "var(--fail)" : "var(--pass)",
                        boxShadow: `0 0 0 3px ${fail ? "var(--fail-dim)" : "var(--pass-dim)"}`,
                      }}
                    />
                    <span
                      style={{
                        fontFamily: "var(--mono)",
                        fontSize: 12,
                        color: "var(--fg1)",
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                      title={run.run_id}
                    >
                      {truncateRunId(run.run_id)}
                    </span>
                  </div>

                  {/* Agent */}
                  <div style={{ minWidth: 0 }}>
                    <div
                      style={{
                        font: "550 12.5px var(--ui)",
                        color: "var(--fg0)",
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {run.agent}
                    </div>
                  </div>

                  {/* Recorded */}
                  <div style={{ font: "450 11px var(--mono)", color: "var(--fg1)" }}>
                    {formatTimestamp(run.created_at_ms)}
                  </div>

                  {/* Outcome chip */}
                  <div>
                    <span
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        font: "600 10px var(--mono)",
                        letterSpacing: ".06em",
                        padding: "3px 9px",
                        borderRadius: 6,
                        background: fail ? "var(--fail-dim)" : "var(--pass-dim)",
                        color: fail ? "var(--fail)" : "var(--pass)",
                        border: `1px solid ${fail ? "var(--fail)" : "var(--pass)"}`,
                      }}
                    >
                      {outcomeLabel}
                    </span>
                    {fmMatchedIds.has(run.run_id) && (
                      <span
                        title={
                          fmMatchLabels[run.run_id]
                            ? `Matched failure pattern ${fmMatchLabels[run.run_id]}`
                            : "Matched failure pattern"
                        }
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 4,
                          font: "600 8.5px var(--mono)",
                          letterSpacing: ".04em",
                          color: "var(--warn)",
                          background: "var(--warn-dim)",
                          border: "1px solid var(--warn)",
                          borderRadius: 5,
                          padding: "2px 6px",
                          whiteSpace: "nowrap",
                          cursor: "default",
                          marginLeft: 6,
                        }}
                      >
                        <span
                          style={{
                            width: 5,
                            height: 5,
                            borderRadius: "50%",
                            background: "var(--warn)",
                            display: "inline-block",
                            flex: "none",
                          }}
                        />
                        FM
                      </span>
                    )}
                  </div>

                  {/* Mode chip */}
                  <div>
                    <span
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        font: "500 10.5px var(--mono)",
                        padding: "3px 8px",
                        borderRadius: 6,
                        border: "1px solid",
                        background: "var(--bg2)",
                        ...(run.mode === "record"
                          ? { color: "var(--rec)", borderColor: "var(--rec)" }
                          : run.mode === "play"
                          ? { color: "var(--pass)", borderColor: "var(--pass)" }
                          : run.mode === "record-over"
                          ? { color: "var(--accent)", borderColor: "var(--accent-bd)" }
                          : { color: "var(--fg1)", borderColor: "var(--bd)" }),
                      }}
                    >
                      {modeIcon}{run.mode ?? "-"}
                    </span>
                  </div>

                  {/* Steps */}
                  <div style={{ font: "500 12px var(--mono)", color: "var(--fg1)" }}>
                    {run.step_count}
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
