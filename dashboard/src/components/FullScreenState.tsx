export function FullScreenState({ label }) {
  return (
    <div className="flex min-h-screen items-center justify-center px-4 text-slate-300">
      <div className="panel flex items-center gap-3 px-6 py-4">
        <span className="h-3 w-3 animate-pulse rounded-full bg-cyan-400" />
        <span>{label}</span>
      </div>
    </div>
  );
}
