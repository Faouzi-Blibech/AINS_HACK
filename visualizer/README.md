# visualizer/: the inspection UI

A raw JSON dump of a trace is unusable. The visualizer presents the run as something a human engineer can read. Three views:

- `src/TraceGraph.jsx`: **trajectory tree / execution graph.** Each node is a step; click to inspect. Node color = blame score from the root-cause analyzer. Side-effecting nodes are marked.
- `src/StepInspector.jsx`: **step inspector.** The exact LLM prompt, context window, tool arguments, and response for a selected step, reconstructed from blob-store references.
- `src/DivergenceDiff.jsx`: **divergence diff.** Side-by-side comparison of the original trace and a forked/replayed trace, highlighting where the two trajectories separate.

Prototype is a React app. Files here are placeholders for the final submission.
