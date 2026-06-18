import { Route, Routes } from "react-router-dom";
import AppShell from "./components/AppShell.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import RunInspector from "./pages/RunInspector.jsx";
import Settings from "./pages/Settings.jsx";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/runs/:runId" element={<RunInspector />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}
