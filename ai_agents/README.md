# ai_agents/: the AI analysis layer

This is where *AI is the mechanism, not a feature*. Remove this layer and Cassette is a tape recorder that replays bytes but explains nothing.

| File | Component | Job |
|---|---|---|
| `semantic_matcher.py` | Semantic matcher | Decide if two outputs express the same intent; score replay fidelity / determinism. |
| `mock_synthesizer.py` | Mock synthesizer | Generate a plausible tool response for a call that has no recorded response (divergence mode). |
| `root_cause.py` | Root-cause analyzer | Temporal Blame Graph: trace backward through causal links, assign a blame score per step. |
| `counterfactual.py` | Counterfactual repair agent | Generate N fix variants, replay in parallel, rank by outcome. |
| `debug_agent.py` | Debug agent | Turn plain English into a structurally valid JSON injection and fire the replay. |

Every output carries a confidence score; low-confidence results are flagged for human review (self-evaluation).
