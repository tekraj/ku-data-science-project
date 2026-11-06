import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AppShell } from "../components/AppShell";
import { NavLinks } from "../components/NavLinks";
import { EmptyChart, Notice, Panel } from "../components/Panel";
import { TopBar } from "../components/TopBar";
import { AXIS, COLORS, GRID, TOOLTIP } from "../lib/chart";
import { axisDay, formatCompact, formatDate, formatDay, formatNumber, formatPct, shortTime, trendColor } from "../lib/format";
import { useApi, useLogout } from "../lib/useApi";

const RANGES = [
  { days: 30, label: "1M" },
  { days: 90, label: "3M" },
  { days: 180, label: "6M" },
  { days: 365, label: "1Y" },
  { days: 1825, label: "5Y" },
  { days: 0, label: "Max" },
];
const THRESHOLDS = [0.1, 0.15, 0.2, 0.3];

export function MarketPage() {
  const onLogout = useLogout();
  const [indexName, setIndexName] = useState("NEPSE");
  const [days, setDays] = useState(365);
  const [threshold, setThreshold] = useState(0.2);
  const [day, setDay] = useState("");

  const indices = useApi("/dashboard/market/indices", 60000);
  const daily = useApi(
    `/dashboard/market/index-daily?index_name=${encodeURIComponent(indexName)}&days=${days}&threshold=${threshold}`,
  );
  const intraday = useApi(
    `/dashboard/market/index-intraday?index_name=${encodeURIComponent(indexName)}${day ? `&date=${day}` : ""}`,
    day ? 0 : 60000,
  );

  const list = indices.data?.indices || [];
  const points = daily.data?.points || [];
  const episodes = daily.data?.episodes || [];
  const longSpan = days === 0 || days > 400;
  const firstDate = points[0]?.date;
  const lastDate = points[points.length - 1]?.date;
  const last = points[points.length - 1];
  const hasTransactions = points.some((p) => p.transactions);

  // Shade each drawdown episode from its peak to its recovery (or the
  // window's end while it's still open), clipped to the visible window.
  const shaded = useMemo(
    () =>
      episodes
        .map((e) => ({
          ...e,
          x1: e.peak_date < firstDate ? firstDate : e.peak_date,
          x2: !e.recovery_date || e.recovery_date > lastDate ? lastDate : e.recovery_date,
        }))
        .filter((e) => firstDate && e.x1 <= e.x2),
    [episodes, firstDate, lastDate],
  );

  const intradayPoints = intraday.data?.points || [];
  const prevClose = intraday.data?.prev_close;
  const errors = [indices.error, daily.error, intraday.error].filter(Boolean);
  const dayTick = (v) => axisDay(v, longSpan);

  return (
    <AppShell
      title="Market"
      subtitle="Official daily index history with drawdowns, volatility and turnover, plus each session's intraday path"
      actions={<TopBar onLogout={onLogout} rightLink={<NavLinks />} />}
    >
      {errors.map((e) => (
        <Notice key={e} tone="rose">{e}</Notice>
      ))}

      <section className="panel mb-4 overflow-x-auto">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="font-display text-xl font-semibold">All Indices</h3>
          <span className="text-xs text-slate-400">live tick during a session, else the official close · click to chart</span>
        </div>
        <div className="grid min-w-[640px] grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
          {list.map((idx) => (
            <button
              key={idx.index_name}
              type="button"
              onClick={() => setIndexName(idx.index_name)}
              className={`rounded-xl border px-3 py-2 text-left transition ${
                idx.index_name === indexName
                  ? "border-cyan-300 bg-cyan-500/15"
                  : "border-slate-700 bg-slate-900/60 hover:border-slate-500"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-xs text-slate-400">{idx.index_name}</span>
                {idx.live ? <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-emerald-400" title="live" /> : null}
              </div>
              <div className="font-display text-lg font-semibold text-slate-100">{formatNumber(idx.value, 2)}</div>
              <div className={`text-xs ${trendColor(idx.percent_change)}`}>{formatPct(idx.percent_change, 2, true)}</div>
            </button>
          ))}
        </div>
      </section>

      <section className="panel mb-4 flex flex-wrap items-end gap-4">
        <div>
          <label className="mb-1 block text-xs uppercase tracking-widest text-slate-400" htmlFor="m-index">Index</label>
          <select
            id="m-index"
            className="rounded-xl border border-slate-600 bg-slate-900/70 px-3 py-2 text-sm text-slate-100"
            value={indexName}
            onChange={(e) => setIndexName(e.target.value)}
          >
            {list.map((idx) => (
              <option key={idx.index_name} value={idx.index_name}>
                {idx.index_name} (since {idx.first_date?.slice(0, 4)})
              </option>
            ))}
          </select>
        </div>
        <div>
          <span className="mb-1 block text-xs uppercase tracking-widest text-slate-400">Range</span>
          <div className="flex gap-1">
            {RANGES.map((r) => (
              <button
                key={r.label}
                type="button"
                onClick={() => setDays(r.days)}
                className={`rounded-lg border px-3 py-1.5 text-sm ${
                  r.days === days ? "border-cyan-300 bg-cyan-500/20 text-cyan-200" : "border-slate-600 bg-slate-800/80 text-slate-200"
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
        <div>
          <label className="mb-1 block text-xs uppercase tracking-widest text-slate-400" htmlFor="m-thr">Crash threshold</label>
          <select
            id="m-thr"
            className="rounded-xl border border-slate-600 bg-slate-900/70 px-3 py-2 text-sm text-slate-100"
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
          >
            {THRESHOLDS.map((t) => (
              <option key={t} value={t}>{`≥ ${t * 100}% drawdown`}</option>
            ))}
          </select>
        </div>
        {last ? (
          <div className="ml-auto text-right text-sm text-slate-300">
            <div>
              Last close <span className="font-semibold text-slate-100">{formatNumber(last.close, 2)}</span> on {formatDay(last.date)}
            </div>
            <div>
              Drawdown <span className="text-rose-300">{formatPct(last.drawdown_pct, 1)}</span> · 20-session vol{" "}
              <span className="text-amber-300">{formatPct(last.vol_20, 1)}</span>
            </div>
          </div>
        ) : null}
      </section>

      <section className="grid gap-3">
        <Panel
          title={`${indexName} Close`}
          note={`${points.length} sessions · shaded: drawdowns deeper than ${threshold * 100}% (peak → recovery) · dashed: running peak`}
          height="h-96"
        >
          {points.length === 0 ? (
            <EmptyChart label={daily.loading ? "Loading…" : "No daily history."} />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={points}>
                <defs>
                  <linearGradient id="mCloseFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={COLORS.teal} stopOpacity={0.45} />
                    <stop offset="95%" stopColor={COLORS.teal} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
                <XAxis dataKey="date" tickFormatter={dayTick} minTickGap={36} stroke={AXIS} />
                <YAxis domain={["auto", "auto"]} stroke={AXIS} width={64} />
                <Tooltip
                  {...TOOLTIP}
                  labelFormatter={(v) => formatDay(v)}
                  formatter={(v, name) => [formatNumber(v, 2), name]}
                />
                {shaded.map((e) => (
                  <ReferenceArea key={e.peak_date} x1={e.x1} x2={e.x2} fill={COLORS.red} fillOpacity={0.08} ifOverflow="hidden" />
                ))}
                <Area type="monotone" dataKey="close" name="Close" stroke={COLORS.teal} fill="url(#mCloseFill)" strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line type="stepAfter" dataKey="running_peak" name="Running peak" stroke={COLORS.slate} strokeDasharray="4 3" strokeWidth={1} dot={false} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </Panel>

        <div className="grid gap-3 xl:grid-cols-2">
          <Panel title="Drawdown from Peak" note="close / running all-time peak − 1" height="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={points}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
                <XAxis dataKey="date" tickFormatter={dayTick} minTickGap={36} stroke={AXIS} />
                <YAxis stroke={AXIS} tickFormatter={(v) => `${v}%`} width={52} />
                <Tooltip {...TOOLTIP} labelFormatter={(v) => formatDay(v)} formatter={(v) => [formatPct(v, 2), "Drawdown"]} />
                <ReferenceLine y={-threshold * 100} stroke={COLORS.red} strokeDasharray="4 3" />
                <Area type="monotone" dataKey="drawdown_pct" stroke={COLORS.red} fill={COLORS.red} fillOpacity={0.25} dot={false} isAnimationActive={false} />
              </AreaChart>
            </ResponsiveContainer>
          </Panel>

          <Panel title="Returns & Realised Volatility" note="daily log return (bars) · 20-session volatility, annualised √240 (line)" height="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={points}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
                <XAxis dataKey="date" tickFormatter={dayTick} minTickGap={36} stroke={AXIS} />
                <YAxis yAxisId="r" stroke={AXIS} tickFormatter={(v) => `${v}%`} width={52} />
                <YAxis yAxisId="v" orientation="right" stroke={COLORS.amber} tickFormatter={(v) => `${v}%`} width={52} />
                <Tooltip {...TOOLTIP} labelFormatter={(v) => formatDay(v)} formatter={(v, name) => [formatPct(v, 2), name]} />
                <Bar yAxisId="r" dataKey="log_return_pct" name="Log return" fill={COLORS.blue} isAnimationActive={false} />
                <Line yAxisId="v" type="monotone" dataKey="vol_20" name="Vol (20)" stroke={COLORS.amber} strokeWidth={1.75} dot={false} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </Panel>
        </div>

        <Panel
          title="Turnover"
          note={hasTransactions ? "NPR traded per session (bars) · number of transactions (line, official sessions only)" : "NPR traded per session"}
          height="h-64"
        >
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={points}>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
              <XAxis dataKey="date" tickFormatter={dayTick} minTickGap={36} stroke={AXIS} />
              <YAxis yAxisId="t" stroke={AXIS} tickFormatter={(v) => formatCompact(v, 1)} width={56} />
              {hasTransactions ? <YAxis yAxisId="n" orientation="right" stroke={COLORS.violet} tickFormatter={(v) => formatCompact(v, 0)} width={48} /> : null}
              <Tooltip
                {...TOOLTIP}
                labelFormatter={(v) => formatDay(v)}
                formatter={(v, name) => [name === "Turnover" ? `NPR ${formatCompact(v, 2)}` : formatNumber(v, 0), name]}
              />
              <Bar yAxisId="t" dataKey="turnover" name="Turnover" fill={COLORS.teal} fillOpacity={0.7} isAnimationActive={false} />
              {hasTransactions ? (
                <Line yAxisId="n" type="monotone" dataKey="transactions" name="Transactions" stroke={COLORS.violet} dot={false} strokeWidth={1.5} isAnimationActive={false} />
              ) : null}
            </ComposedChart>
          </ResponsiveContainer>
        </Panel>

        <Panel
          title={`Intraday · ${intraday.data?.date ? formatDay(intraday.data.date) : "…"}`}
          note={
            intraday.data?.source === "nepalstock_live"
              ? "official 1-minute ticks scraped live · dashed: previous close"
              : intraday.data?.source === "merolagani_ticks"
                ? "merolagani tick history (back to 2018) · dashed: previous close"
                : "no ticks for this session"
          }
          right={
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="btn-ghost px-3 py-1.5 text-sm"
                disabled={!intraday.data?.prev_session}
                onClick={() => setDay(intraday.data?.prev_session)}
              >
                ← Prev
              </button>
              <input
                type="date"
                className="rounded-xl border border-slate-600 bg-slate-900/70 px-3 py-1.5 text-sm text-slate-100"
                value={day || intraday.data?.date || ""}
                onChange={(e) => setDay(e.target.value)}
              />
              <button
                type="button"
                className="btn-ghost px-3 py-1.5 text-sm"
                disabled={!intraday.data?.next_session}
                onClick={() => setDay(intraday.data?.next_session)}
              >
                Next →
              </button>
              <button type="button" className="btn-ghost px-3 py-1.5 text-sm" onClick={() => setDay("")}>
                Latest
              </button>
            </div>
          }
          height="h-80"
        >
          {intradayPoints.length === 0 ? (
            <EmptyChart label={intraday.loading ? "Loading…" : "No intraday ticks for this date (holiday, weekend or before 2018)."} />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={intradayPoints}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
                <XAxis dataKey="t" tickFormatter={shortTime} minTickGap={36} stroke={AXIS} />
                <YAxis domain={["auto", "auto"]} stroke={AXIS} width={64} />
                <Tooltip {...TOOLTIP} labelFormatter={(v) => formatDate(v)} formatter={(v) => [formatNumber(v, 2), indexName]} />
                {prevClose ? (
                  <ReferenceLine y={prevClose} stroke={COLORS.slate} strokeDasharray="4 3" ifOverflow="extendDomain" />
                ) : null}
                <Line type="monotone" dataKey="value" stroke={COLORS.blue} strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </Panel>

        <Panel title="Drawdown Episodes" note={`peak-to-trough falls deeper than ${threshold * 100}% over the index's full history — the thesis' crash labels`}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-slate-700 text-left text-xs uppercase tracking-wide text-slate-400">
                  <th className="px-3 py-2">Peak</th>
                  <th className="px-3 py-2 text-right">Peak value</th>
                  <th className="px-3 py-2">Trough</th>
                  <th className="px-3 py-2 text-right">Trough value</th>
                  <th className="px-3 py-2 text-right">Drawdown</th>
                  <th className="px-3 py-2 text-right">Days to trough</th>
                  <th className="px-3 py-2">Recovered</th>
                </tr>
              </thead>
              <tbody>
                {episodes.map((e) => (
                  <tr key={e.peak_date} className="border-b border-slate-800 text-slate-200">
                    <td className="px-3 py-2">{formatDay(e.peak_date)}</td>
                    <td className="px-3 py-2 text-right">{formatNumber(e.peak, 2)}</td>
                    <td className="px-3 py-2">{formatDay(e.trough_date)}</td>
                    <td className="px-3 py-2 text-right">{formatNumber(e.trough, 2)}</td>
                    <td className="px-3 py-2 text-right text-rose-300">{formatPct(e.drawdown_pct, 1)}</td>
                    <td className="px-3 py-2 text-right">{formatNumber(e.days_to_trough, 0)}</td>
                    <td className="px-3 py-2">{e.recovery_date ? formatDay(e.recovery_date) : <span className="text-amber-300">not yet</span>}</td>
                  </tr>
                ))}
                {!daily.loading && episodes.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-3 py-4 text-slate-400">No drawdown deeper than {threshold * 100}% in this window.</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </Panel>
      </section>
    </AppShell>
  );
}
