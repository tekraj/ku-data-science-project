import { useState } from "react";
import { AppShell } from "../components/AppShell";
import { NavLinks } from "../components/NavLinks";
import { Notice, Panel } from "../components/Panel";
import { TopBar } from "../components/TopBar";
import { formatDate, formatNumber, timeAgo } from "../lib/format";
import { useApi, useLogout } from "../lib/useApi";

const HEALTH_WINDOWS = [
  { hours: 24, label: "24h" },
  { hours: 72, label: "3d" },
  { hours: 168, label: "7d" },
];

// Jobs that log every few minutes around the clock (minute scrapes log a
// skip outside market hours; news every 15 min): a longer silence means the
// stack or the machine was down.
const GAP_ALERT_MINUTES = 30;

function isFrequent(job) {
  return job.skipped > 0 || job.job === "news_scraper";
}

function formatGap(minutes) {
  if (minutes === null || minutes === undefined) return "-";
  if (minutes < 90) return `${Math.round(minutes)} min`;
  if (minutes < 48 * 60) return `${(minutes / 60).toFixed(1)} h`;
  return `${(minutes / 1440).toFixed(1)} d`;
}

function healthTone(job) {
  if (isFrequent(job) && job.max_gap_minutes > GAP_ALERT_MINUTES) return "text-amber-300";
  const worked = job.ok + job.failed;
  if (worked === 0) return "text-slate-400";
  if (job.failed / worked > 0.1) return "text-rose-300";
  if (job.failed > 0) return "text-amber-300";
  return "text-emerald-300";
}

export function LogsPage() {
  const onLogout = useLogout();
  const [healthHours, setHealthHours] = useState(24);
  const [status, setStatus] = useState("all");
  const [source, setSource] = useState("");
  const [includeSkipped, setIncludeSkipped] = useState(false);
  const [limit, setLimit] = useState(200);

  const health = useApi(`/dashboard/pipeline-health?hours=${healthHours}`, 30000);
  const logs = useApi(
    `/dashboard/pipeline-logs?limit=${limit}&status=${status}&source=${encodeURIComponent(source)}&include_skipped=${includeSkipped}`,
    30000,
  );

  const jobs = health.data?.jobs || [];
  const summary = logs.data?.summary || { success: 0, failed: 0, last_run_at: null };
  const rows = logs.data?.logs || [];
  const sources = logs.data?.sources || [];
  const errors = [health.error, logs.error].filter(Boolean);

  return (
    <AppShell
      title="Pipeline Run Logs"
      subtitle="Health of every scheduled job, and the stream of runs behind it"
      actions={<TopBar onLogout={onLogout} rightLink={<NavLinks />} />}
    >
      {errors.map((e) => (
        <Notice key={e} tone="rose">{e}</Notice>
      ))}

      <Panel
        title="Pipeline Health"
        note="runs that did work vs failures; skips are minute ticks outside market hours; a long gap means nothing ran (stack or machine down)"
        right={
          <div className="flex gap-1">
            {HEALTH_WINDOWS.map((w) => (
              <button
                key={w.hours}
                type="button"
                onClick={() => setHealthHours(w.hours)}
                className={`rounded-lg border px-3 py-1.5 text-sm ${
                  w.hours === healthHours ? "border-cyan-300 bg-cyan-500/20 text-cyan-200" : "border-slate-600 bg-slate-800/80 text-slate-200"
                }`}
              >
                {w.label}
              </button>
            ))}
          </div>
        }
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-sm">
            <thead>
              <tr className="border-b border-slate-700 text-left text-xs uppercase tracking-wide text-slate-400">
                <th className="px-3 py-2">Job</th>
                <th className="px-3 py-2 text-right">OK</th>
                <th className="px-3 py-2 text-right">Failed</th>
                <th className="px-3 py-2 text-right">Skipped</th>
                <th className="px-3 py-2">Last productive run</th>
                <th className="px-3 py-2">Longest gap</th>
                <th className="px-3 py-2">Last failure</th>
                <th className="px-3 py-2">Sources used</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.job} className="border-b border-slate-800 align-top text-slate-200">
                  <td className={`px-3 py-2 font-medium ${healthTone(job)}`}>
                    {job.label}
                    <div className="text-xs font-normal text-slate-500">{job.job}</div>
                  </td>
                  <td className="px-3 py-2 text-right">{formatNumber(job.ok, 0)}</td>
                  <td className={`px-3 py-2 text-right ${job.failed ? "text-rose-300" : ""}`}>{formatNumber(job.failed, 0)}</td>
                  <td className="px-3 py-2 text-right text-slate-400">{formatNumber(job.skipped, 0)}</td>
                  <td className="px-3 py-2">
                    {job.last_ok ? (
                      <>
                        {formatDate(job.last_ok)}
                        <div className="text-xs text-slate-400">{timeAgo(job.last_ok)}</div>
                      </>
                    ) : (
                      <span className="text-slate-500">none in window</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <span className={isFrequent(job) && job.max_gap_minutes > GAP_ALERT_MINUTES ? "text-amber-300" : ""}>
                      {formatGap(job.max_gap_minutes)}
                    </span>
                    {job.max_gap_ended_at ? <div className="text-xs text-slate-400">until {formatDate(job.max_gap_ended_at)}</div> : null}
                  </td>
                  <td className="max-w-[22rem] px-3 py-2">
                    {job.last_failed ? (
                      <>
                        <span className="text-rose-300">{timeAgo(job.last_failed)}</span>
                        <div className="truncate text-xs text-slate-400" title={job.last_error || ""}>{job.last_error}</div>
                      </>
                    ) : (
                      <span className="text-slate-500">-</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-300">
                    {Object.entries(job.sources || {}).map(([name, n]) => (
                      <div key={name}>
                        {name} <span className="text-slate-500">× {formatNumber(n, 0)}</span>
                      </div>
                    ))}
                  </td>
                </tr>
              ))}
              {!health.loading && jobs.length === 0 ? (
                <tr>
                  <td className="px-3 py-4 text-slate-400" colSpan={8}>No runs in this window — is the stack (or the machine) running?</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </Panel>

      <section className="mt-4 grid gap-3 md:grid-cols-3">
        <article className="metric-card">
          <p className="text-xs uppercase tracking-[0.14em] text-slate-400">Successful (shown)</p>
          <p className="mt-2 font-display text-3xl font-bold text-emerald-300">{logs.loading && !logs.data ? "..." : formatNumber(summary.success, 0)}</p>
        </article>
        <article className="metric-card">
          <p className="text-xs uppercase tracking-[0.14em] text-slate-400">Failed (shown)</p>
          <p className="mt-2 font-display text-3xl font-bold text-rose-300">{logs.loading && !logs.data ? "..." : formatNumber(summary.failed, 0)}</p>
        </article>
        <article className="metric-card">
          <p className="text-xs uppercase tracking-[0.14em] text-slate-400">Last Run</p>
          <p className="mt-2 text-base font-semibold text-slate-100">{logs.loading && !logs.data ? "..." : formatDate(summary.last_run_at)}</p>
        </article>
      </section>

      <section className="panel mt-4 overflow-hidden">
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <h3 className="mr-auto font-display text-xl font-semibold">Execution Stream</h3>
          <select
            className="rounded-xl border border-slate-600 bg-slate-900/70 px-3 py-1.5 text-sm text-slate-100"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="all">All statuses</option>
            <option value="success">Success</option>
            <option value="failed">Failed</option>
          </select>
          <select
            className="rounded-xl border border-slate-600 bg-slate-900/70 px-3 py-1.5 text-sm text-slate-100"
            value={source}
            onChange={(e) => setSource(e.target.value)}
          >
            <option value="">All sources</option>
            {sources.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
          <select
            className="rounded-xl border border-slate-600 bg-slate-900/70 px-3 py-1.5 text-sm text-slate-100"
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
          >
            {[100, 200, 500, 1000].map((n) => (
              <option key={n} value={n}>{`${n} rows`}</option>
            ))}
          </select>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" checked={includeSkipped} onChange={(e) => setIncludeSkipped(e.target.checked)} />
            show market-closed skips
          </label>
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
                  <td className="max-w-[28rem] px-3 py-2">{row.message || "-"}</td>
                  <td className="max-w-[20rem] truncate px-3 py-2 text-rose-200" title={row.error_text || ""}>{row.error_text || "-"}</td>
                </tr>
              ))}
              {!logs.loading && rows.length === 0 ? (
                <tr>
                  <td className="px-3 py-4 text-slate-400" colSpan={8}>No pipeline logs match these filters.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </AppShell>
  );
}
