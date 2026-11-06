import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AppShell } from "../components/AppShell";
import { NavLinks } from "../components/NavLinks";
import { EmptyChart, Metric, Notice, Panel } from "../components/Panel";
import { TopBar } from "../components/TopBar";
import { AXIS, COLORS, GRID, TOOLTIP } from "../lib/chart";
import { axisDay, formatCompact, formatDate, formatDay, formatNumber, formatPct, shortTime } from "../lib/format";
import { useApi, useLogout } from "../lib/useApi";

const SESSION_OPTIONS = [30, 60, 120, 250];

function brokerLabel(b) {
  if (!b.name) return `#${b.id}`;
  return `${b.id} ${b.name.length > 22 ? `${b.name.slice(0, 21)}…` : b.name}`;
}

export function BrokersPage() {
  const onLogout = useLogout();
  const [day, setDay] = useState("");
  const [symbolInput, setSymbolInput] = useState("");
  const [symbol, setSymbol] = useState("");
  const [sessions, setSessions] = useState(60);

  const summary = useApi(
    `/dashboard/floorsheet/summary?symbol=${encodeURIComponent(symbol)}${day ? `&date=${day}` : ""}`,
    day ? 0 : 120000,
  );
  const concentration = useApi(`/dashboard/floorsheet/concentration?sessions=${sessions}&symbol=${encodeURIComponent(symbol)}`);
  const coverage = useApi("/dashboard/floorsheet/coverage", 600000);

  const s = summary.data;
  const totals = s?.totals;
  const brokers = s?.brokers || [];
  const topGross = useMemo(() => brokers.slice(0, 15).map((b) => ({ ...b, label: brokerLabel(b) })), [brokers]);
  const netFlow = useMemo(() => {
    const sorted = [...brokers].sort((a, b) => b.net_amount - a.net_amount);
    const buyers = sorted.slice(0, 8);
    const sellers = sorted.slice(-8).filter((b) => !buyers.includes(b));
    return [...buyers, ...sellers].map((b) => ({ ...b, label: brokerLabel(b) }));
  }, [brokers]);
  const months = coverage.data?.months || [];
  const coverageRows = useMemo(
    () =>
      months.map((m) => ({
        ...m,
        brokers: m.with_brokers,
        no_brokers: m.with_trades - m.with_brokers,
        missing: m.sessions - m.with_trades,
      })),
    [months],
  );
  const cov = coverage.data?.totals;
  const brokerCoverage = totals?.trades ? (totals.with_broker / totals.trades) * 100 : null;

  function applySymbol(e) {
    e.preventDefault();
    setSymbol(symbolInput.trim().toUpperCase());
  }

  const errors = [summary.error, concentration.error, coverage.error].filter(Boolean);

  return (
    <AppShell
      title="Brokers"
      subtitle="Every trade with its buying and selling broker: flows, concentration and trade sizes per session"
      actions={<TopBar onLogout={onLogout} rightLink={<NavLinks />} />}
    >
      {errors.map((e) => (
        <Notice key={e} tone="rose">{e}</Notice>
      ))}

      <section className="panel mb-4 flex flex-wrap items-end gap-3">
        <div>
          <span className="mb-1 block text-xs uppercase tracking-widest text-slate-400">Session</span>
          <div className="flex items-center gap-2">
            <button type="button" className="btn-ghost px-3 py-2 text-sm" disabled={!s?.prev_session} onClick={() => setDay(s?.prev_session)}>
              ←
            </button>
            <input
              type="date"
              className="rounded-xl border border-slate-600 bg-slate-900/70 px-3 py-2 text-sm text-slate-100"
              value={day || s?.date || ""}
              onChange={(e) => setDay(e.target.value)}
            />
            <button type="button" className="btn-ghost px-3 py-2 text-sm" disabled={!s?.next_session} onClick={() => setDay(s?.next_session)}>
              →
            </button>
            <button type="button" className="btn-ghost px-3 py-2 text-sm" onClick={() => setDay("")}>
              Latest
            </button>
          </div>
        </div>
        <form onSubmit={applySymbol}>
          <label className="mb-1 block text-xs uppercase tracking-widest text-slate-400" htmlFor="b-symbol">Symbol (blank = whole market)</label>
          <div className="flex gap-2">
            <input
              id="b-symbol"
              list="b-symbols"
              className="w-36 rounded-xl border border-slate-600 bg-slate-900/70 px-3 py-2 text-sm uppercase text-slate-100"
              value={symbolInput}
              onChange={(e) => setSymbolInput(e.target.value)}
              placeholder="e.g. NABIL"
            />
            <datalist id="b-symbols">
              {(s?.symbols || []).map((x) => (
                <option key={x.symbol} value={x.symbol} />
              ))}
            </datalist>
            <button type="submit" className="btn-ghost px-3 py-2 text-sm">Apply</button>
            {symbol ? (
              <button type="button" className="btn-ghost px-3 py-2 text-sm" onClick={() => { setSymbol(""); setSymbolInput(""); }}>
                Clear
              </button>
            ) : null}
          </div>
        </form>
        <div className="ml-auto text-sm text-slate-400">{summary.loading ? "Loading…" : s?.date ? `${formatDay(s.date)}${symbol ? ` · ${symbol}` : ""}` : ""}</div>
      </section>

      {totals && totals.trades === 0 ? (
        <Notice>No trades stored for {symbol || "the market"} on {formatDay(s?.date)} — not a session, or its broker history hasn't been backfilled yet (see coverage below).</Notice>
      ) : null}
      {totals && totals.trades > 0 && brokerCoverage < 90 ? (
        <Notice>
          Only {formatPct(brokerCoverage, 1)} of this session's trades have broker ids yet. Live sessions get them from the post-close sweep;
          older ones from the merolagani history backfill.
        </Notice>
      ) : null}

      <section className="mb-4 grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Metric label="Trades" value={formatNumber(totals?.trades, 0)} sub={`${formatNumber(totals?.symbols, 0)} symbols`} />
        <Metric label="Turnover" value={`NPR ${formatCompact(totals?.amount, 2)}`} sub={`${formatCompact(totals?.quantity, 2)} shares`} />
        <Metric label="Active brokers" value={formatNumber(totals?.brokers, 0)} sub={`broker ids on ${formatPct(brokerCoverage, 1)} of trades`} />
        <Metric label="Top-5 buy share" value={formatPct(totals?.top5_buy_share, 1)} sub="of buy turnover" />
        <Metric label="Top-5 sell share" value={formatPct(totals?.top5_sell_share, 1)} sub="of sell turnover" />
        <Metric label="Buy-side HHI" value={formatNumber(totals?.hhi_buy, 4)} sub={totals?.hhi_buy ? `≈ ${formatNumber(1 / totals.hhi_buy, 0)} equal-sized brokers` : null} />
      </section>

      <section className="grid gap-3 xl:grid-cols-2">
        <Panel title="Top 15 Brokers by Turnover" note="buy and sell amount (NPR)" height="h-[30rem]">
          {topGross.length === 0 ? (
            <EmptyChart label="No broker data." />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={topGross} layout="vertical" margin={{ left: 8, right: 16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
                <XAxis type="number" stroke={AXIS} tickFormatter={(v) => formatCompact(v, 1)} />
                <YAxis type="category" dataKey="label" stroke={AXIS} width={170} tick={{ fontSize: 11 }} interval={0} />
                <Tooltip {...TOOLTIP} labelFormatter={(_l, p) => p?.[0]?.payload?.name || _l} formatter={(v, name) => [`NPR ${formatCompact(v, 2)}`, name]} />
                <Legend />
                <Bar dataKey="buy_amount" name="Buy" fill={COLORS.green} isAnimationActive={false} />
                <Bar dataKey="sell_amount" name="Sell" fill={COLORS.red} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Panel>

        <Panel title="Net Broker Flow" note="buy − sell amount: the 8 largest net buyers and net sellers" height="h-[30rem]">
          {netFlow.length === 0 ? (
            <EmptyChart label="No broker data." />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={netFlow} layout="vertical" margin={{ left: 8, right: 16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
                <XAxis type="number" stroke={AXIS} tickFormatter={(v) => formatCompact(v, 1)} />
                <YAxis type="category" dataKey="label" stroke={AXIS} width={170} tick={{ fontSize: 11 }} interval={0} />
                <Tooltip {...TOOLTIP} labelFormatter={(_l, p) => p?.[0]?.payload?.name || _l} formatter={(v) => [`NPR ${formatCompact(v, 2)}`, "Net"]} />
                <ReferenceLine x={0} stroke={AXIS} />
                <Bar dataKey="net_amount" isAnimationActive={false}>
                  {netFlow.map((b) => (
                    <Cell key={b.id} fill={b.net_amount >= 0 ? COLORS.green : COLORS.red} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </Panel>
      </section>

      <section className="mt-3 grid gap-3 xl:grid-cols-[1.6fr_1fr]">
        <Panel
          title="Intraday Activity"
          note={symbol ? "trades per minute (bars) · VWAP per minute (line)" : "trades per minute (bars) · turnover per minute (line)"}
          height="h-72"
        >
          {(s?.minutes || []).length === 0 ? (
            <EmptyChart
              label={totals?.trades ? "No trade times for this session — merolagani's history doesn't publish them (only live-scraped sessions since 2026-09 have them)." : "No trades."}
            />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={s.minutes}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
                <XAxis dataKey="t" tickFormatter={shortTime} minTickGap={36} stroke={AXIS} />
                <YAxis yAxisId="n" stroke={AXIS} width={44} />
                <YAxis
                  yAxisId="v"
                  orientation="right"
                  stroke={COLORS.amber}
                  domain={["auto", "auto"]}
                  tickFormatter={(v) => (symbol ? formatNumber(v, 1) : formatCompact(v, 1))}
                  width={56}
                />
                <Tooltip
                  {...TOOLTIP}
                  labelFormatter={(v) => formatDate(v)}
                  formatter={(v, name) => [name === "Trades" ? formatNumber(v, 0) : name === "VWAP" ? formatNumber(v, 2) : `NPR ${formatCompact(v, 2)}`, name]}
                />
                <Bar yAxisId="n" dataKey="trades" name="Trades" fill={COLORS.blue} fillOpacity={0.75} isAnimationActive={false} />
                <Line
                  yAxisId="v"
                  type="monotone"
                  dataKey={symbol ? "vwap" : "amount"}
                  name={symbol ? "VWAP" : "Turnover"}
                  stroke={COLORS.amber}
                  dot={false}
                  strokeWidth={1.75}
                  isAnimationActive={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </Panel>

        <Panel title="Trade Size Mix" note="share of trades vs share of turnover, by trade value (NPR)" height="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={s?.sizes || []}>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
              <XAxis dataKey="bucket" stroke={AXIS} tick={{ fontSize: 11 }} interval={0} />
              <YAxis stroke={AXIS} tickFormatter={(v) => `${v}%`} width={44} />
              <Tooltip {...TOOLTIP} formatter={(v, name) => [formatPct(v, 1), name]} />
              <Legend />
              <Bar dataKey="trades_pct" name="% of trades" fill={COLORS.blue} isAnimationActive={false} />
              <Bar dataKey="amount_pct" name="% of turnover" fill={COLORS.amber} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </Panel>
      </section>

      <section className="mt-3">
        <Panel
          title="Broker Concentration"
          note="per session: top-5 brokers' share of buy and sell turnover · buy-side Herfindahl index (right axis) · gaps = broker ids not backfilled yet"
          right={
            <select
              className="rounded-xl border border-slate-600 bg-slate-900/70 px-3 py-1.5 text-sm text-slate-100"
              value={sessions}
              onChange={(e) => setSessions(Number(e.target.value))}
            >
              {SESSION_OPTIONS.map((n) => (
                <option key={n} value={n}>{`last ${n} sessions`}</option>
              ))}
            </select>
          }
          height="h-72"
        >
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={concentration.data?.points || []}>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
              <XAxis dataKey="date" tickFormatter={(v) => axisDay(v, sessions > 120)} minTickGap={36} stroke={AXIS} />
              <YAxis yAxisId="p" stroke={AXIS} tickFormatter={(v) => `${v}%`} width={44} domain={[0, "auto"]} />
              <YAxis yAxisId="h" orientation="right" stroke={COLORS.violet} width={52} tickFormatter={(v) => formatNumber(v, 3)} />
              <Tooltip
                {...TOOLTIP}
                labelFormatter={(v) => formatDay(v)}
                formatter={(v, name) => [name === "HHI (buy)" ? formatNumber(v, 4) : formatPct(v, 1), name]}
              />
              <Legend />
              <Line yAxisId="p" type="monotone" dataKey="top5_buy_share" name="Top-5 buy share" stroke={COLORS.green} dot={false} isAnimationActive={false} />
              <Line yAxisId="p" type="monotone" dataKey="top5_sell_share" name="Top-5 sell share" stroke={COLORS.red} dot={false} isAnimationActive={false} />
              <Line yAxisId="h" type="monotone" dataKey="hhi_buy" name="HHI (buy)" stroke={COLORS.violet} dot={false} strokeDasharray="4 3" isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </Panel>
      </section>

      <section className="mt-3 grid gap-3 xl:grid-cols-[1.6fr_1fr]">
        <Panel title="Broker Table" note="every broker active in this session, by gross turnover">
          <div className="max-h-[26rem] overflow-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="sticky top-0 bg-slate-900">
                <tr className="border-b border-slate-700 text-left text-xs uppercase tracking-wide text-slate-400">
                  <th className="px-3 py-2">Broker</th>
                  <th className="px-3 py-2 text-right">Buy (NPR)</th>
                  <th className="px-3 py-2 text-right">Sell (NPR)</th>
                  <th className="px-3 py-2 text-right">Net (NPR)</th>
                  <th className="px-3 py-2 text-right">Trades b/s</th>
                </tr>
              </thead>
              <tbody>
                {brokers.map((b) => (
                  <tr key={b.id} className="border-b border-slate-800 text-slate-200">
                    <td className="px-3 py-1.5">
                      <span className="text-slate-400">{b.id}</span> {b.name || ""}
                    </td>
                    <td className="px-3 py-1.5 text-right">{formatCompact(b.buy_amount, 2)}</td>
                    <td className="px-3 py-1.5 text-right">{formatCompact(b.sell_amount, 2)}</td>
                    <td className={`px-3 py-1.5 text-right ${b.net_amount >= 0 ? "text-emerald-300" : "text-rose-300"}`}>{formatCompact(b.net_amount, 2)}</td>
                    <td className="px-3 py-1.5 text-right">
                      {formatNumber(b.buy_trades, 0)} / {formatNumber(b.sell_trades, 0)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-slate-500">Names are each id's most recent name; brokers have renamed and merged over the years.</p>
        </Panel>

        <Panel title="Most Traded Symbols" note={symbol ? "clear the symbol filter to see the market's top symbols" : "by turnover this session · click to filter"}>
          <div className="max-h-[26rem] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-slate-900">
                <tr className="border-b border-slate-700 text-left text-xs uppercase tracking-wide text-slate-400">
                  <th className="px-3 py-2">Symbol</th>
                  <th className="px-3 py-2 text-right">Turnover</th>
                  <th className="px-3 py-2 text-right">Trades</th>
                  <th className="px-3 py-2 text-right">VWAP</th>
                </tr>
              </thead>
              <tbody>
                {(s?.symbols || []).map((x) => (
                  <tr
                    key={x.symbol}
                    className="cursor-pointer border-b border-slate-800 text-slate-200 hover:bg-slate-800/60"
                    onClick={() => { setSymbol(x.symbol); setSymbolInput(x.symbol); }}
                  >
                    <td className="px-3 py-1.5 font-medium">{x.symbol}</td>
                    <td className="px-3 py-1.5 text-right">{formatCompact(x.amount, 2)}</td>
                    <td className="px-3 py-1.5 text-right">{formatNumber(x.trades, 0)}</td>
                    <td className="px-3 py-1.5 text-right">{formatNumber(x.vwap, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </section>

      <section className="mt-3">
        <Panel
          title="Dataset Coverage"
          note={
            cov
              ? `${formatNumber(cov.with_brokers, 0)} of ${formatNumber(cov.sessions, 0)} sessions since ${formatDay(coverage.data.first_session)} have broker ids · ${formatCompact(cov.trades_with_broker, 1)} trades with broker ids` +
                (coverage.data.backfill ? ` · history backfill last filled ${formatDay(coverage.data.backfill.last_session)} (${formatDate(coverage.data.backfill.last_run_at)})` : "")
              : "sessions per month"
          }
          height="h-72"
        >
          {coverageRows.length === 0 ? (
            <EmptyChart label={coverage.loading ? "Counting every stored trade (takes a few seconds)…" : "No data."} />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={coverageRows}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
                <XAxis dataKey="month" stroke={AXIS} minTickGap={24} />
                <YAxis stroke={AXIS} width={36} />
                <Tooltip {...TOOLTIP} formatter={(v, name) => [formatNumber(v, 0), name]} />
                <Legend />
                <Bar dataKey="brokers" name="With broker ids" stackId="s" fill={COLORS.green} isAnimationActive={false} />
                <Bar dataKey="no_brokers" name="Trades without broker ids" stackId="s" fill={COLORS.amber} isAnimationActive={false} />
                <Bar dataKey="missing" name="Not stored yet" stackId="s" fill="#475569" isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Panel>
      </section>
    </AppShell>
  );
}
