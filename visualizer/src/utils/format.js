export function truncateRunId(runId, head = 8, tail = 4) {
  if (runId.length <= head + tail + 1) {
    return runId;
  }
  return `${runId.slice(0, head)}…${runId.slice(-tail)}`;
}

export function formatTimestamp(ms) {
  return new Date(ms).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
