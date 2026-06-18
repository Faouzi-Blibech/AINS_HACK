import { useNavigate } from "react-router-dom";
import StatusBadge from "../components/StatusBadge.jsx";
import { MOCK_RUNS } from "../mocks/mock_runs.js";
import { formatTimestamp, truncateRunId } from "../utils/format.js";

export default function Dashboard() {
  const navigate = useNavigate();

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-zinc-100">Runs</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Recorded agent executions. Select a run to inspect its trace.
        </p>
      </div>

      <div className="overflow-hidden rounded-lg border border-zinc-800 bg-zinc-900/50">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-xs font-medium uppercase tracking-wider text-zinc-500">
              <th className="px-4 py-3">Run ID</th>
              <th className="px-4 py-3">Agent</th>
              <th className="hidden px-4 py-3 sm:table-cell">Recorded</th>
              <th className="px-4 py-3">Steps</th>
              <th className="px-4 py-3">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/80">
            {MOCK_RUNS.map((run) => (
              <tr
                key={run.run_id}
                onClick={() => navigate(`/runs/${run.run_id}`)}
                className="cursor-pointer transition-colors hover:bg-zinc-800/40"
              >
                <td className="px-4 py-3">
                  <span
                    className="font-mono text-zinc-200"
                    title={run.run_id}
                  >
                    {truncateRunId(run.run_id)}
                  </span>
                </td>
                <td className="px-4 py-3 text-zinc-300">{run.agent}</td>
                <td className="hidden px-4 py-3 text-zinc-500 sm:table-cell">
                  {formatTimestamp(run.created_at_ms)}
                </td>
                <td className="px-4 py-3 font-mono text-zinc-400">
                  {run.step_count}
                </td>
                <td className="px-4 py-3">
                  <StatusBadge status={run.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {MOCK_RUNS.length === 0 && (
        <p className="mt-8 text-center text-sm text-zinc-500">
          No recorded runs yet.
        </p>
      )}
    </div>
  );
}
