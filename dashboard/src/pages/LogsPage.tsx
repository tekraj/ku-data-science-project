import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { apiRequest } from "../lib/api";
import { formatDate, formatNumber } from "../lib/format";
import { AppShell } from "../components/AppShell";
import { TopBar } from "../components/TopBar";

export function LogsPage() {
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
      actions={
        <TopBar
          onLogout={onLogout}
          rightLink={
            <>
              <Link className="btn-ghost" to="/">Dashboard</Link>
              <Link className="btn-ghost" to="/news">News</Link>
              <Link className="btn-ghost" to="/technicals">Technicals</Link>
            </>
          }
        />
      }
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
