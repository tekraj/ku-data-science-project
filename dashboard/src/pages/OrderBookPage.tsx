import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
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
import { formatCompact, formatDate, formatDay, formatNumber, formatPct, shortTime, timeAgo } from "../lib/format";
import { useApi, useLogout } from "../lib/useApi";

// Merge the order-book snapshots (~every 2 min per symbol) with the
// 1-minute last-traded-price series onto one time axis; the chart joins
// across the gaps each series leaves.
function mergeSeries(series, ltp) {
  const rows = new Map();
  for (const s of series) rows.set(s.t, { t: s.t, best_bid: s.best_bid, best_ask: s.best_ask });
  for (const p of ltp) rows.set(p.t, { ...(rows.get(p.t) || { t: p.t }), ltp: p.ltp });
  return [...rows.values()].sort((a, b) => (a.t < b.t ? -1 : 1));
}

export function OrderBookPage() {
  const onLogout = useLogout();
  const symbols = useApi("/dashboard/market/depth-symbols", 120000);
  const [symbol, setSymbol] = useState("");
  const [day, setDay] = useState("");

  const symbolList = symbols.data?.symbols || [];
  useEffect(() => {
    if (!symbol && symbolList.length > 0) {
      setSymbol(symbolList.some((s) => s.symbol === "NABIL") ? "NABIL" : symbolList[0].symbol);
    }
  }, [symbol, symbolList]);

  const depth = useApi(
    symbol ? `/dashboard/market/depth?symbol=${encodeURIComponent(symbol)}${day ? `&date=${day}` : ""}` : null,
    day ? 0 : 60000,
  );
  const series = depth.data?.series || [];
  const ltp = depth.data?.ltp || [];
  const book = depth.data?.latest;
  const merged = useMemo(() => mergeSeries(series, ltp), [series, ltp]);
  const lastSnap = series[series.length - 1];

  // Ladder: asks above (highest first), bids below, so the spread sits in
  // the middle like a trading screen.
  const ladder = useMemo(() => {
    if (!book) return [];
    const asks = [...book.asks].reverse().map((l) => ({ ...l, side: "ask", label: formatNumber(l.price, 2), qty: l.quantity }));
    const bids = book.bids.map((l) => ({ ...l, side: "bid", label: formatNumber(l.price, 2), qty: l.quantity }));
    return [...asks, ...bids];
  }, [book]);

  const errors = [symbols.error, depth.error].filter(Boolean);

  return (
    <AppShell
      title="Order Book"
      subtitle="Bid/ask depth of the 50 most liquid stocks, snapshotted every ~2 minutes during the session"
      actions={<TopBar onLogout={onLogout} rightLink={<NavLinks />} />}
    >
      {errors.map((e) => (
        <Notice key={e} tone="rose">{e}</Notice>
      ))}

      <section className="panel mb-4 flex flex-wrap items-end gap-4">
        <div>
          <label className="mb-1 block text-xs uppercase tracking-widest text-slate-400" htmlFor="ob-symbol">Symbol</label>
          <select
            id="ob-symbol"
            className="rounded-xl border border-slate-600 bg-slate-900/70 px-3 py-2 text-sm text-slate-100"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
          >
            {symbolList.map((s) => (
              <option key={s.symbol} value={s.symbol}>
                {s.symbol} ({s.snapshots} snapshots)
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs uppercase tracking-widest text-slate-400" htmlFor="ob-day">Session</label>
          <input
            id="ob-day"
            type="date"
            className="rounded-xl border border-slate-600 bg-slate-900/70 px-3 py-2 text-sm text-slate-100"
            value={day || depth.data?.date || ""}
            onChange={(e) => setDay(e.target.value)}
          />
        </div>
        <button type="button" className="btn-ghost" onClick={() => setDay("")}>Latest</button>
        <div className="ml-auto text-sm text-slate-400">
          {book ? `Latest snapshot ${formatDate(book.t)} (${timeAgo(book.t)})` : depth.loading ? "Loading…" : ""}
        </div>
      </section>

      {!depth.loading && symbol && series.length === 0 ? (
        <Notice>No order-book snapshots for {symbol} on {formatDay(depth.data?.date)}. Depth is collected only during sessions, for the 50 most liquid stocks of the day.</Notice>
      ) : null}

      <section className="mb-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Metric label="Best bid / ask" value={lastSnap ? `${formatNumber(lastSnap.best_bid, 2)} / ${formatNumber(lastSnap.best_ask, 2)}` : "-"} />
        <Metric label="Spread" value={formatPct(lastSnap?.spread_pct, 3)} sub="of mid price" />
        <Metric
          label="Order imbalance"
          value={lastSnap?.imbalance != null ? formatNumber(lastSnap.imbalance, 3) : "-"}
          sub="(buy − sell) / (buy + sell) resting qty"
          tone={lastSnap?.imbalance > 0 ? "text-emerald-300" : lastSnap?.imbalance < 0 ? "text-rose-300" : "text-slate-100"}
        />
        <Metric
          label="Resting buy / sell qty"
          value={lastSnap ? `${formatCompact(lastSnap.total_buy_qty, 1)} / ${formatCompact(lastSnap.total_sell_qty, 1)}` : "-"}
          sub="whole book, all price levels"
        />
      </section>

      <section className="grid gap-3 xl:grid-cols-[1fr_1.6fr]">
        <Panel title="Depth Ladder" note="top 5 levels each side at the latest snapshot" height="h-96">
          {ladder.length === 0 ? (
            <EmptyChart label="No snapshot." />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={ladder} layout="vertical" margin={{ left: 8, right: 16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
                <XAxis type="number" stroke={AXIS} tickFormatter={(v) => formatCompact(v, 1)} />
                <YAxis type="category" dataKey="label" stroke={AXIS} width={64} />
                <Tooltip
                  {...TOOLTIP}
                  formatter={(v, _n, item) => [`${formatNumber(v, 0)} shares · ${item.payload.orders} orders`, item.payload.side === "bid" ? "Bid" : "Ask"]}
                />
                <Bar dataKey="qty" isAnimationActive={false} radius={[0, 6, 6, 0]}>
                  {ladder.map((l, i) => (
                    <Cell key={i} fill={l.side === "bid" ? COLORS.green : COLORS.red} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </Panel>

        <Panel title="Best Bid / Ask vs Last Traded Price" note="order-book snapshots and the 1-minute LTP" height="h-96">
          {merged.length === 0 ? (
            <EmptyChart label="No data." />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={merged}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
                <XAxis dataKey="t" tickFormatter={shortTime} minTickGap={36} stroke={AXIS} />
                <YAxis domain={["auto", "auto"]} stroke={AXIS} width={60} />
                <Tooltip {...TOOLTIP} labelFormatter={(v) => formatDate(v)} formatter={(v, name) => [formatNumber(v, 2), name]} />
                <Legend />
                <Line type="stepAfter" dataKey="best_bid" name="Best bid" stroke={COLORS.green} dot={false} connectNulls isAnimationActive={false} />
                <Line type="stepAfter" dataKey="best_ask" name="Best ask" stroke={COLORS.red} dot={false} connectNulls isAnimationActive={false} />
                <Line type="monotone" dataKey="ltp" name="LTP" stroke={COLORS.amber} strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </Panel>
      </section>

      <section className="mt-3 grid gap-3 xl:grid-cols-2">
        <Panel title="Order Imbalance" note="(buy − sell) / (buy + sell) of the whole book's resting quantity" height="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={series}>
              <defs>
                <linearGradient id="obImb" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={COLORS.green} stopOpacity={0.5} />
                  <stop offset="50%" stopColor={COLORS.green} stopOpacity={0.05} />
                  <stop offset="50%" stopColor={COLORS.red} stopOpacity={0.05} />
                  <stop offset="100%" stopColor={COLORS.red} stopOpacity={0.5} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
              <XAxis dataKey="t" tickFormatter={shortTime} minTickGap={36} stroke={AXIS} />
              <YAxis domain={[-1, 1]} stroke={AXIS} width={44} />
              <Tooltip {...TOOLTIP} labelFormatter={(v) => formatDate(v)} formatter={(v) => [formatNumber(v, 3), "Imbalance"]} />
              <ReferenceLine y={0} stroke={AXIS} />
              <Area type="monotone" dataKey="imbalance" stroke={COLORS.teal} fill="url(#obImb)" dot={false} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        </Panel>

        <Panel title="Spread & Top-5 Depth" note="bid-ask spread in % of mid (line) · quantity resting in the top 5 levels" height="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={series}>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
              <XAxis dataKey="t" tickFormatter={shortTime} minTickGap={36} stroke={AXIS} />
              <YAxis yAxisId="q" stroke={AXIS} tickFormatter={(v) => formatCompact(v, 1)} width={52} />
              <YAxis yAxisId="s" orientation="right" stroke={COLORS.amber} tickFormatter={(v) => `${formatNumber(v, 2)}%`} width={56} />
              <Tooltip
                {...TOOLTIP}
                labelFormatter={(v) => formatDate(v)}
                formatter={(v, name) => [name === "Spread" ? formatPct(v, 3) : formatNumber(v, 0), name]}
              />
              <Legend />
              <Line yAxisId="q" type="monotone" dataKey="bid_depth5" name="Bid depth (5)" stroke={COLORS.green} dot={false} isAnimationActive={false} />
              <Line yAxisId="q" type="monotone" dataKey="ask_depth5" name="Ask depth (5)" stroke={COLORS.red} dot={false} isAnimationActive={false} />
              <Line yAxisId="s" type="monotone" dataKey="spread_pct" name="Spread" stroke={COLORS.amber} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </Panel>
      </section>
    </AppShell>
  );
}
