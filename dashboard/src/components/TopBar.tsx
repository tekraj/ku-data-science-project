export function TopBar({ hours, setHours, onLogout, rightLink }) {
  return (
    <>
      {setHours ? (
        <>
          <label className="text-xs uppercase tracking-widest text-slate-400" htmlFor="window-select">
            Window
          </label>
          <select
            id="window-select"
            className="rounded-xl border border-slate-600 bg-slate-900/70 px-3 py-2 text-sm text-slate-100"
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
          >
            <option value={6}>6h</option>
            <option value={12}>12h</option>
            <option value={24}>24h</option>
            <option value={72}>72h</option>
            <option value={168}>7d</option>
            <option value={87600}>All Time</option>
          </select>
        </>
      ) : null}
      {rightLink}
      <button className="btn-ghost" onClick={onLogout} type="button">
        Sign Out
      </button>
    </>
  );
}
