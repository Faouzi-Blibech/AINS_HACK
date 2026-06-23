import { Route, Routes } from "react-router-dom";
import AppShell from "./components/AppShell.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import RunInspector from "./pages/RunInspector.jsx";
import FailureMemory from "./pages/FailureMemory.jsx";
import EvalReport from "./pages/EvalReport.jsx";
import ConnectAgent from "./pages/ConnectAgent.jsx";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/runs/:runId" element={<RunInspector />} />
        <Route path="/memory" element={<FailureMemory />} />
        <Route path="/eval" element={<EvalReport />} />
        <Route path="/connect" element={<ConnectAgent />} />
      </Route>
    </Routes>
  );
}
