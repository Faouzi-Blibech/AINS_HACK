"""ai_agents: the AI analysis layer.

Where *AI is the mechanism, not a feature*. Houses the five AI components
(semantic matcher, mock synthesizer, root-cause / Temporal Blame Graph,
counterfactual repair, debug agent), the confidence / self-eval wrapper, and
the Layer 2 failure-memory intelligence.

Reason over the shared trace contract (docs/trace_schema.json); never touch a
live endpoint. All perturbation / divergence goes through the ReplayEngine
contract in `replay_interface.py`, which the replay_engine module satisfies.
"""
