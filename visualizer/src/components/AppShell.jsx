import { useState, useEffect } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import MetricBar from "./MetricBar.jsx";

// Nav icon paths (20x20 viewBox)
const ICONS = {
  runs: "M3 5h14M3 10h14M3 15h8",
  trace: "M4 4l4 4-4 4M10 16h7",
  memory: "M10 2a5 5 0 00-3.5 8.5L3 14h14l-3.5-3.5A5 5 0 0010 2z",
  eval: "M4 12l4 4 8-8M17 3H3a1 1 0 00-1 1v12a1 1 0 001 1h14a1 1 0 001-1V4a1 1 0 00-1-1z",
};

const NAV_ITEMS = [
  { label: "Runs", to: "/", end: true, icon: "runs", count: 6 },
  { label: "Trace", to: "/runs/latest", end: false, icon: "trace", count: 9, matchPrefix: "/runs/" },
  { label: "Failure memory", to: "/memory", end: false, icon: "memory", count: 14 },
  { label: "Evaluation", to: "/eval", end: true, icon: "eval" },
];

function CassetteLogoMark() {
  return (
    <div
      style={{
        width: 38,
        height: 38,
        borderRadius: 11,
        background: "var(--brand)",
        display: "grid",
        placeItems: "center",
        flex: "none",
        boxShadow: "var(--glow)",
      }}
    >
      <svg width="24" height="24" viewBox="0 0 30 30">
        {/* Left reel */}
        <g>
          <circle cx="10" cy="15" r="4.6" fill="none" stroke="#0b0e18" strokeWidth="2" />
          <circle cx="10" cy="15" r="1.2" fill="#0b0e18" />
        </g>
        {/* Right reel */}
        <g>
          <circle cx="20" cy="15" r="4.6" fill="none" stroke="#0b0e18" strokeWidth="2" />
          <circle cx="20" cy="15" r="1.2" fill="#0b0e18" />
        </g>
      </svg>
    </div>
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

export default function AppShell() {
  const [theme, setTheme] = useState(() => {
    return localStorage.getItem("cassette-theme") || "dark";
  });
  const location = useLocation();

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("cassette-theme", theme);
  }, [theme]);

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
            <div
              style={{
                font: "450 9px var(--mono)",
                letterSpacing: ".1em",
                color: "var(--fg2)",
                marginTop: 2,
              }}
            >
              FLIGHT&nbsp;RECORDER
            </div>
          </div>
        </div>

        {/* Search field */}
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
          onClick={() => {}}
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
