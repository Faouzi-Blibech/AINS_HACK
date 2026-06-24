// DivergenceDiff -- side-by-side original vs forked/replayed trace.
//
// Aligns the original and forked runs by step_id and labels how each row
// changed after a record-over injection.

function stableStringify(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  return `{${Object.keys(value)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`)
    .join(",")}}`;
}

function sameStep(left, right) {
  return Boolean(left && right && stableStringify(left) === stableStringify(right));
}

function stepSummary(step) {
  if (!step) return "-";
  if (step.type === "llm_call") return `LLM - ${step.model ?? "model"}`;
  if (step.type === "tool_call") {
    const transport = step.transport ? ` - ${step.transport}` : "";
    return `Tool - ${step.tool ?? "tool"}${transport}`;
  }
  return step.type ?? "step";
}

function stepMeta(step) {
  if (!step) return "";
  const bits = [];
  if (step.status) bits.push(step.status);
  if (step.side_effecting) bits.push("side-effecting");
  if (step.causal_parents?.length) bits.push(`parents ${step.causal_parents.join(",")}`);
  return bits.join(" / ");
}

function changeKind(stepId, original, forked, forkStepId) {
  const numericStepId = Number(stepId);
  const numericForkStep = forkStepId == null ? null : Number(forkStepId);

  if (numericForkStep != null && numericStepId === numericForkStep) return "edited";
  if (original && !forked) return "missing from fork";
  if (!original && forked) return "new in fork";
  if (original && forked && !sameStep(original, forked)) return "changed";
  if (numericForkStep != null && numericStepId < numericForkStep) return "copied";
  return "same";
}

function changeColor(kind) {
  if (kind === "edited") return "var(--accent)";
  if (kind === "missing from fork") return "var(--warn)";
  if (kind === "changed" || kind === "new in fork") return "var(--pass)";
  if (kind === "copied") return "var(--fg1)";
  return "var(--fg2)";
}

function StepCell({ step }) {
  return (
    <div>
      <div style={{ font: "600 11.5px var(--ui)", color: step ? "var(--fg0)" : "var(--fg2)" }}>
        {stepSummary(step)}
      </div>
      {step && (
        <div
          style={{
            marginTop: 3,
            font: "450 10.5px var(--mono)",
            color: "var(--fg2)",
            whiteSpace: "normal",
          }}
        >
          {stepMeta(step) || `step_id ${step.step_id}`}
        </div>
      )}
    </div>
  );
}

export default function DivergenceDiff({
  originalTrace,
  forkTrace,
  forkStepId,
  editedFields,
  finalStatus,
  sideEffectCount,
}) {
  const originalSteps = originalTrace?.steps ?? [];
  const forkSteps = forkTrace?.steps ?? [];
  const originalById = new Map(originalSteps.map((step) => [step.step_id, step]));
  const forkById = new Map(forkSteps.map((step) => [step.step_id, step]));
  const stepIds = [
    ...new Set([
      ...originalSteps.map((step) => step.step_id),
      ...forkSteps.map((step) => step.step_id),
    ]),
  ].sort((a, b) => Number(a) - Number(b));

  const rows = stepIds.map((stepId) => {
    const original = originalById.get(stepId);
    const forked = forkById.get(stepId);
    return {
      stepId,
      original,
      forked,
      kind: changeKind(stepId, original, forked, forkStepId),
    };
  });

  const downstreamDeltaCount = rows.filter((row) =>
    ["missing from fork", "changed", "new in fork"].includes(row.kind)
  ).length;

  const headerCell = {
    background: "var(--bg2)",
    borderBottom: "1px solid var(--bd)",
    padding: "9px 12px",
    font: "600 9.5px var(--mono)",
    letterSpacing: ".08em",
    color: "var(--fg2)",
    textAlign: "left",
  };

  const bodyCell = {
    padding: "10px 12px",
    borderBottom: "1px solid var(--bd)",
    borderLeft: "1px solid var(--bd)",
    verticalAlign: "top",
  };

  return (
    <div
      style={{
        border: "1px solid var(--bd)",
        borderRadius: 10,
        overflow: "hidden",
        background: "var(--bg1)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          padding: "11px 13px",
          borderBottom: "1px solid var(--bd)",
          background: "var(--bg2)",
          flexWrap: "wrap",
        }}
      >
        <div>
          <div style={{ font: "600 12.5px var(--ui)", color: "var(--fg0)" }}>
            Divergence diff
          </div>
          <div style={{ marginTop: 3, font: "450 10.5px var(--mono)", color: "var(--fg2)" }}>
            fork @ step {forkStepId ?? "?"} / downstream deltas {downstreamDeltaCount}
          </div>
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            flexWrap: "wrap",
            font: "450 10.5px var(--mono)",
            color: "var(--fg1)",
          }}
        >
          <span>status {finalStatus ?? forkTrace?.status ?? "unknown"}</span>
          <span>side effects {sideEffectCount ?? 0}</span>
          {editedFields?.length > 0 && <span>edited {editedFields.join(", ")}</span>}
        </div>
      </div>

      <div style={{ overflowX: "auto" }}>
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            tableLayout: "fixed",
          }}
        >
          <thead>
            <tr>
              <th style={{ ...headerCell, width: 74 }}>STEP</th>
              <th style={{ ...headerCell, borderLeft: "1px solid var(--bd)" }}>
                ORIGINAL
              </th>
              <th style={{ ...headerCell, borderLeft: "1px solid var(--bd)" }}>
                FORKED
              </th>
              <th style={{ ...headerCell, borderLeft: "1px solid var(--bd)", width: 150 }}>
                CHANGE
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.length > 0 ? (
              rows.map((row, index) => {
                const isLast = index === rows.length - 1;
                const isForkStep =
                  forkStepId != null && Number(row.stepId) === Number(forkStepId);
                const borderBottom = isLast ? "none" : "1px solid var(--bd)";
                return (
                  <tr
                    key={row.stepId}
                    style={{
                      background: isForkStep ? "var(--accent-dim)" : "transparent",
                    }}
                  >
                    <td
                      style={{
                        padding: "10px 12px",
                        borderBottom,
                        color: isForkStep ? "var(--accent2)" : "var(--fg2)",
                        font: "600 11px var(--mono)",
                        verticalAlign: "top",
                      }}
                    >
                      {row.stepId}
                    </td>
                    <td style={{ ...bodyCell, borderBottom }}>
                      <StepCell step={row.original} />
                    </td>
                    <td style={{ ...bodyCell, borderBottom }}>
                      <StepCell step={row.forked} />
                    </td>
                    <td
                      style={{
                        ...bodyCell,
                        borderBottom,
                        color: changeColor(row.kind),
                        font: "600 11px var(--ui)",
                      }}
                    >
                      {row.kind}
                    </td>
                  </tr>
                );
              })
            ) : (
              <tr>
                <td
                  colSpan={4}
                  style={{
                    padding: "13px",
                    font: "450 12px var(--ui)",
                    color: "var(--fg2)",
                    textAlign: "center",
                  }}
                >
                  No step diff available.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
