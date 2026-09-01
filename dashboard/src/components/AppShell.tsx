export function AppShell({ children, title, subtitle, actions }) {
  return (
    <div className="mx-auto max-w-[1400px] px-3 py-4 md:px-6 md:py-6">
      <header className="panel mb-4 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Nepse Intelligence</p>
          <h1 className="font-display text-3xl font-bold tracking-tight text-slate-100 md:text-5xl">{title}</h1>
          <p className="mt-1 text-slate-300">{subtitle}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">{actions}</div>
      </header>
      {children}
    </div>
  );
}
