import { useState, useEffect, useRef, useCallback } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import MetricBar from "./MetricBar.jsx";
import { listRuns } from "../api/client.js";

// Nav icon paths (20x20 viewBox)
const ICONS = {
  runs: "M3 5h14M3 10h14M3 15h8",
  trace: "M4 4l4 4-4 4M10 16h7",
  memory: "M10 2a5 5 0 00-3.5 8.5L3 14h14l-3.5-3.5A5 5 0 0010 2z",
  eval: "M4 12l4 4 8-8M17 3H3a1 1 0 00-1 1v12a1 1 0 001 1h14a1 1 0 001-1V4a1 1 0 00-1-1z",
  connect: "M8.5 4.5a2.5 2.5 0 015 0v1a2.5 2.5 0 01-5 0v-1zM4 10h12M6 10v5.5a1.5 1.5 0 003 0V10M11 10v5.5a1.5 1.5 0 003 0V10",
};

const NAV_ITEMS = [
  { label: "Runs", to: "/", end: true, icon: "runs", count: 6 },
  { label: "Trace", to: "/runs/latest", end: false, icon: "trace", count: 9, matchPrefix: "/runs/" },
  { label: "Failure memory", to: "/memory", end: false, icon: "memory", count: 14 },
  { label: "Evaluation", to: "/eval", end: true, icon: "eval" },
  { label: "Connect agent", to: "/connect", end: true, icon: "connect" },
];

function CassetteLogoMark() {
  return (
    <svg width="32" height="32" viewBox="0 0 30 30" style={{ flex: "none" }}>
      <rect x="1" y="1" width="28" height="28" rx="7" fill="var(--bg3)" stroke="var(--bd2)" />
      {/* Left reel */}
      <g>
        <circle cx="10" cy="15" r="4.4" fill="none" stroke="var(--accent)" strokeWidth="1.6" />
        <circle cx="10" cy="15" r="1.1" fill="var(--accent)" />
      </g>
      {/* Right reel */}
      <g>
        <circle cx="20" cy="15" r="4.4" fill="none" stroke="var(--accent)" strokeWidth="1.6" />
        <circle cx="20" cy="15" r="1.1" fill="var(--accent)" />
      </g>
    </svg>
  );
}

function SidebarNavItem({ label, to, end, icon, count, matchPrefix }) {
  const location = useLocation();
  const prefixActive = matchPrefix ? location.pathname.startsWith(matchPrefix) : false;

  return (
    <NavLink
      to={to}
      end={end}
      style={({ isActive }) => {
        const active = isActive || prefixActive;
        return {
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "9px 10px",
          borderRadius: 10,
          cursor: "pointer",
          textDecoration: "none",
          font: "500 13.5px var(--ui)",
          color: active ? "var(--accent)" : "var(--fg1)",
          background: active ? "var(--accent-dim)" : "transparent",
          borderLeft: active ? "2px solid var(--accent)" : "2px solid transparent",
          transition: "background 0.15s, color 0.15s",
          marginBottom: 2,
        };
      }}
      onMouseEnter={(e) => {
        if (!e.currentTarget.getAttribute("aria-current")) {
          e.currentTarget.style.background = "var(--hover)";
          e.currentTarget.style.color = "var(--fg0)";
        }
      }}
      onMouseLeave={(e) => {
        if (!e.currentTarget.getAttribute("aria-current")) {
          e.currentTarget.style.background = "";
          e.currentTarget.style.color = "";
        }
      }}
    >
      <svg
        width="18"
        height="18"
        viewBox="0 0 20 20"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ flex: "none" }}
      >
        <path d={ICONS[icon]} />
      </svg>
      <span style={{ flex: 1, textAlign: "left" }}>{label}</span>
      {count != null && (
        <span
          style={{
            font: "600 10.5px var(--mono)",
            background: "var(--bg3)",
            border: "1px solid var(--bd2)",
            borderRadius: 6,
            padding: "1px 7px",
            color: "var(--fg2)",
          }}
        >
          {count}
        </span>
      )}
    </NavLink>
  );
}

// Jump palette modal
function JumpPalette({ onClose }) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [runs, setRuns] = useState([]);
  const [fetchError, setFetchError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [highlightIndex, setHighlightIndex] = useState(0);
  const inputRef = useRef(null);

  useEffect(() => {
    listRuns()
      .then((data) => {
        setRuns(data.runs ?? []);
        setLoading(false);
      })
      .catch(() => {
        setFetchError(true);
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    if (inputRef.current) inputRef.current.focus();
  }, []);

  const filteredRuns = runs.filter((r) => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return (
      (r.run_id ?? "").toLowerCase().includes(q) ||
      (r.agent ?? "").toLowerCase().includes(q)
    );
  });

  // Reset highlight when query changes
  useEffect(() => {
    setHighlightIndex(0);
  }, [query]);

  function goToRun(runId) {
    navigate(`/runs/${runId}`);
    onClose();
  }

  function handleKeyDown(e) {
    if (e.key === "Escape") {
      onClose();
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlightIndex((i) => Math.min(i + 1, filteredRuns.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlightIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      const run = filteredRuns[highlightIndex];
      if (run) goToRun(run.run_id);
    }
  }

  return (
    // Backdrop
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        background: "rgba(0,0,0,0.48)",
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        paddingTop: "15vh",
      }}
    >
      {/* Panel */}
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 520,
          maxWidth: "90vw",
          background: "var(--bg1)",
          border: "1px solid var(--bd2)",
          borderRadius: 16,
          boxShadow: "0 24px 64px rgba(0,0,0,0.48)",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* Input row */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "14px 16px",
            borderBottom: "1px solid var(--bd)",
          }}
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 16 16"
            style={{ flex: "none", color: "var(--fg2)" }}
          >
            <circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <path d="M11 11l3.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Jump to a run..."
            style={{
              flex: 1,
              border: "none",
              outline: "none",
              background: "transparent",
              font: "450 14px var(--ui)",
              color: "var(--fg0)",
            }}
          />
          <kbd
            style={{
              font: "600 10px var(--mono)",
              background: "var(--bg3)",
              border: "1px solid var(--bd2)",
              borderRadius: 5,
              padding: "2px 6px",
              color: "var(--fg2)",
            }}
          >
            ESC
          </kbd>
        </div>

        {/* Results list */}
        <div style={{ maxHeight: 360, overflowY: "auto" }}>
          {loading && (
            <div
              style={{
                padding: "24px 16px",
                font: "450 12.5px var(--ui)",
                color: "var(--fg2)",
                textAlign: "center",
              }}
            >
              Loading runs...
            </div>
          )}
          {!loading && fetchError && (
            <div
              style={{
                padding: "24px 16px",
                font: "450 12.5px var(--ui)",
                color: "var(--fail)",
                textAlign: "center",
              }}
            >
              Could not load runs.
            </div>
          )}
          {!loading && !fetchError && filteredRuns.length === 0 && (
            <div
              style={{
                padding: "24px 16px",
                font: "450 12.5px var(--ui)",
                color: "var(--fg2)",
                textAlign: "center",
              }}
            >
              No runs match.
            </div>
          )}
          {!loading &&
            !fetchError &&
            filteredRuns.map((run, idx) => {
              const highlighted = idx === highlightIndex;
              const fail = run.status === "error";
              return (
                <div
                  key={run.run_id}
                  onClick={() => goToRun(run.run_id)}
                  onMouseEnter={() => setHighlightIndex(idx)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "10px 16px",
                    cursor: "pointer",
                    background: highlighted ? "var(--accent-dim)" : "transparent",
                    borderLeft: highlighted ? "2px solid var(--accent)" : "2px solid transparent",
                    transition: "background 0.08s",
                  }}
                >
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
                      font: "500 12px var(--mono)",
                      color: highlighted ? "var(--accent)" : "var(--fg1)",
                      flex: "none",
                    }}
                  >
                    {run.run_id}
                  </span>
                  <span
                    style={{
                      font: "450 12px var(--ui)",
                      color: "var(--fg2)",
                      minWidth: 0,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {run.agent}
                  </span>
                </div>
              );
            })}
        </div>
      </div>
    </div>
  );
}

export default function AppShell() {
  const [theme, setTheme] = useState(() => {
    return localStorage.getItem("cassette-theme") || "dark";
  });
  const location = useLocation();
  const [paletteOpen, setPaletteOpen] = useState(false);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("cassette-theme", theme);
  }, [theme]);

  // Ctrl/Cmd+K shortcut
  const handleGlobalKeyDown = useCallback((e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "k") {
      e.preventDefault();
      setPaletteOpen(true);
    }
  }, []);

  useEffect(() => {
    window.addEventListener("keydown", handleGlobalKeyDown);
    return () => window.removeEventListener("keydown", handleGlobalKeyDown);
  }, [handleGlobalKeyDown]);

  function toggleTheme() {
    setTheme((t) => (t === "dark" ? "light" : "dark"));
  }

  // Derive page title from route
  let pageTitle = "Runs";
  let pageSub = "All agent runs";
  if (location.pathname.startsWith("/runs/")) {
    pageTitle = "Execution trace";
    pageSub = location.pathname.replace("/runs/", "") + " · triage-agent";
  } else if (location.pathname === "/memory") {
    pageTitle = "Failure memory";
    pageSub = "Recorded failure patterns";
  } else if (location.pathname === "/trace") {
    pageTitle = "Execution trace";
    pageSub = "Select a run to inspect";
  } else if (location.pathname === "/eval") {
    pageTitle = "Evaluation";
    pageSub = "Metric scores vs targets";
  } else if (location.pathname === "/connect") {
    pageTitle = "Connect agent";
    pageSub = "Quick test or bring your own agent";
  }

  return (
    <div
      style={{
        display: "flex",
        minHeight: "100vh",
        background: "var(--bg0)",
        color: "var(--fg0)",
        fontFamily: "var(--ui)",
      }}
    >
      {/* Jump palette */}
      {paletteOpen && <JumpPalette onClose={() => setPaletteOpen(false)} />}

      {/* Left sidebar */}
      <aside
        style={{
          width: 252,
          flex: "none",
          background: "var(--bg1)",
          borderRight: "1px solid var(--bd)",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* Brand */}
        <div
          style={{
            padding: "22px 20px 18px",
            display: "flex",
            alignItems: "center",
            gap: 13,
          }}
        >
          <CassetteLogoMark />
          <div>
            <div
              style={{
                font: "700 16px var(--ui)",
                letterSpacing: ".15em",
                color: "var(--fg0)",
              }}
            >
              CASSETTE
            </div>
          </div>
        </div>

        {/* Search / jump button */}
        <button
          style={{
            margin: "4px 16px 8px",
            display: "flex",
            alignItems: "center",
            gap: 9,
            background: "var(--bg2)",
            border: "1px solid var(--bd)",
            borderRadius: 11,
            padding: "10px 12px",
            cursor: "pointer",
            color: "var(--fg2)",
            font: "450 12.5px var(--ui)",
          }}
          onClick={() => setPaletteOpen(true)}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 16 16"
            style={{ flex: "none" }}
          >
            <circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <path d="M11 11l3.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <span style={{ flex: 1, textAlign: "left" }}>Search or jump to...</span>
          <span
            style={{
              font: "600 10px var(--mono)",
              background: "var(--bg3)",
              border: "1px solid var(--bd2)",
              borderRadius: 5,
              padding: "2px 6px",
            }}
          >
            K
          </span>
        </button>

        {/* WORKSPACE nav */}
        <div style={{ padding: "8px 14px" }}>
          <div
            style={{
              font: "600 9.5px var(--mono)",
              letterSpacing: ".16em",
              color: "var(--fg2)",
              padding: "10px 8px 7px",
            }}
          >
            WORKSPACE
          </div>
          {NAV_ITEMS.map((item) => (
            <SidebarNavItem key={item.to} {...item} />
          ))}
        </div>

        {/* Spacer */}
        <div style={{ flex: 1 }} />

        {/* Agent footer */}
        <div
          style={{
            padding: 16,
            borderTop: "1px solid var(--bd)",
            display: "flex",
            flexDirection: "column",
            gap: 11,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 11,
              padding: "11px 12px",
              border: "1px solid var(--bd)",
              borderRadius: 12,
              background: "var(--bg2)",
            }}
          >
            <div style={{ position: "relative", flex: "none" }}>
              <span
                style={{
                  width: 9,
                  height: 9,
                  borderRadius: "50%",
                  background: "var(--pass)",
                  boxShadow: "0 0 0 3px var(--pass-dim)",
                  display: "block",
                }}
              />
              <span
                style={{
                  position: "absolute",
                  inset: -3,
                  borderRadius: "50%",
                  border: "1px solid var(--pass)",
                  opacity: 0.5,
                  animation: "glowpulse 2s ease-in-out infinite",
                }}
              />
            </div>
            <div style={{ minWidth: 0 }}>
              <div
                style={{
                  font: "550 11px var(--mono)",
                  color: "var(--fg1)",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                triage-agent v2.3.1
              </div>
              <div
                style={{
                  font: "450 9.5px var(--mono)",
                  color: "var(--fg2)",
                }}
              >
                engine v0.9 live
              </div>
            </div>
          </div>
        </div>
      </aside>

      {/* Main content area */}
      <main
        style={{
          flex: 1,
          minWidth: 0,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        {/* Top metric bar */}
        <MetricBar
          pageTitle={pageTitle}
          pageSub={pageSub}
          onThemeToggle={toggleTheme}
          theme={theme}
        />

        {/* Page content */}
        <div
          style={{
            flex: 1,
            minHeight: 0,
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
          }}
        >
          <Outlet />
        </div>
      </main>
    </div>
  );
}
