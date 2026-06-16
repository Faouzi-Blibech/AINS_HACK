# eval/: evaluation harness + synthetic test set

The evaluation discipline for the final submission. Four metrics run against a synthetic set of injected-failure scenarios.

| Metric | Definition | Target |
|---|---|---|
| Determinism rate | % of replays that reproduce the original tool-call sequence | 100% |
| Side-effect containment | Count of side-effecting tool calls executed during replay | 0 (always) |
| Semantic-match P/R | Precision/recall of the semantic matcher vs. human-labeled equivalences | > 0.85 |
| Root-cause accuracy | % of injected failures where the blame graph identifies the correct root cause | > 0.75 |

- `harness.py`: runs the four metrics and prints a report.
- `test_set/`: synthetic failure scenarios (each: a seeded run + a known injected fault + the expected root cause).

On non-determinism: tool responses are fixed by the tape, so the environment is deterministic. The LLM may still vary; the semantic matcher and the determinism-rate metric quantify that rather than pretending it away.
