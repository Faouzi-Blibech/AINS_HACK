const STATUS_STYLES = {
  ok: "bg-emerald-500/10 text-emerald-400 ring-emerald-500/20",
  error: "bg-red-500/10 text-red-400 ring-red-500/20",
  timeout: "bg-amber-500/10 text-amber-400 ring-amber-500/20",
  aborted: "bg-zinc-500/10 text-zinc-400 ring-zinc-500/20",
};

export default function StatusBadge({ status }) {
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.aborted;

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current opacity-80" />
      {status}
    </span>
  );
}
