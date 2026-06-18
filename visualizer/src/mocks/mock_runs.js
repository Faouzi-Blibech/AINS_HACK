import mockTrace from "./mock_trace_fixture.json";

export const MOCK_RUNS = [
  {
    run_id: mockTrace.run_id,
    agent: mockTrace.agent,
    created_at_ms: mockTrace.created_at_ms,
    status: mockTrace.status,
    mode: mockTrace.mode,
    step_count: mockTrace.steps.length,
  },
];
