# replay_engine/: deterministic replay, divergence, snapshot

Re-executes a recorded run against the tape instead of live endpoints.

- `replay.py`: **deterministic replay (Play).** Re-runs the agent step-by-step; every tool call returns its recorded response. `side_effecting: true` calls are ALWAYS mocked. This is the core safety guarantee.
- `divergence.py`: **divergence (Record-over).** Edit a prompt or tool result at step N; the call's identity changes, the recorded response no longer matches, so the run forks a new branch and continues down a new trajectory.
- `snapshot.py`: **state snapshot and resume.** Serialize the agent's context window at any step; resume or inspect from that exact state.

Replays are stateless and run in parallel, which is what makes the counterfactual agent's N-variants-at-once possible.
