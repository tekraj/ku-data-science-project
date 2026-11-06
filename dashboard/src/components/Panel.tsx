// A titled chart/table card. `right` sits opposite the title (a note or a
// control); `height` is a Tailwind height class for the chart body, or
// omitted for free-height content.
export function Panel({ title, note = null, right = null, height = "", className = "", children }) {
  return (
    <article className={`panel ${className}`}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="font-display text-xl font-semibold">{title}</h3>
          {note ? <p className="text-xs text-slate-400">{note}</p> : null}
        </div>
        {right}
      </div>
      {height ? <div className={height}>{children}</div> : children}
    </article>
  );
}

export function Metric({ label, value, sub = null, tone = "text-slate-100" }) {
  return (
    <article className="metric-card">
      <p className="text-xs uppercase tracking-[0.14em] text-slate-400">{label}</p>
      <p className={`mt-2 font-display text-2xl font-bold md:text-3xl ${tone}`}>{value}</p>
      {sub ? <p className="mt-1 text-sm text-slate-300">{sub}</p> : null}
    </article>
  );
}

export function Notice({ tone = "amber", children }) {
  const tones = {
    amber: "border-amber-500/40 bg-amber-950/30 text-amber-200",
    rose: "border-rose-500/40 bg-rose-950/40 text-rose-200",
    slate: "border-slate-600 bg-slate-900/60 text-slate-300",
  };
  return <div className={`mb-4 rounded-xl border px-4 py-3 text-sm ${tones[tone]}`}>{children}</div>;
}

export function EmptyChart({ label }) {
  return <div className="flex h-full items-center justify-center text-sm text-slate-400">{label}</div>;
}
