// TraceGraph — the execution DAG / trajectory tree view.
//
// Each node is a step. Click a node to open the StepInspector. Node color
// encodes the blame score from the root-cause analyzer (red = root cause,
// orange = contributed, gray = innocent). Side-effecting nodes are marked.
//
// Skeleton only.

export default function TraceGraph(/* { runId } */) {
  // TODO: fetch trace, lay out steps as a graph (D3), color by blame score.
  return null;
}
