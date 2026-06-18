import { NavLink, Outlet } from "react-router-dom";

function navLinkClass({ isActive }) {
  return [
    "rounded-md px-3 py-2 text-sm font-medium transition-colors",
    isActive
      ? "bg-zinc-800 text-white"
      : "text-zinc-400 hover:bg-zinc-800/60 hover:text-zinc-100",
  ].join(" ");
}

function NavItems() {
  return (
    <>
      <NavLink to="/" end className={navLinkClass}>
        Dashboard
      </NavLink>
      <NavLink to="/settings" className={navLinkClass}>
        Settings
      </NavLink>
    </>
  );
}

export default function AppShell() {
  return (
    <div className="flex min-h-screen flex-col bg-zinc-950 text-zinc-100 md:flex-row">
      {/* Mobile top bar */}
      <header className="flex items-center justify-between border-b border-zinc-800 bg-zinc-900 px-4 py-3 md:hidden">
        <div>
          <span className="text-base font-semibold tracking-tight">Cassette</span>
          <p className="text-xs text-zinc-500">Agent flight recorder</p>
        </div>
        <nav className="flex gap-1">
          <NavLink
            to="/"
            end
            className={({ isActive }) =>
              `rounded-md px-2.5 py-1.5 text-xs font-medium ${
                isActive ? "bg-zinc-800 text-white" : "text-zinc-400"
              }`
            }
          >
            Runs
          </NavLink>
          <NavLink
            to="/settings"
            className={({ isActive }) =>
              `rounded-md px-2.5 py-1.5 text-xs font-medium ${
                isActive ? "bg-zinc-800 text-white" : "text-zinc-400"
              }`
            }
          >
            Settings
          </NavLink>
        </nav>
      </header>

      {/* Desktop sidebar */}
      <aside className="hidden w-56 shrink-0 flex-col border-r border-zinc-800 bg-zinc-900 md:flex">
        <div className="border-b border-zinc-800 px-5 py-5">
          <span className="text-lg font-semibold tracking-tight">Cassette</span>
          <p className="mt-1 text-xs text-zinc-500">Agent flight recorder</p>
        </div>
        <nav className="flex flex-1 flex-col gap-1 p-3">
          <NavItems />
        </nav>
        <div className="border-t border-zinc-800 px-5 py-4 text-xs text-zinc-600">
          v0.1.0 · mock data
        </div>
      </aside>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <Outlet />
      </div>
    </div>
  );
}
