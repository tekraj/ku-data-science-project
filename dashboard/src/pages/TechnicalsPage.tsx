import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Area,
  Bar,
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
import { apiRequest } from "../lib/api";
import { formatNumber } from "../lib/format";
import { AppShell } from "../components/AppShell";
import { TopBar } from "../components/TopBar";

const WINDOW_OPTIONS = [
  { value: 90, label: "90d" },
  { value: 180, label: "180d" },
  { value: 365, label: "1y" },
  { value: 730, label: "2y" },
];

// The backend returns plain "YYYY-MM-DD" strings for point dates (not full
// timestamps), so we use them directly as the tooltip/axis label instead of
// piping through formatDate — formatDate applies the Asia/Kathmandu timezone
// offset to a Date parsed from the string, which (being UTC midnight) would
// roll over to the next calendar day and misrepresent the point's date.
function formatPointDate(dateString) {
  return dateString || "-";
}

export function TechnicalsPage() {
  const navigate = useNavigate();

  const [indices, setIndices] = useState([]);
  const [indexName, setIndexName] = useState("");
  const [days, setDays] = useState(365);
  const [indicatorData, setIndicatorData] = useState(null);
  const [loadingIndices, setLoadingIndices] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function onLogout() {
    try {
      await apiRequest("/auth/logout", { method: "POST" });
    } finally {
      navigate("/login", { replace: true });
    }
  }

  // Load the list of available indices once, then pick a sensible default.
  useEffect(() => {
    let active = true;
    setLoadingIndices(true);

    apiRequest("/dashboard/indices")
      .then((d) => {
        if (!active) return;
        const list = d.indices || [];
        setIndices(list);
        setIndexName((prev) => {
          if (prev && list.some((i) => i.index_name === prev)) return prev;
          const nepse = list.find((i) => i.index_name === "NEPSE");
          if (nepse) return nepse.index_name;
          return list.length > 0 ? list[0].index_name : "";
        });
      })
      .catch((e) => {
        if (!active) return;
        if (e.status === 401) {
          navigate("/login", { replace: true });
          return;
        }
        setError("Unable to load index list.");
      })
      .finally(() => {
        if (active) setLoadingIndices(false);
      });

    return () => {
      active = false;
    };
  }, [navigate]);

  // Load indicators whenever the selected index or window changes.
  useEffect(() => {
    if (!indexName) return;
    let active = true;
    setLoading(true);
    setError("");

    apiRequest(`/dashboard/indicators?index_name=${encodeURIComponent(indexName)}&days=${days}`)
      .then((d) => {
        if (!active) return;
        setIndicatorData(d);
      })
      .catch((e) => {
        if (!active) return;
        if (e.status === 401) {
          navigate("/login", { replace: true });
          return;
        }
        setError("Unable to load technical indicators.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [indexName, days, navigate]);

  const points = indicatorData?.points || [];
  const daysAvailable = indicatorData?.days_available ?? null;

  return (
    <AppShell
      title="Technical Analysis"
      subtitle="SMA, EMA, MACD, RSI and Bollinger Band indicators derived from daily closing values"
      actions={
        <TopBar
          onLogout={onLogout}
          rightLink={
            <>
              <Link className="btn-ghost" to="/">Dashboard</Link>
              <Link className="btn-ghost" to="/news">News</Link>
              <Link className="btn-ghost" to="/logs">Run Logs</Link>
            </>
          }
        />
      }
    >
      {error && <div className="mb-4 rounded-xl border border-rose-500/40 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">{error}</div>}

      {/* Header controls */}
      <section className="panel mb-4 flex flex-wrap items-end gap-3">
        <div>
          <label className="mb-1 block text-xs uppercase tracking-widest text-slate-400" htmlFor="index-select">
            Index
          </label>
          <select
            id="index-select"
            className="rounded-xl border border-slate-600 bg-slate-900/70 px-3 py-2 text-sm text-slate-100"
            value={indexName}
            onChange={(e) => setIndexName(e.target.value)}
            disabled={loadingIndices || indices.length === 0}
          >
            {indices.length === 0 ? (
              <option value="">No indices available</option>
            ) : (
              indices.map((idx) => (
                <option key={idx.index_name} value={idx.index_name}>
                  {idx.index_name} ({idx.distinct_days}d)
                </option>
              ))
            )}
          </select>
        </div>

        <div>
          <label className="mb-1 block text-xs uppercase tracking-widest text-slate-400" htmlFor="days-select">
            Window
          </label>
          <select
            id="days-select"
            className="rounded-xl border border-slate-600 bg-slate-900/70 px-3 py-2 text-sm text-slate-100"
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
          >
            {WINDOW_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        <div className="text-sm text-slate-400">
          {loading ? "Loading…" : `${points.length} points`}
        </div>
      </section>

      {!loading && daysAvailable !== null && daysAvailable < 200 && (
        <div className="mb-4 rounded-xl border border-amber-500/40 bg-amber-950/30 px-4 py-3 text-sm text-amber-200">
          Only {daysAvailable} days of history available for {indexName} — the 200-day moving average will not render until more data accumulates.
        </div>
      )}

      {/* Price + Moving Averages */}
      <section className="panel mb-4">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="font-display text-xl font-semibold">Price &amp; Moving Averages</h3>
          <span className="text-xs text-slate-400">SMA 20 / 50 / 200</span>
        </div>
        <div className="h-96">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={points}>
              <defs>
                <linearGradient id="closeFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#2dd4bf" stopOpacity={0.5} />
                  <stop offset="95%" stopColor="#2dd4bf" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(148, 163, 184, .2)" />
              <XAxis dataKey="date" minTickGap={28} stroke="#94a3b8" />
              <YAxis domain={["auto", "auto"]} stroke="#94a3b8" />
              <Tooltip labelFormatter={(v) => formatPointDate(v)} formatter={(v, name) => [formatNumber(v, 2), name]} />
              <Legend />
              <Area type="monotone" dataKey="close" name="Close" stroke="#2dd4bf" fill="url(#closeFill)" strokeWidth={2.5} dot={false} connectNulls={false} />
              <Line type="monotone" dataKey="sma_20" name="SMA 20" stroke="#fbbf24" strokeWidth={1.75} dot={false} connectNulls={false} />
              <Line type="monotone" dataKey="sma_50" name="SMA 50" stroke="#60a5fa" strokeWidth={1.75} dot={false} connectNulls={false} />
              <Line type="monotone" dataKey="sma_200" name="SMA 200" stroke="#c4b5fd" strokeWidth={1.75} dot={false} connectNulls={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </section>

      {/* Bollinger Bands */}
      <section className="panel mb-4">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="font-display text-xl font-semibold">Bollinger Bands</h3>
          <span className="text-xs text-slate-400">20-period, upper / middle / lower</span>
        </div>
        <div className="h-96">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={points}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(148, 163, 184, .2)" />
              <XAxis dataKey="date" minTickGap={28} stroke="#94a3b8" />
              <YAxis domain={["auto", "auto"]} stroke="#94a3b8" />
              <Tooltip labelFormatter={(v) => formatPointDate(v)} formatter={(v, name) => [formatNumber(v, 2), name]} />
              <Legend />
              {/* Band fill: Recharts has no first-class "area between two lines" mark,
                  and stacking two Areas to fake one (upper fill, then lower painted
                  over in the background color) breaks as soon as the Y axis
                  autoscales per panel or the panel isn't opaque, producing a
                  misleading shape. Three plain Lines (dashed upper/lower, solid
                  middle) is the simpler, honest rendering used here instead. */}
              <Line type="monotone" dataKey="close" name="Close" stroke="#2dd4bf" strokeWidth={2} dot={false} connectNulls={false} />
              <Line type="monotone" dataKey="bollinger_upper" name="Upper" stroke="#818cf8" strokeWidth={1.25} strokeDasharray="4 3" dot={false} connectNulls={false} />
              <Line type="monotone" dataKey="bollinger_middle" name="Middle (SMA 20)" stroke="#fbbf24" strokeWidth={1.25} dot={false} connectNulls={false} />
              <Line type="monotone" dataKey="bollinger_lower" name="Lower" stroke="#818cf8" strokeWidth={1.25} strokeDasharray="4 3" dot={false} connectNulls={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </section>

      {/* MACD */}
      <section className="panel mb-4">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="font-display text-xl font-semibold">MACD</h3>
          <span className="text-xs text-slate-400">12/26 EMA convergence-divergence, 9-period signal</span>
        </div>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={points}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(148, 163, 184, .2)" />
              <XAxis dataKey="date" minTickGap={28} stroke="#94a3b8" />
              <YAxis domain={["auto", "auto"]} stroke="#94a3b8" />
              <Tooltip labelFormatter={(v) => formatPointDate(v)} formatter={(v, name) => [formatNumber(v, 3), name]} />
              <Legend />
              <Bar dataKey="macd_histogram" name="Histogram">
                {points.map((p, idx) => (
                  <Cell key={idx} fill={Number(p.macd_histogram) >= 0 ? "#34d399" : "#f87171"} />
                ))}
              </Bar>
              <Line type="monotone" dataKey="macd" name="MACD" stroke="#60a5fa" strokeWidth={1.75} dot={false} connectNulls={false} />
              <Line type="monotone" dataKey="macd_signal" name="Signal" stroke="#fbbf24" strokeWidth={1.75} dot={false} connectNulls={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </section>

      {/* RSI */}
      <section className="panel">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="font-display text-xl font-semibold">RSI (14)</h3>
          <span className="text-xs text-slate-400">relative strength index</span>
        </div>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(148, 163, 184, .2)" />
              <XAxis dataKey="date" minTickGap={28} stroke="#94a3b8" />
              <YAxis domain={[0, 100]} stroke="#94a3b8" />
              <Tooltip labelFormatter={(v) => formatPointDate(v)} formatter={(v, name) => [formatNumber(v, 2), name]} />
              <ReferenceLine y={70} stroke="#f87171" strokeDasharray="4 3" label={{ value: "Overbought", position: "insideTopRight", fill: "#f87171", fontSize: 11 }} />
              <ReferenceLine y={30} stroke="#34d399" strokeDasharray="4 3" label={{ value: "Oversold", position: "insideBottomRight", fill: "#34d399", fontSize: 11 }} />
              <Line type="monotone" dataKey="rsi_14" name="RSI 14" stroke="#c4b5fd" strokeWidth={2} dot={false} connectNulls={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>
    </AppShell>
  );
}
