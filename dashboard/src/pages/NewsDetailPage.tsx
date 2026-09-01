import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiRequest } from "../lib/api";
import { formatDate } from "../lib/format";
import { AppShell } from "../components/AppShell";
import { TopBar } from "../components/TopBar";

type Article = {
  id: number;
  source: string;
  portal_tier: string;
  title: string | null;
  body: string | null;
  category: string | null;
  url: string;
  published_at: string | null;
  scraped_at: string | null;
};

export function NewsDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();

  const [article, setArticle] = useState<Article | null>(null);
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

    apiRequest(`/dashboard/news/${id}`)
      .then((d) => { if (active) setArticle(d); })
      .catch((e) => {
        if (!active) return;
        if (e.status === 401) { navigate("/login", { replace: true }); return; }
        setError(e.status === 404 ? "Article not found." : "Unable to load article.");
      })
      .finally(() => { if (active) setLoading(false); });

    return () => { active = false; };
  }, [id, navigate]);

  return (
    <AppShell
      title="Article"
      subtitle="Fetched content — the original source is always one click away"
      actions={
        <TopBar
          onLogout={onLogout}
          rightLink={
            <>
              <Link className="btn-ghost" to="/news">← Back to News</Link>
              <Link className="btn-ghost" to="/">Dashboard</Link>
            </>
          }
        />
      }
    >
      {error && (
        <div className="rounded-xl border border-rose-500/40 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      )}

      {loading && !error && (
        <p className="py-12 text-center text-slate-400">Loading article…</p>
      )}

      {!loading && !error && article && (
        <article className="panel flex flex-col gap-4 p-6">
          <div className="flex flex-wrap items-center gap-1.5">
            <span
              className={`rounded-full border px-2 py-0.5 text-xs font-semibold uppercase ${
                article.portal_tier === "finance"
                  ? "bg-cyan-500/20 text-cyan-200 border-cyan-500/40"
                  : "bg-amber-500/20 text-amber-200 border-amber-500/40"
              }`}
            >
              {article.portal_tier}
            </span>
            {article.category && (
              <span className="rounded-full bg-slate-600/40 px-2 py-0.5 text-xs font-medium text-slate-300">
                {article.category}
              </span>
            )}
            <span className="ml-auto text-xs text-slate-400">{article.source}</span>
          </div>

          <h1 className="font-display text-2xl font-bold leading-snug text-slate-100 md:text-3xl">
            {article.title || "Untitled Article"}
          </h1>

          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
            {article.published_at && <span>Published: {formatDate(article.published_at)}</span>}
            <span>Scraped: {formatDate(article.scraped_at)}</span>
          </div>

          {article.body ? (
            <p className="whitespace-pre-line text-base leading-relaxed text-slate-200">
              {article.body}
            </p>
          ) : (
            <p className="text-sm italic text-slate-400">No content captured for this article yet.</p>
          )}

          <div className="mt-2 border-t border-slate-700 pt-4">
            <a
              href={article.url}
              target="_blank"
              rel="noreferrer"
              className="btn-primary inline-flex items-center gap-1.5"
            >
              View Original Article ↗
            </a>
          </div>
        </article>
      )}
    </AppShell>
  );
}
