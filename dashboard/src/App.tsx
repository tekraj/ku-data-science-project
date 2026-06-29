import { useEffect, useMemo, useState } from "react";
import {
  BrowserRouter,
  Link,
  Navigate,
  Outlet,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
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

const API_BASE = "/api";

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

const NPT = "Asia/Kathmandu";

function formatDate(dateString: string | null | undefined): string {
  if (!dateString) return "-";
  const dt = new Date(dateString);
  if (Number.isNaN(dt.getTime())) return "-";
  return dt.toLocaleString("en-US", {
    timeZone: NPT,
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }) + " NPT";
}

function shortTime(dateString: string | null | undefined): string {
  if (!dateString) return "-";
  const dt = new Date(dateString);
  if (Number.isNaN(dt.getTime())) return "-";
  return dt.toLocaleTimeString("en-US", { timeZone: NPT, hour: "2-digit", minute: "2-digit", hour12: false });
}

function trendColor(value) {
  if (value > 0) return "text-emerald-300";
  if (value < 0) return "text-rose-300";
  return "text-slate-300";
}

async function apiRequest(path, options = {}) {
  const { headers, body } = options;
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      ...(body ? { "Content-Type": "application/json" } : {}),
      ...(headers || {}),
    },
  });

  if (!response.ok) {
    const error = new Error(`Request failed: ${response.status}`);
    error.status = response.status;
    throw error;
  }

  return response.json();
}

function AppShell({ children, title, subtitle, actions }) {
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

function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    apiRequest("/auth/me")
      .then(() => {
        if (active) navigate("/", { replace: true });
      })
      .catch(() => {
        if (active) setChecking(false);
      });
    return () => {
      active = false;
    };
  }, [navigate]);

  async function onSubmit(e) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await apiRequest("/auth/signin", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      navigate("/", { replace: true });
    } catch {
      setError("Invalid email or password.");
    } finally {
      setLoading(false);
    }
  }

  if (checking) {
    return <FullScreenState label="Checking session..." />;
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden px-4">
      <div className="absolute -left-24 -top-24 h-64 w-64 rounded-full bg-cyan-400/30 blur-3xl" />
      <div className="absolute -bottom-24 -right-24 h-72 w-72 rounded-full bg-blue-500/30 blur-3xl" />

      <form onSubmit={onSubmit} className="panel relative z-10 w-full max-w-md p-7 md:p-8">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">Secure Login</p>
        <h1 className="mt-2 font-display text-3xl font-bold text-slate-100">Market Command Portal</h1>
        <p className="mt-2 text-sm text-slate-300">Access the protected NEPSE analytics dashboard and run telemetry charts.</p>

        <div className="mt-5 space-y-4">
          <div>
            <label className="mb-1 block text-sm text-slate-300">Email</label>
            <input
              className="field"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="mb-1 block text-sm text-slate-300">Password</label>
            <input
              className="field"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
        </div>

        {error && <div className="mt-4 rounded-xl border border-rose-500/40 bg-rose-950/50 px-3 py-2 text-sm text-rose-200">{error}</div>}

        <button type="submit" disabled={loading} className="btn-primary mt-5 w-full">
          {loading ? "Signing In..." : "Sign In"}
        </button>
      </form>
    </main>
  );
}

function FullScreenState({ label }) {
  return (
    <div className="flex min-h-screen items-center justify-center px-4 text-slate-300">
      <div className="panel flex items-center gap-3 px-6 py-4">
        <span className="h-3 w-3 animate-pulse rounded-full bg-cyan-400" />
        <span>{label}</span>
      </div>
    </div>
  );
}

function ProtectedRoute() {
  const [checking, setChecking] = useState(true);
  const [allowed, setAllowed] = useState(false);
  const location = useLocation();

  useEffect(() => {
    let active = true;

    apiRequest("/auth/me")
      .then(() => {
        if (!active) return;
        setAllowed(true);
      })
      .catch(() => {
        if (!active) return;
        setAllowed(false);
      })
      .finally(() => {
        if (active) setChecking(false);
      });

    return () => {
      active = false;
    };
  }, []);

  if (checking) return <FullScreenState label="Validating session..." />;
  if (!allowed) return <Navigate to="/login" state={{ from: location.pathname }} replace />;

  return <Outlet />;
}

function TopBar({ hours, setHours, onLogout, rightLink }) {
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

function DashboardPage() {
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
          rightLink={<><Link className="btn-ghost" to="/news">News</Link><Link className="btn-ghost" to="/logs">Run Logs</Link></>}
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
              <a
                key={`${item.url}-${item.scraped_at}`}
                href={item.url}
                target="_blank"
                rel="noreferrer"
                className="block rounded-xl border border-slate-700 bg-slate-900/70 p-3 transition hover:border-cyan-400/60"
              >
                <div className="mb-1 flex items-center justify-between gap-2 text-xs text-slate-400">
                  <span>{item.source}</span>
                  <span className={item.portal_tier === "finance" ? "text-cyan-300" : "text-amber-300"}>{item.portal_tier}</span>
                </div>
                <h4 className="line-clamp-2 font-medium text-slate-100">{item.title || "Untitled"}</h4>
                <p className="mt-1 line-clamp-2 text-sm text-slate-300">{item.body ? `${item.body.slice(0, 140)}...` : "No body captured"}</p>
                <p className="mt-1 text-xs text-slate-400">{formatDate(item.scraped_at)}</p>
              </a>
            ))}
            {!loading && news.length === 0 ? <p className="text-sm text-slate-400">No news records available yet.</p> : null}
          </div>
        </article>
      </section>
    </AppShell>
  );
}

function LogsPage() {
  const navigate = useNavigate();
  const [logsData, setLogsData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;

    async function loadLogs() {
      setLoading(true);
      setError("");
      try {
        const data = await apiRequest("/dashboard/pipeline-logs?limit=180");
        if (!active) return;
        setLogsData(data);
      } catch (e) {
        if (!active) return;
        if (e.status === 401) {
          navigate("/login", { replace: true });
          return;
        }
        setError("Unable to load pipeline logs.");
      } finally {
        if (active) setLoading(false);
      }
    }

    loadLogs();
    const id = window.setInterval(loadLogs, 30000);
    return () => {
      active = false;
      window.clearInterval(id);
    };
  }, [navigate]);

  async function onLogout() {
    try {
      await apiRequest("/auth/logout", { method: "POST" });
    } finally {
      navigate("/login", { replace: true });
    }
  }

  const summary = logsData?.summary || { success: 0, failed: 0, last_run_at: null };
  const rows = logsData?.logs || [];

  return (
    <AppShell
      title="Pipeline Run Logs"
      subtitle="Protected stream of successful and failed pipeline executions"
      actions={<TopBar onLogout={onLogout} rightLink={<Link className="btn-ghost" to="/">Dashboard</Link>} />}
    >
      {error && <div className="mb-4 rounded-xl border border-rose-500/40 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">{error}</div>}

      <section className="grid gap-3 md:grid-cols-3">
        <article className="metric-card">
          <p className="text-xs uppercase tracking-[0.14em] text-slate-400">Successful</p>
          <p className="mt-2 font-display text-3xl font-bold text-emerald-300">{loading ? "..." : formatNumber(summary.success, 0)}</p>
        </article>
        <article className="metric-card">
          <p className="text-xs uppercase tracking-[0.14em] text-slate-400">Failed</p>
          <p className="mt-2 font-display text-3xl font-bold text-rose-300">{loading ? "..." : formatNumber(summary.failed, 0)}</p>
        </article>
        <article className="metric-card">
          <p className="text-xs uppercase tracking-[0.14em] text-slate-400">Last Run</p>
          <p className="mt-2 text-base font-semibold text-slate-100">{loading ? "..." : formatDate(summary.last_run_at)}</p>
        </article>
      </section>

      <section className="panel mt-4 overflow-hidden">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="font-display text-xl font-semibold">Execution Stream</h3>
          <span className="text-xs text-slate-400">{rows.length} rows</span>
        </div>

        <div className="overflow-auto">
          <table className="min-w-[1050px] w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-slate-700 text-left text-xs uppercase tracking-wide text-slate-400">
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Started</th>
                <th className="px-3 py-2">Duration</th>
                <th className="px-3 py-2">News</th>
                <th className="px-3 py-2">NEPSE</th>
                <th className="px-3 py-2">Source</th>
                <th className="px-3 py-2">Message</th>
                <th className="px-3 py-2">Error</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-b border-slate-800 text-slate-200">
                  <td className="px-3 py-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-semibold uppercase ${
                        row.status === "success" ? "bg-emerald-500/20 text-emerald-300" : "bg-rose-500/20 text-rose-300"
                      }`}
                    >
                      {row.status}
                    </span>
                  </td>
                  <td className="px-3 py-2">{formatDate(row.started_at)}</td>
                  <td className="px-3 py-2">{formatNumber((row.duration_ms || 0) / 1000, 1)}s</td>
                  <td className="px-3 py-2">{row.news_total}/{row.news_inserted}</td>
                  <td className="px-3 py-2">{row.nepse_records}</td>
                  <td className="px-3 py-2">{row.nepse_source || "-"}</td>
                  <td className="px-3 py-2">{row.message || "-"}</td>
                  <td className="px-3 py-2 text-rose-200">{row.error_text || "-"}</td>
                </tr>
              ))}
              {!loading && rows.length === 0 ? (
                <tr>
                  <td className="px-3 py-4 text-slate-400" colSpan={8}>No pipeline logs found yet.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </AppShell>
  );
}

const TIER_COLORS: Record<string, string> = {
  finance: "bg-cyan-500/20 text-cyan-200 border-cyan-500/40",
  general: "bg-amber-500/20 text-amber-200 border-amber-500/40",
};

const CATEGORY_COLORS: Record<string, string> = {
  market: "bg-violet-500/20 text-violet-200",
  economy: "bg-blue-500/20 text-blue-200",
  company: "bg-emerald-500/20 text-emerald-200",
  banking: "bg-sky-500/20 text-sky-200",
  policy: "bg-orange-500/20 text-orange-200",
  international: "bg-fuchsia-500/20 text-fuchsia-200",
};

function categoryClass(cat: string): string {
  if (!cat) return "bg-slate-600/40 text-slate-300";
  const key = cat.toLowerCase();
  for (const [k, v] of Object.entries(CATEGORY_COLORS)) {
    if (key.includes(k)) return v;
  }
  return "bg-slate-600/40 text-slate-300";
}

function NewsPage() {
  const navigate = useNavigate();

  const [page, setPage] = useState(1);
  const [tier, setTier] = useState("all");
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [category, setCategory] = useState("");
  const [data, setData] = useState<{ total: number; total_pages: number; news: any[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function onLogout() {
    try { await apiRequest("/auth/logout", { method: "POST" }); } finally {
      navigate("/login", { replace: true });
    }
  }

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");

    const params = new URLSearchParams({
      page: String(page),
      page_size: "20",
      ...(tier !== "all" ? { tier } : {}),
      ...(search ? { search } : {}),
      ...(category ? { category } : {}),
    });

    apiRequest(`/dashboard/news?${params}`)
      .then((d) => { if (active) setData(d); })
      .catch((e) => {
        if (!active) return;
        if (e.status === 401) { navigate("/login", { replace: true }); return; }
        setError("Unable to load news.");
      })
      .finally(() => { if (active) setLoading(false); });

    return () => { active = false; };
  }, [page, tier, search, category, navigate]);

  function applySearch() {
    setSearch(searchInput.trim());
    setPage(1);
  }

  const totalPages = data?.total_pages ?? 1;
  const items = data?.news ?? [];

  const pageNumbers: number[] = [];
  const start = Math.max(1, page - 2);
  const end = Math.min(totalPages, page + 2);
  for (let i = start; i <= end; i++) pageNumbers.push(i);

  return (
    <AppShell
      title="News Room"
      subtitle="Paginated articles ordered by date — filter by tier, category or keyword"
      actions={
        <TopBar
          onLogout={onLogout}
          rightLink={<Link className="btn-ghost" to="/">Dashboard</Link>}
        />
      }
    >
      {error && <div className="mb-4 rounded-xl border border-rose-500/40 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">{error}</div>}

      {/* Filters */}
      <section className="panel mb-4 flex flex-wrap items-end gap-3">
        <div>
          <label className="mb-1 block text-xs uppercase tracking-widest text-slate-400">Tier</label>
          <select
            className="rounded-xl border border-slate-600 bg-slate-900/70 px-3 py-2 text-sm text-slate-100"
            value={tier}
            onChange={(e) => { setTier(e.target.value); setPage(1); }}
          >
            <option value="all">All</option>
            <option value="finance">Finance</option>
            <option value="general">General</option>
          </select>
        </div>

        <div>
          <label className="mb-1 block text-xs uppercase tracking-widest text-slate-400">Category</label>
          <input
            className="field w-40"
            type="text"
            placeholder="e.g. market"
            value={category}
            onChange={(e) => { setCategory(e.target.value); setPage(1); }}
          />
        </div>

        <div className="flex-1">
          <label className="mb-1 block text-xs uppercase tracking-widest text-slate-400">Search Title</label>
          <div className="flex gap-2">
            <input
              className="field flex-1"
              type="text"
              placeholder="keyword…"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && applySearch()}
            />
            <button className="btn-primary px-5" onClick={applySearch} type="button">Search</button>
            {(search || category || tier !== "all") && (
              <button
                className="btn-ghost"
                onClick={() => { setSearch(""); setSearchInput(""); setCategory(""); setTier("all"); setPage(1); }}
                type="button"
              >
                Clear
              </button>
            )}
          </div>
        </div>

        <div className="text-sm text-slate-400">
          {loading ? "Loading…" : `${data?.total ?? 0} articles`}
        </div>
      </section>

      {/* News grid */}
      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {items.map((item, idx) => (
          <a
            key={`${item.url}-${idx}`}
            href={item.url}
            target="_blank"
            rel="noreferrer"
            className="panel flex flex-col gap-2 p-4 transition hover:border-cyan-400/60 hover:-translate-y-0.5"
          >
            {/* Badges row */}
            <div className="flex flex-wrap items-center gap-1.5">
              <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold uppercase ${TIER_COLORS[item.portal_tier] ?? "bg-slate-700/50 text-slate-300 border-slate-600"}`}>
                {item.portal_tier}
              </span>
              {item.category && (
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${categoryClass(item.category)}`}>
                  {item.category}
                </span>
              )}
              <span className="ml-auto text-xs text-slate-400">{item.source}</span>
            </div>

            {/* Title */}
            <h3 className="line-clamp-3 font-display text-base font-semibold leading-snug text-slate-100">
              {item.title || "Untitled Article"}
            </h3>

            {/* Body snippet */}
            {item.body && (
              <p className="line-clamp-3 text-sm text-slate-300">
                {item.body.slice(0, 200)}
              </p>
            )}

            {/* Date */}
            <p className="mt-auto pt-1 text-xs text-slate-500">{formatDate(item.scraped_at)}</p>
          </a>
        ))}

        {!loading && items.length === 0 && (
          <p className="col-span-full py-12 text-center text-slate-400">No articles match your filters.</p>
        )}

        {loading && (
          <p className="col-span-full py-12 text-center text-slate-400">Loading articles…</p>
        )}
      </section>

      {/* Pagination */}
      {totalPages > 1 && (
        <nav className="mt-6 flex items-center justify-center gap-1">
          <button
            className="btn-ghost px-3 py-1.5 text-sm disabled:opacity-40"
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
            type="button"
          >
            ← Prev
          </button>

          {start > 1 && (
            <>
              <button className="btn-ghost px-3 py-1.5 text-sm" onClick={() => setPage(1)} type="button">1</button>
              {start > 2 && <span className="px-1 text-slate-500">…</span>}
            </>
          )}

          {pageNumbers.map((n) => (
            <button
              key={n}
              className={`px-3 py-1.5 text-sm rounded-xl border transition ${
                n === page
                  ? "border-cyan-400 bg-cyan-500/20 text-cyan-200"
                  : "border-slate-600 bg-slate-900/70 text-slate-300 hover:border-slate-400"
              }`}
              onClick={() => setPage(n)}
              type="button"
            >
              {n}
            </button>
          ))}

          {end < totalPages && (
            <>
              {end < totalPages - 1 && <span className="px-1 text-slate-500">…</span>}
              <button className="btn-ghost px-3 py-1.5 text-sm" onClick={() => setPage(totalPages)} type="button">{totalPages}</button>
            </>
          )}

          <button
            className="btn-ghost px-3 py-1.5 text-sm disabled:opacity-40"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
            type="button"
          >
            Next →
          </button>
        </nav>
      )}
    </AppShell>
  );
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/news" element={<NewsPage />} />
          <Route path="/logs" element={<LogsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
