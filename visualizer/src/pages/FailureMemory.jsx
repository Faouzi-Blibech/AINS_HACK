import { useEffect, useState } from "react";
import { getLibrary, searchLibrary } from "../api/client.js";

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

function fmLabel(entry, index) {
  if (entry.id == null) return `FM-${String(index + 1).padStart(3, "0")}`;
  return String(entry.id).toUpperCase().startsWith("FM") ? entry.id : `FM-${entry.id}`;
}

function MemoryCard({ entry, index, score }) {
  const label = fmLabel(entry, index);
  const detRate =
    entry.determinism_rate != null ? `${Math.round(entry.determinism_rate * 100)}%` : null;
  const scorePct = score != null ? Math.round(score * 100) : null;

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
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
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
          {scorePct != null && (
            <span
              style={{
                font: "700 9px var(--mono)",
                letterSpacing: ".06em",
                color: scorePct >= 60 ? "var(--pass)" : "var(--warn)",
                border: `1px solid ${scorePct >= 60 ? "var(--pass)" : "var(--warn)"}`,
                borderRadius: 7,
                padding: "3px 8px",
                flex: "none",
              }}
            >
              {scorePct}% MATCH
            </span>
          )}
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
        {detRate && (
          <div style={{ textAlign: "right", flex: "none" }}>
            <div style={{ font: "600 8.5px var(--mono)", letterSpacing: ".1em", color: "var(--fg2)" }}>
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

      <div>
        <div style={{ font: "600 9px var(--mono)", letterSpacing: ".12em", color: "var(--fg2)", marginBottom: 5 }}>
          FAILURE PATTERN
        </div>
        <div style={{ font: "550 14px var(--ui)", color: "var(--fg0)", lineHeight: 1.5 }}>
          {entry.failure_pattern}
        </div>
      </div>

      {entry.fix_that_worked && (
        <div
          style={{
            background: "var(--warn-dim)",
            border: "1px solid rgba(255,180,84,.22)",
            borderRadius: 11,
            padding: "11px 14px",
          }}
        >
          <div style={{ font: "600 9px var(--mono)", letterSpacing: ".12em", color: "var(--warn)", marginBottom: 5 }}>
            FIX THAT WORKED
          </div>
          <div style={{ font: "450 12.5px var(--ui)", color: "var(--fg1)", lineHeight: 1.55 }}>
            {entry.fix_that_worked}
          </div>
        </div>
      )}

    </div>
  );
}

const SectionLabel = ({ children }) => (
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

const EXAMPLES = [
  "the priority field was ambiguous so the ticket was routed to the wrong team",
  "a tool call timed out and the empty result was treated as success",
  "a tool was called with a string where a number was required",
];

export default function FailureMemory() {
  const [entries, setEntries] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Semantic recall box state
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [result, setResult] = useState(null);
  const [searchError, setSearchError] = useState(null);

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

  async function runSearch(q) {
    const text = (q ?? query).trim();
    if (!text) return;
    setQuery(text);
    setSearching(true);
    setSearchError(null);
    setResult(null);
    try {
      const data = await searchLibrary(text);
      setResult(data);
    } catch (err) {
      setSearchError(err.message ?? "Recall failed.");
    } finally {
      setSearching(false);
    }
  }

  return (
    <div style={{ flex: 1, overflowY: "auto", overflowX: "hidden", padding: "28px 28px 48px" }}>
      {/* Page header */}
      <div style={{ marginBottom: 22 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <h1 style={{ margin: 0, font: "700 22px var(--ui)", letterSpacing: "-.02em", color: "var(--fg0)" }}>
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
        <p style={{ margin: "5px 0 0", font: "450 12.5px var(--ui)", color: "var(--fg2)" }}>
          Failures Cassette has diagnosed and fixed. Describe a situation and the AI recalls
          the most similar past failures by meaning, with the fix that worked.
        </p>
      </div>

      {/* ===== SEMANTIC RECALL BOX ===== */}
      <div
        style={{
          background: "linear-gradient(180deg, var(--bg2), var(--bg1))",
          border: "1px solid var(--accent-bd)",
          borderRadius: 16,
          padding: "18px 20px",
          marginBottom: 24,
          boxShadow: "var(--glow)",
        }}
      >
        <SectionLabel>Recall similar failures</SectionLabel>
        <div style={{ display: "flex", gap: 10 }}>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runSearch()}
            placeholder="Describe a failure or situation, e.g. a ticket was misrouted because the priority was unclear"
            style={{
              flex: 1,
              background: "var(--bg2)",
              border: "1px solid var(--bd)",
              borderRadius: 10,
              padding: "10px 13px",
              color: "var(--fg0)",
              font: "450 13px var(--ui)",
            }}
          />
          <button
            onClick={() => runSearch()}
            disabled={searching || !query.trim()}
            style={{
              background: searching ? "var(--bg3)" : "var(--accent)",
              color: searching ? "var(--fg2)" : "var(--bg0)",
              border: "none",
              borderRadius: 10,
              padding: "10px 20px",
              font: "600 13px var(--ui)",
              cursor: searching || !query.trim() ? "not-allowed" : "pointer",
              flex: "none",
            }}
          >
            {searching ? "Recalling..." : "Recall"}
          </button>
        </div>

        {/* Example chips */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 11 }}>
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              onClick={() => runSearch(ex)}
              style={{
                font: "450 11px var(--ui)",
                color: "var(--fg1)",
                background: "var(--bg2)",
                border: "1px solid var(--bd)",
                borderRadius: 999,
                padding: "4px 11px",
                cursor: "pointer",
              }}
            >
              {ex}
            </button>
          ))}
        </div>

        {searchError && (
          <div style={{ marginTop: 12, font: "450 12px var(--ui)", color: "var(--fail)" }}>{searchError}</div>
        )}

        {/* Recall results */}
        {result && !searching && (
          <div style={{ marginTop: 16 }}>
            {result.matches?.length ? (
              <>
                <div style={{ font: "450 12px var(--ui)", color: "var(--fg1)", marginBottom: 12, lineHeight: 1.5 }}>
                  <span style={{ font: "600 10px var(--mono)", color: "var(--accent2)", letterSpacing: ".06em" }}>
                    AI RANKING ({Math.round((result.confidence ?? 0) * 100)}% confidence)
                  </span>
                  {result.rationale ? ` — ${result.rationale}` : ""}
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {result.matches.map((m, i) => (
                    <MemoryCard key={m.id ?? i} entry={m} index={i} score={m.score} />
                  ))}
                </div>
              </>
            ) : (
              <div style={{ font: "450 12.5px var(--ui)", color: "var(--fg2)" }}>
                No similar failure found in memory.
              </div>
            )}
          </div>
        )}
      </div>

      {/* Error state for the full list */}
      {error && (
        <div
          style={{
            background: "var(--fail-dim)",
            border: "1px solid var(--fail)",
            borderRadius: 14,
            padding: "16px 20px",
            font: "450 13px var(--ui)",
            color: "var(--fail)",
          }}
        >
          {error}
        </div>
      )}

      {loading && (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {[0, 1, 2].map((i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      )}

      {!loading && !error && entries.length === 0 && (
        <div
          style={{
            background: "var(--bg1)",
            border: "1px solid var(--bd)",
            borderRadius: 16,
            padding: "56px 24px",
            textAlign: "center",
            color: "var(--fg2)",
            font: "450 13px var(--ui)",
          }}
        >
          No failure patterns recorded yet.
        </div>
      )}

      {/* Full library list */}
      {!loading && !error && entries.length > 0 && (
        <>
          <SectionLabel>All learned patterns</SectionLabel>
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {entries.map((entry, idx) => (
              <MemoryCard key={idx} entry={entry} index={idx} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
