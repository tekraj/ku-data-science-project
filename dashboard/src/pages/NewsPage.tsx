import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { apiRequest } from "../lib/api";
import { formatDate } from "../lib/format";
import { AppShell } from "../components/AppShell";
import { TopBar } from "../components/TopBar";

// TIER_COLORS/CATEGORY_COLORS/categoryClass live here (not lib/format.ts) since
// NewsPage is their only consumer.
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

export function NewsPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  // page/tier/category/search all live in the URL (not component state) so
  // a refresh -- or sharing the link -- lands back on the same page and
  // filters instead of always resetting to page 1.
  const page = Math.max(1, Number(searchParams.get("page")) || 1);
  const tier = searchParams.get("tier") || "all";
  const search = searchParams.get("search") || "";
  const category = searchParams.get("category") || "";

  const [searchInput, setSearchInput] = useState(search);
  const [data, setData] = useState<{ total: number; total_pages: number; news: any[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function onLogout() {
    try { await apiRequest("/auth/logout", { method: "POST" }); } finally {
      navigate("/login", { replace: true });
    }
  }

  function updateParams(next: { page?: number; tier?: string; category?: string; search?: string }, resetPage = false) {
    setSearchParams((prev) => {
      const params = new URLSearchParams(prev);
      const merged = {
        page: next.page ?? page,
        tier: next.tier ?? tier,
        category: next.category ?? category,
        search: next.search ?? search,
      };
      if (resetPage) merged.page = 1;

      params.set("page", String(merged.page));
      merged.tier !== "all" ? params.set("tier", merged.tier) : params.delete("tier");
      merged.category ? params.set("category", merged.category) : params.delete("category");
      merged.search ? params.set("search", merged.search) : params.delete("search");
      return params;
    });
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
    updateParams({ search: searchInput.trim() }, true);
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
          rightLink={
            <>
              <Link className="btn-ghost" to="/">Dashboard</Link>
              <Link className="btn-ghost" to="/technicals">Technicals</Link>
              <Link className="btn-ghost" to="/logs">Run Logs</Link>
            </>
          }
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
            onChange={(e) => updateParams({ tier: e.target.value }, true)}
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
            onChange={(e) => updateParams({ category: e.target.value }, true)}
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
                onClick={() => { setSearchInput(""); updateParams({ search: "", category: "", tier: "all" }, true); }}
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
          <Link
            key={item.id ?? `${item.url}-${idx}`}
            to={`/news/${item.id}`}
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
            <p className="mt-auto pt-1 text-xs text-slate-500">{formatDate(item.published_at ?? item.scraped_at)}</p>
          </Link>
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
            onClick={() => updateParams({ page: page - 1 })}
            type="button"
          >
            ← Prev
          </button>

          {start > 1 && (
            <>
              <button className="btn-ghost px-3 py-1.5 text-sm" onClick={() => updateParams({ page: 1 })} type="button">1</button>
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
              onClick={() => updateParams({ page: n })}
              type="button"
            >
              {n}
            </button>
          ))}

          {end < totalPages && (
            <>
              {end < totalPages - 1 && <span className="px-1 text-slate-500">…</span>}
              <button className="btn-ghost px-3 py-1.5 text-sm" onClick={() => updateParams({ page: totalPages })} type="button">{totalPages}</button>
            </>
          )}

          <button
            className="btn-ghost px-3 py-1.5 text-sm disabled:opacity-40"
            disabled={page >= totalPages}
            onClick={() => updateParams({ page: page + 1 })}
            type="button"
          >
            Next →
          </button>
        </nav>
      )}
    </AppShell>
  );
}
