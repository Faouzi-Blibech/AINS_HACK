export const MOCK_BLAME = {
  run_id: "run-fixture-001",
  failed_step_id: 4,
  root_cause_step_id: 2,
  verdict: "Step 4 is where it failed. Step 2 is why.",
  confidence: 0.9,
  steps: [
    {
      step_id: 1,
      blame_score: 0.6,
      rationale:
        "contributor: perturbing this step changes the downstream trajectory but does not resolve the failure",
    },
    {
      step_id: 2,
      blame_score: 1.0,
      rationale:
        "root cause: correcting this step's output resolves the failure",
    },
    {
      step_id: 3,
      blame_score: 0.4,
      rationale:
        "contributor: perturbing this step changes the downstream trajectory but does not resolve the failure",
    },
  ],
};
