# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

A data platform for a Kathmandu University data-science thesis on **market crash detection for NEPSE** (Nepal Stock Exchange) — see `thesis/main.tex` (TDA on correlation networks + Mean Field Games + jump-diffusion/COGARCH). It:

- collects live NEPSE market data every minute during trading hours (index values, every stock's price, every trade, order-book depth, sector turnover) from the official nepalstock.com.np API;
- maintains long-history **research datasets** (daily OHLCV for every index and equity back to 2000/2010, ~1-minute index ticks back to 2018, broker-level trades) for model calibration and backtesting;
- scrapes ~20 Nepali news portals (plus historical backfills) for event context;
- exposes everything through a FastAPI backend and a React dashboard behind Nginx.

The README describes an older idealized layout (`nepali-news-pipeline/`, a single `nepse-news-scraper/` monolith). Both are gone — trust this file and the directory layout over the README.

## Repository Layout

- `nepse-common/` — shared Python package installed into every service image (`pip install -e`): `config.py` (all settings from env vars), `models/` (SQLAlchemy 2.0 ORM), `db/session.py` (cached engine + `session_scope`), `db/upserts.py` (idempotent bulk upserts for the research tables), `constants/index_registry.py` (the 17 NEPSE indices with their official id, canonical name and merolagani symbol), `schemas/`, and **`alembic/`** (the only place schema changes live).
- `nepse-service/` — Temporal worker for all NEPSE market data. `scraper/` = HTTP clients (`nepse_wasm_auth.py` official-API token derivation, `nepse_market_data.py` official endpoints, `nepse_scraper.py` live index with fallbacks, `merolagani_history.py` deep history, `historical_nepse_loader.py` CSV parser), `activities/`, `workflows/`, `register_schedules.py`, `worker.py`, `manage_data.py` (coverage report + stale-data cleanup CLI), `historical-data/` (CSV exports imported on startup).
- `news-service/` — Temporal worker for news: live portal scraping (`scraper/scrapers.py`) and historical backfills (sitemap / cursor / sequential-id discovery, GDELT daily, article-field repair).
- `api-service/` — FastAPI (`main.py`, `routers/`, `services/`, `manage.py create-admin`). Reads the DB; starts the news historical backfill workflow via Temporal (`/admin/historical/backfill`).
- `dashboard/` — React + TypeScript + Vite + Tailwind (recharts). Routes `/login`, `/`, `/news`, `/news/:id`, `/logs`, `/technicals`; all but `/login` behind `ProtectedRoute`. `dist/` is committed build output — don't hand-edit it.
- `nginx/` — builds the dashboard (pnpm) and serves it; proxies `/api/` to `api-service:8001`.
- `scripts/` — one-off tools: `nepsealpha-scraper/` (sharesansar/nepsealpha index CSV downloaders + `seed_from_csv.py`), `export_nepse_news_to_files.py`.
- `data/` — `pgsql/` (Postgres bind-mounted data dir, root-owned), `sector-2021-2026/` (index CSV exports), `nepse_news/` (exported article text files).
- `thesis/` — the LaTeX research proposal the datasets exist for.
- `init.sql` / `init2.sql` — old SQL dumps; `init.sql` is mounted into Postgres's `docker-entrypoint-initdb.d` (only runs on an empty data dir).
- `test.py` — scratch script for probing the NEPSE API; not a test suite.

There is no automated test suite. Verify changes by running activities against the live API/DB (see "Testing changes") and checking `manage_data.py coverage` / `pipeline_run_logs`.

## Architecture

**Services** (`docker-compose.yml`): `db` (Postgres 15, container `nepse-postgres-db`, TZ Asia/Kathmandu), `temporal` + `temporal-ui` (:8080), `nepse-service`, `news-service`, `api-service` (:8001), `nginx` (:80).

**Temporal does all scheduling.** Each worker's `register_schedules.py` upserts its schedules on startup (idempotent create-or-update); workflows are thin orchestration, activities do the I/O. Task queues: `nepse-market-queue` (nepse-service), `news-scraper-queue` (news-service). Every workflow run writes one `pipeline_run_logs` row (`nepse_source` identifies the job) — the dashboard's Logs page reads it, and it's the first place to look when a dataset stops growing.

**nepse-service schedules** (all times NPT; NEPSE trades Mon–Fri since April 2026, Sun–Thu before):

| Schedule | When | Workflow → table |
|---|---|---|
| index | every `NEPSE_SCRAPER_INTERVAL_MINUTES` (1), market hours, needs `LIVE_NEPSE_SCRAPE_ENABLED=true` | `NepseIndexScrapeWorkflow` → `nepse_index` (all 17 indices; official API, nepsetrading/merolagani fallback) |
| today-price | every minute, market hours | → `nepse_today_price` |
| floor sheet | every minute, market hours | → `nepse_floorsheet` (latest 500 contracts) |
| sector summary | every minute, market hours | → `nepse_sector_summary` |
| market depth | every minute, market hours | → `nepse_market_depth` (`MARKET_DEPTH_BATCH_SIZE` of the `MARKET_DEPTH_TOP_N` most liquid stocks per tick) |
| floor-sheet EOD sweep | Mon–Fri 15:20 and 17:00 | `NepseFloorSheetEodSweepWorkflow` → completes the day's `nepse_floorsheet` + fills broker ids |
| end of day | Mon–Fri 15:40 | `NepseEndOfDayWorkflow` → official daily bars into `nepse_stock_daily` / `nepse_index_daily`, today's ticks into `nepse_intraday_tick` |
| research backfill | Saturday 06:00, plus once on every worker startup | `ResearchHistoryBackfillWorkflow` → `nepse_security`, `nepse_index_daily`, `nepse_stock_daily`, `nepse_intraday_tick` |
| floor-sheet history | Sunday 06:00, plus once on every worker startup | `FloorSheetHistoryBackfillWorkflow` → completes past `nepse_floorsheet` sessions (broker ids + missed trades) from merolagani, `FLOORSHEET_BACKFILL_START_DATE` .. yesterday; continue-as-new every 100 sessions |
| CSV import | once on startup | `HistoricalNepseCsvImportWorkflow` → `nepse_index` + `nepse_index_daily` (idempotent via a `pipeline_run_logs` success row with message `historical_nepse_csv_import_v2`) |

"Market hours" = `is_market_open_activity`: Mon–Fri 10:55–15:05 NPT **and** NEPSE's own `/api/nots/nepse-data/market-open` status says OPEN (so holidays are skipped). During the post-close padding it also requires that today's session was actually seen; if the status call fails it degrades to the clock gate. Writers additionally drop rows whose `businessDate` isn't today.

Calendar schedules are written in UTC via `_npt_calendar()` (NPT is fixed UTC+5:45, no DST) rather than `time_zone_name`. Interval schedules use `_npt_aligned_offset()` so grids land on NPT wall-clock boundaries. (news-service's `HISTORICAL_DAILY_HOUR_NPT` calendar is *not* converted, so it actually fires at that hour UTC.)

**Data flow to the frontend:** dashboard → `/api/...` → Nginx → `api-service` → Postgres. The API reads `nepse_index`, `nepse_news` and `pipeline_run_logs`; the research tables are for analysis code (SQL/pandas), not the dashboard.

**Auth:** api-service issues HS256 JWTs (`JWT_SECRET`, `JWT_TTL_MINUTES`) as an httponly cookie `nepse_access_token` or bearer token. Accounts live in `admin_users` (no signup; `docker compose exec api-service python manage.py create-admin`). `/dashboard/*` and `/admin/*` require auth; `/articles`, `/nepse-index`, `/health` are public.

## Database

All timestamps are **naive NPT** (`scraped_at` defaults come from the DB's `now()` in Asia/Kathmandu). Schema changes go through a new Alembic revision in `nepse-common/alembic/versions/` plus the matching model — never ad-hoc DDL.

### Live market data (nepalstock.com.np, since 2026-09-15 unless noted)
- `nepse_index` — one row per index per scrape: `value`, `change`, `percent_change`. Mixed granularity: one 15:00 close per trading day from the CSV import (2021-01-17 → 2026-06-29), irregular ticks 2026-06-29 → 09-14, 1-minute after. Dashboard source; for research use `nepse_index_daily` / `nepse_intraday_tick`.
- `nepse_today_price` — every traded security's snapshot each minute (`ltp`, OHLC so far, volume, turnover, `average_traded_price`, `last_updated_time` = time of the security's last trade). `close_price` is always NULL intraday (NEPSE sets it only after the close). `ltp`/volume are NULL before 2026-09-23.
- `nepse_floorsheet` — every trade (`contract_id` unique per `business_date`, `trade_time` to the microsecond, quantity, rate, `buyer/seller_member_id` + broker names, `stock_id`). NEPSE serves broker fields only **after 15:00**, so intraday rows have them NULL until the EOD sweep upserts them (`ON CONFLICT` fills NULL columns only). Past sessions (NEPSE can't serve them) are completed from merolagani's floor-sheet history by `FloorSheetHistoryBackfillWorkflow`: broker ids for every trade, broker names (only for sessions within 90 days — firms rename/merge) where the id was seen in a NEPSE sweep, and the missing trades — which have `trade_time` NULL and no `stock_id`/`trade_book_id` (merolagani doesn't publish them).
- `nepse_market_depth` — order-book snapshots (`buy_levels`/`sell_levels` JSONB, ≤5 levels each).
- `nepse_sector_summary` — per-sector turnover/volume/transactions per minute (empty before 2026-10-15: the endpoint is GET-only and was being POSTed).

### Research datasets (built by the research/EOD workflows)
- `nepse_index_daily` (PK `index_name, trade_date`) — daily OHLC + turnover for all 17 indices. NEPSE from 2000-01-03, most sub-indices from 2014–2016. Its NEPSE rows are the **trading calendar**. `volume`/`total_transactions` exist only for official rows (last ~1 year).
- `nepse_stock_daily` (PK `symbol, trade_date`) — every equity incl. delisted (~490). Raw `open..close, volume` plus `adj_*` (bonus/right-adjusted; use these for returns — raw prices have huge ex-date drops). `adj_*` are refreshed weekly (factors change retroactively) and are NULL for rows added since the last refresh.
- `nepse_intraday_tick` (PK `symbol, tick_time`) — `price` + `volume` point observations: indices ~1 per minute back to ~2018; equities only if listed in `INTRADAY_BACKFILL_STOCKS`. Not bars and not minute-aligned — resample before computing returns.
- `nepse_security` — security master (sector, instrument type, status A/S/D).
- `research_backfill_state` — resume cursors (`intraday`/symbol windows; `daily_full_refresh` last run).
- `research_index_drawdown` (view) — per index/day: `log_return`, `running_peak`, `drawdown` over `nepse_index_daily`. `manage_data.py crash-events` turns it into drawdown episodes (crash ground truth); the crash threshold is a modelling choice, not stored.

Source precedence for the daily tables (`db/upserts.py`): `nepalstock` (official) > `merolagani` > `csv`. A lower-ranked source never overwrites a higher one; `adj_*` always come from merolagani.

### Other
`nepse_news` (articles, deduped by `url`, `portal_tier` finance/general), `historical_backfill_*` / `historical_cursor_state` / `historical_idwalk_cursor` (news backfill queues and cursors), `pipeline_run_logs`, `admin_users`.

## External sources — gotchas

**nepalstock.com.np official API** (`scraper/nepse_wasm_auth.py`): every call needs `Authorization: Salter <token>`, derived per request from `/api/authenticate/prove` salts through the bundled `nepse.wasm`; many POST endpoints also need a numeric payload `id` (`build_payload_id`). TLS chain is incomplete → `verify=False` (only for this host). Verified behaviours:
- History is shallow: `/api/nots/index/history/{id}` and `/api/nots/market/history/security/{id}` keep ~1 year; `today-price?businessDate=` only accepts the last few days ("Searched Date is not valid."). The floor sheet is the **latest session only** (`businessDate` ignored) — past sessions come from merolagani instead.
- `/api/nots/sectorwise` is GET-only. `/api/nots/nepse-index` gives the 4 headline indices, `/api/nots` the 13 sub-indices.
- Floor sheet pages via `page`/`size=500`; `sort=contractId,desc` orders by segment (contract-id digits 9–10) then sequence, not by time, and pages shift while the market is open — full sweeps are exact only after the close.
- On holidays every endpoint keeps serving the previous session; always check `businessDate`.

**merolagani.com Floorsheet.aspx** (`scraper/merolagani_floorsheet.py`): ASP.NET WebForms — search a date by postback (`txtFloorsheetDateFilter`, MM/DD/YYYY), then 500-row pages via the pager's `hdnCurrentPage` (any page can be jumped to); every postback must carry the previous response's `__VIEWSTATE`. History back to ~2020; contract ids match NEPSE's; no trade time or broker names.

**merolagani.com chart handler** (`scraper/merolagani_history.py`, `TechnicalChartHandler.ashx?type=get_advanced_chart`): no auth. Symbols are tickers or the index labels in `index_registry.py`. Daily `t` falls on the bar's **UTC** date (not midnight-aligned). Intraday responses look like OHLC but `o==h==l==c` with second-resolution `t` — they are ticks. Indices' `v` is NPR turnover, equities' `v` is shares. Pace requests (`MEROLAGANI_REQUEST_PAUSE_SECONDS`).

## Configuration

Everything flows through `nepse_common/config.py: load_app_config()` from `.env` (template: `.env.example`, keep both in sync when adding settings). nepse-service knobs: `NEPSE_SCRAPER_INTERVAL_MINUTES`, `LIVE_NEPSE_SCRAPE_ENABLED`, `SCRAPER_REQUEST_TIMEOUT`, `MARKET_DEPTH_TOP_N`, `MARKET_DEPTH_BATCH_SIZE`, `RESEARCH_BACKFILL_ENABLED`, `RESEARCH_BACKFILL_ON_STARTUP`, `INTRADAY_BACKFILL_START_DATE`, `INTRADAY_BACKFILL_INDICES`, `INTRADAY_BACKFILL_STOCKS` (`""`/`ALL`/comma list), `MEROLAGANI_REQUEST_PAUSE_SECONDS`, `FLOORSHEET_BACKFILL_START_DATE`, `HISTORICAL_NEPSE_CSV_IMPORT_ON_STARTUP`, `HISTORICAL_NEPSE_CSV_DIR`. news-service: `SCRAPER_INTERVAL_MINUTES`, `HISTORICAL_DAILY_*`, `HISTORICAL_NEWS_BACKFILL_ENABLED`, `NEPSE_NEWS_FIELDS_BACKFILL_ENABLED`, etc. Auth: `JWT_SECRET`, `JWT_TTL_MINUTES`, `COOKIE_SECURE`. Temporal: `TEMPORAL_ADDRESS`.

## Commands

```bash
# Full stack
cp .env.example .env            # first time; fill in credentials
docker compose up -d --build    # dashboard http://localhost, API :8001, Temporal UI :8080

# Rebuild/restart one service after code changes (nepse-common changes need a rebuild of every service using it)
docker compose up -d --build nepse-service

# Migrations (run after pulling schema changes; additive ones are safe while workers run)
docker compose run --rm --no-deps nepse-service sh -c 'cd /nepse-common && alembic upgrade head'
docker compose run --rm --no-deps nepse-service sh -c 'cd /nepse-common && alembic revision -m "..."'

# Dataset coverage report / quarantine rows scraped on non-trading days (dry run unless --apply) / crash labels
docker compose exec nepse-service python manage_data.py coverage
docker compose exec nepse-service python manage_data.py cleanup-stale [--apply]
docker compose exec nepse-service python manage_data.py crash-events --index NEPSE --threshold 0.2 [--csv]

# Admin account for the dashboard
docker compose exec api-service python manage.py create-admin

# psql
docker exec -it nepse-postgres-db psql -U superset -d nepse

# Dashboard dev
cd dashboard && pnpm install && pnpm dev    # :5173 (build: pnpm build)
```

Trigger a workflow by hand (e.g. after a missed evening) from the Temporal UI (:8080) or a one-off client, e.g. start `NepseFloorSheetEodSweepWorkflow` on task queue `nepse-market-queue` — it must run before the next session opens.

## Testing changes

There are no unit tests. To exercise an activity against the real API/DB without disturbing the running worker, build the image and run it in a one-off container with `temporalio.testing.ActivityEnvironment`:

```bash
docker compose build nepse-service
docker compose run --rm --no-deps -v $PWD/my_check.py:/tmp/check.py:ro nepse-service python /tmp/check.py
# my_check.py: sys.path.insert(0, "/app"); await ActivityEnvironment().run(some_activity, *args)
```

Avoid running the 1-minute timeseries writers this way during market hours (they'd insert duplicate snapshots next to the live worker's); the upsert-based writers (floor sheet, research tables) are safe to re-run.

## Conventions

- Activities are `async def`; wrap blocking `requests` calls in `asyncio.to_thread`. Pacing sleeps may live in activities (`asyncio.sleep`); long activities heartbeat and are given a `heartbeat_timeout`.
- Workflow code must stay deterministic: no I/O, use `workflow.now()` / `workflow.sleep()`. Importing config inside `workflow.unsafe.imports_passed_through()` is the existing pattern.
- Large result sets (full floor sheet, multi-year histories) are written inside the activity — never returned through Temporal (payload size limits).
- Writers to research/natural-key tables must be idempotent upserts; timeseries snapshot tables (`nepse_index`, `nepse_today_price`, `nepse_market_depth`, `nepse_sector_summary`) are plain inserts.
- Per-item failures in long loops are recorded and skipped, and the summary goes into the run's `pipeline_run_logs` message.
