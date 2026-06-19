// TraceGraph — execution DAG rendered with @xyflow/react, colored by blame tier.

import { useCallback, useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

// ---------------------------------------------------------------------------
// Blame tier helpers
// ---------------------------------------------------------------------------

function getBlameTier(stepId, blame) {
  if (!blame) return "neutral";
  if (stepId === blame.root_cause_step_id) return "root";
  const entry = blame.steps?.find((s) => s.step_id === stepId);
  if (!entry) return "neutral";
  return entry.blame_score > 0 ? "contributor" : "innocent";
}

// Node border + background by blame tier (dark-zinc theme compatible)
const TIER_STYLES = {
  root: {
    border: "border-red-500",
    bg: "bg-red-500/10",
    label: "text-red-300",
    idColor: "text-red-400/70",
  },
  contributor: {
    border: "border-amber-500",
    bg: "bg-amber-500/10",
    label: "text-amber-300",
    idColor: "text-amber-400/70",
  },
  innocent: {
    border: "border-zinc-600",
    bg: "bg-zinc-800/60",
    label: "text-zinc-400",
    idColor: "text-zinc-500",
  },
  neutral: {
    border: "border-zinc-700",
    bg: "bg-zinc-800/50",
    label: "text-zinc-300",
    idColor: "text-zinc-500",
  },
};

// ---------------------------------------------------------------------------
// Custom node component
// ---------------------------------------------------------------------------

function StepNode({ data, selected }) {
  const { stepId, label, sideEffecting, tier, isFailed } = data;
  const style = TIER_STYLES[tier] ?? TIER_STYLES.neutral;

  // Selected ring takes visual precedence; if both, the outline below adds the failed cue.
  const combinedRing = selected
    ? "ring-2 ring-sky-500"
    : isFailed
    ? "ring-2 ring-red-500/80"
    : "";

  return (
    <div
      className={[
        "relative min-w-[160px] rounded-md border px-4 py-3 text-sm transition-all",
        style.border,
        style.bg,
        combinedRing,
        // Extra outline for failed+selected at the same time
        selected && isFailed ? "outline outline-2 outline-red-500/60" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {/* React Flow connection handles */}
      <Handle
        type="target"
        position={Position.Top}
        className="!border-zinc-600 !bg-zinc-700"
      />
      <Handle
        type="source"
        position={Position.Bottom}
        className="!border-zinc-600 !bg-zinc-700"
      />

      {/* Step id */}
      <p className={`font-mono text-xs ${style.idColor}`}>#{stepId}</p>

      {/* Label (LLM · model or Tool · tool) */}
      <p className={`mt-0.5 font-medium ${style.label}`}>{label}</p>

      {/* Badges row */}
      <div className="mt-1.5 flex flex-wrap items-center gap-1">
        {sideEffecting && (
          <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-xs text-amber-400">
            side-effect
          </span>
        )}
        {isFailed && (
          <span className="rounded bg-red-500/15 px-1.5 py-0.5 text-xs font-semibold text-red-400">
            failed here
          </span>
        )}
        {tier === "root" && (
          <span className="rounded bg-red-500/15 px-1.5 py-0.5 text-xs font-semibold text-red-400">
            root cause
          </span>
        )}
        {tier === "contributor" && !isFailed && (
          <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-xs text-amber-400">
            contributor
          </span>
        )}
      </div>
    </div>
  );
}

// Register once outside the parent to avoid React Flow warnings about nodeTypes
// being recreated on each render.
const NODE_TYPES = { step: StepNode };

// ---------------------------------------------------------------------------
// Layout helpers
// ---------------------------------------------------------------------------

/**
 * Deterministic topological layout.
 * Assigns each node a "depth" equal to 1 + max(parent depths).
 * Within the same depth, nodes are spread horizontally.
 */
function computeLayout(steps) {
  // Build depth map
  const depthMap = {};
  const stepMap = {};
  steps.forEach((s) => (stepMap[s.step_id] = s));

  function depth(stepId, visited = new Set()) {
    if (depthMap[stepId] !== undefined) return depthMap[stepId];
    if (visited.has(stepId)) return 0; // cycle guard
    visited.add(stepId);
    const step = stepMap[stepId];
    if (!step || step.causal_parents.length === 0) {
      depthMap[stepId] = 0;
      return 0;
    }
    const parentDepths = step.causal_parents.map((pid) =>
      depth(pid, new Set(visited))
    );
    depthMap[stepId] = Math.max(...parentDepths) + 1;
    return depthMap[stepId];
  }

  steps.forEach((s) => depth(s.step_id));

  // Group by depth level
  const byDepth = {};
  steps.forEach((s) => {
    const d = depthMap[s.step_id] ?? 0;
    (byDepth[d] = byDepth[d] ?? []).push(s.step_id);
  });

  // Compute (x, y) positions
  const NODE_W = 180;
  const NODE_H = 110;
  const H_GAP = 40;
  const V_GAP = 60;

  const positions = {};
  Object.entries(byDepth).forEach(([depthStr, ids]) => {
    const d = Number(depthStr);
    const totalW = ids.length * NODE_W + (ids.length - 1) * H_GAP;
    ids.forEach((id, i) => {
      positions[id] = {
        x: i * (NODE_W + H_GAP) - totalW / 2 + NODE_W / 2,
        y: d * (NODE_H + V_GAP),
      };
    });
  });

  return positions;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function TraceGraph({ trace, selectedStepId, onSelectStep, blame }) {
  const { nodes, edges } = useMemo(() => {
    const positions = computeLayout(trace.steps);

    const nodes = trace.steps.map((step) => {
      const label =
        step.type === "llm_call"
          ? `LLM · ${step.model ?? "unknown"}`
          : `Tool · ${step.tool ?? "unknown"}`;

      const tier = getBlameTier(step.step_id, blame);
      const isFailed = blame ? step.step_id === blame.failed_step_id : false;
      const pos = positions[step.step_id] ?? { x: 0, y: 0 };

      return {
        id: String(step.step_id),
        type: "step",
        position: pos,
        selected: step.step_id === selectedStepId,
        data: {
          stepId: step.step_id,
          label,
          sideEffecting: !!step.side_effecting,
          tier,
          isFailed,
        },
      };
    });

    const edges = [];
    trace.steps.forEach((step) => {
      (step.causal_parents ?? []).forEach((parentId) => {
        edges.push({
          id: `e${parentId}-${step.step_id}`,
          source: String(parentId),
          target: String(step.step_id),
          style: { stroke: "#52525b", strokeWidth: 1.5 },
          markerEnd: { type: "arrowclosed", color: "#52525b" },
        });
      });
    });

    return { nodes, edges };
  }, [trace, blame, selectedStepId]);

  const handleNodeClick = useCallback(
    (_event, node) => {
      onSelectStep(Number(node.id));
    },
    [onSelectStep]
  );

  return (
    <div className="flex h-full min-h-0 flex-col rounded-lg border border-zinc-800 bg-zinc-900/50">
      {/* Header */}
      <div className="shrink-0 border-b border-zinc-800 px-4 py-3">
        <h2 className="text-sm font-medium text-zinc-200">Trace Graph</h2>
        <p className="mt-0.5 font-mono text-xs text-zinc-500">{trace.run_id}</p>
      </div>

      {/* React Flow canvas */}
      <div className="flex-1 min-h-0">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          onNodeClick={handleNodeClick}
          fitView
          fitViewOptions={{ padding: 0.25 }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={true}
          proOptions={{ hideAttribution: true }}
          colorMode="dark"
          style={{ background: "transparent" }}
        >
          <Background color="#3f3f46" gap={20} size={1} />
          <Controls
            showInteractive={false}
            className="!border-zinc-700 !bg-zinc-800 !shadow-none"
          />
        </ReactFlow>
      </div>
    </div>
  );
}
