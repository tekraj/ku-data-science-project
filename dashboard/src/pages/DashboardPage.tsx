import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
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
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { apiRequest } from "../lib/api";
import { formatDate, formatNumber, shortTime, trendColor } from "../lib/format";
import { AppShell } from "../components/AppShell";
import { TopBar } from "../components/TopBar";

export function DashboardPage() {
  const navigate = useNavigate();
  const [hours, setHours] = useState(24);
  const [overview, setOverview] = useState(null);
  const [news, setNews] = useState([]);
  const [mainHistory, setMainHistory] = useState([]);
  const [sectorHistory, setSectorHistory] = useState({});
  const [activeSector, setActiveSector] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;

    async function loadData() {
      setLoading(true);
      setError("");
      try {
        const [overviewData, newsData, historyData, sectorData] = await Promise.all([
          apiRequest(`/dashboard/overview?hours=${hours}`),
          apiRequest(`/dashboard/latest-news?limit=15`),
          apiRequest(`/dashboard/nepse-history?hours=${hours}`),
          apiRequest(`/dashboard/sector-history?hours=${hours}`),
        ]);

        if (!active) return;

        setOverview(overviewData);
        setNews(newsData.news || []);
        setMainHistory(historyData.points || []);
        setSectorHistory(sectorData.series || {});

        const keys = Object.keys(sectorData.series || {});
        if (keys.length > 0) {
          setActiveSector((prev) => (prev && keys.includes(prev) ? prev : keys[0]));
        } else {
          setActiveSector("");
        }
      } catch (e) {
        if (!active) return;
        if (e.status === 401) {
          navigate("/login", { replace: true });
          return;
        }
        setError("Unable to load dashboard data.");
      } finally {
        if (active) setLoading(false);
      }
    }

    loadData();
    const id = window.setInterval(loadData, 30000);

    return () => {
      active = false;
      window.clearInterval(id);
    };
  }, [hours, navigate]);

  async function onLogout() {
    try {
      await apiRequest("/auth/logout", { method: "POST" });
    } finally {
      navigate("/login", { replace: true });
    }
  }

  const stats = overview?.stats || {};
  const latestNepse = overview?.nepse || {};
  const topSources = overview?.top_sources || [];
  const sectorSnapshot = overview?.sector_snapshot || [];
  const sectorTabs = Object.keys(sectorHistory || {});
  const activeSectorSeries = activeSector ? sectorHistory[activeSector] || [] : [];

  const newsMix = useMemo(
    () => [
      { name: "Finance", value: Number(stats.finance_count || 0) },
      { name: "General", value: Number(stats.general_count || 0) },
    ],
    [stats.finance_count, stats.general_count],
  );

  const sectorMomentum = useMemo(
    () =>
      sectorSnapshot
        .map((item) => ({
          name: item.index,
          percent: Number(item.percent_change || 0),
        }))
        .slice(0, 10),
    [sectorSnapshot],
  );

  return (
    <AppShell
      title="NEPSE Analytics Dashboard"
      subtitle="Protected market intelligence view with live index, sector, source, and feed charts"
      actions={
        <TopBar
          hours={hours}
          setHours={setHours}
          onLogout={onLogout}
          rightLink={
            <>
              <Link className="btn-ghost" to="/news">News</Link>
              <Link className="btn-ghost" to="/technicals">Technicals</Link>
              <Link className="btn-ghost" to="/logs">Run Logs</Link>
            </>
          }
        />
      }
    >
      {error && <div className="mb-4 rounded-xl border border-rose-500/40 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">{error}</div>}

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <article className="metric-card">
          <p className="text-xs uppercase tracking-[0.14em] text-slate-400">NEPSE Value</p>
          <p className="mt-2 font-display text-3xl font-bold text-slate-100">{loading ? "..." : formatNumber(latestNepse.value, 2)}</p>
          <p className={`mt-1 text-sm ${trendColor(Number(latestNepse.change || 0))}`}>
            {loading ? "..." : `${formatNumber(latestNepse.change, 2)} (${formatNumber(latestNepse.percent_change, 2)}%)`}
          </p>
        </article>
        <article className="metric-card">
          <p className="text-xs uppercase tracking-[0.14em] text-slate-400">Articles</p>
          <p className="mt-2 font-display text-3xl font-bold text-slate-100">{loading ? "..." : formatNumber(stats.total_articles, 0)}</p>
          <p className="mt-1 text-sm text-slate-300">{formatNumber(stats.total_sources, 0)} active sources</p>
        </article>
        <article className="metric-card">
          <p className="text-xs uppercase tracking-[0.14em] text-slate-400">News Mix</p>
          <p className="mt-2 font-display text-3xl font-bold text-slate-100">
            {loading ? "..." : `${formatNumber(stats.finance_count, 0)} / ${formatNumber(stats.general_count, 0)}`}
          </p>
          <p className="mt-1 text-sm text-slate-300">Finance / General</p>
        </article>
        <article className="metric-card">
          <p className="text-xs uppercase tracking-[0.14em] text-slate-400">Last Scrape</p>
          <p className="mt-2 text-lg font-semibold text-slate-100">{loading ? "..." : formatDate(stats.last_scraped_at)}</p>
        </article>
      </section>

      <section className="mt-4 grid gap-3 xl:grid-cols-[1.55fr_1fr]">
        <article className="panel">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-display text-xl font-semibold">Main Index Trend</h3>
            <span className="text-xs text-slate-400">{mainHistory.length} points</span>
          </div>
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={mainHistory}>
                <defs>
                  <linearGradient id="nepseFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#2dd4bf" stopOpacity={0.55} />
                    <stop offset="95%" stopColor="#2dd4bf" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(148, 163, 184, .2)" />
                <XAxis dataKey="scraped_at" tickFormatter={shortTime} minTickGap={28} stroke="#94a3b8" />
                <YAxis domain={["auto", "auto"]} stroke="#94a3b8" />
                <Tooltip labelFormatter={(v) => formatDate(v)} formatter={(v) => [formatNumber(v, 2), "NEPSE"]} />
                <Area type="monotone" dataKey="value" stroke="#2dd4bf" fill="url(#nepseFill)" strokeWidth={2.5} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </article>

        <article className="panel">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-display text-xl font-semibold">News Mix</h3>
            <span className="text-xs text-slate-400">finance vs general</span>
          </div>
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Tooltip formatter={(v) => formatNumber(v, 0)} />
                <Legend />
                <Pie data={newsMix} dataKey="value" nameKey="name" innerRadius={58} outerRadius={96}>
                  {newsMix.map((entry, idx) => (
                    <Cell key={entry.name} fill={idx === 0 ? "#2dd4bf" : "#f59e0b"} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
          </div>
        </article>
      </section>

      <section className="mt-4 grid gap-3 xl:grid-cols-[1.55fr_1fr]">
        <article className="panel">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="font-display text-xl font-semibold">Sub-Indices (Tabs)</h3>
            <span className="text-xs text-slate-400">{sectorTabs.length} sectors</span>
          </div>

          <div className="mb-3 flex flex-wrap gap-2">
            {sectorTabs.map((sector) => (
              <button
                key={sector}
                type="button"
                onClick={() => setActiveSector(sector)}
                className={`rounded-lg border px-3 py-1.5 text-sm transition ${
                  sector === activeSector
                    ? "border-cyan-300 bg-cyan-500/20 text-cyan-200"
                    : "border-slate-600 bg-slate-800/80 text-slate-200 hover:border-slate-400"
                }`}
              >
                {sector}
              </button>
            ))}
            {sectorTabs.length === 0 ? <span className="text-sm text-slate-400">No sector data yet.</span> : null}
          </div>

          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={activeSectorSeries}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(148, 163, 184, .2)" />
                <XAxis dataKey="scraped_at" tickFormatter={shortTime} minTickGap={28} stroke="#94a3b8" />
                <YAxis domain={["auto", "auto"]} stroke="#94a3b8" />
                <Tooltip labelFormatter={(v) => formatDate(v)} formatter={(v) => [formatNumber(v, 2), activeSector || "Sector"]} />
                <Line type="monotone" dataKey="value" stroke="#60a5fa" strokeWidth={2.5} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </article>

        <article className="panel">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-display text-xl font-semibold">Sector Momentum</h3>
            <span className="text-xs text-slate-400">top 10 latest % change</span>
          </div>
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={sectorMomentum} layout="vertical" margin={{ left: 10, right: 14 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(148, 163, 184, .2)" />
                <XAxis type="number" stroke="#94a3b8" />
                <YAxis dataKey="name" type="category" width={95} stroke="#94a3b8" />
                <Tooltip formatter={(v) => [`${formatNumber(v, 2)}%`, "Change"]} />
                <Bar dataKey="percent" radius={[0, 8, 8, 0]}>
                  {sectorMomentum.map((item) => (
                    <Cell key={item.name} fill={item.percent >= 0 ? "#34d399" : "#f87171"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </article>
      </section>

      <section className="mt-4 grid gap-3 xl:grid-cols-[1fr_1.1fr]">
        <article className="panel">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-display text-xl font-semibold">Top News Sources</h3>
            <span className="text-xs text-slate-400">latest window volume</span>
          </div>
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={topSources}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(148, 163, 184, .2)" />
                <XAxis dataKey="source" interval={0} angle={-15} textAnchor="end" height={58} stroke="#94a3b8" />
                <YAxis stroke="#94a3b8" />
                <Tooltip formatter={(v) => [formatNumber(v, 0), "Articles"]} />
                <Bar dataKey="item_count" fill="#f59e0b" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </article>

        <article className="panel">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="font-display text-xl font-semibold">Latest News Feed</h3>
            <span className="text-xs text-slate-400">refreshes every 30s</span>
          </div>
          <div className="max-h-80 space-y-2 overflow-y-auto pr-1">
            {news.map((item) => (
              <Link
                key={item.id ?? `${item.url}-${item.scraped_at}`}
                to={`/news/${item.id}`}
                className="block rounded-xl border border-slate-700 bg-slate-900/70 p-3 transition hover:border-cyan-400/60"
              >
                <div className="mb-1 flex items-center justify-between gap-2 text-xs text-slate-400">
                  <span>{item.source}</span>
                  <span className={item.portal_tier === "finance" ? "text-cyan-300" : "text-amber-300"}>{item.portal_tier}</span>
                </div>
                <h4 className="line-clamp-2 font-medium text-slate-100">{item.title || "Untitled"}</h4>
                <p className="mt-1 line-clamp-2 text-sm text-slate-300">{item.body ? `${item.body.slice(0, 140)}...` : "No body captured"}</p>
                <p className="mt-1 text-xs text-slate-400">{formatDate(item.published_at ?? item.scraped_at)}</p>
              </Link>
            ))}
            {!loading && news.length === 0 ? <p className="text-sm text-slate-400">No news records available yet.</p> : null}
          </div>
        </article>
      </section>
    </AppShell>
  );
}
