# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

A pipeline that scrapes 20 Nepali news portals plus the NEPSE (Nepal Stock Exchange) live market index every 30 minutes, stores everything in PostgreSQL, and exposes it via a FastAPI backend and a React dashboard served through Nginx. It also runs a daily historical news backfill and can import multi-year historical NEPSE index data from CSV exports.

Note: the README describes an idealized `nepali-news-pipeline/` layout (e.g. a top-level `config`/`db`/`scraper`), but the actual backend code lives under `nepse-news-scraper/`. Trust the directory layout below over the README when they disagree.

## Repository Layout

- `nepse-news-scraper/` — Python/FastAPI backend (the actual pipeline code)
  - `main.py` — FastAPI app: auth, public API, dashboard API, starts the scheduler on startup
  - `config/config.py` — loads all settings from env vars into frozen dataclasses (`DatabaseConfig`, `ScraperConfig`, `AppConfig`)
  - `db/connection.py` — psycopg2 connection + `ensure_table_exists` (creates `nepse_news`, `nepse_index`, `pipeline_run_logs` with retry/backoff, since the DB container may not be ready yet)
  - `db/writer.py` — all INSERT logic; articles are deduped by `url` (`ON CONFLICT DO NOTHING`), historical NEPSE rows deduped by `(index_name, scraped_at)`
  - `scraper/scrapers.py` — the 20 portal scrapers (BeautifulSoup), tier-tagged `finance`/`general`
  - `scraper/nepse_scraper.py`, `scraper/merolagani_scraper.py` — live NEPSE main + sector index scraping
  - `scraper/historical_scraper.py`, `scraper/historical_nepse_loader.py` — daily historical news backfill and CSV-based historical NEPSE import
  - `scraper/scheduler.py` — APScheduler `BlockingScheduler` wiring; owns the whole pipeline run lifecycle
  - `historical-data/` — checked-in CSV exports (per-sector NEPSE price history) imported on startup
- `dashboard/` — React + TypeScript + Vite + Tailwind frontend (recharts for charts, react-router-dom for routing)
- `nginx/` — reverse proxy: serves the built dashboard and proxies `/api/` to the FastAPI container
- `docker-compose.yml` — wires together `nepse-news-api` (FastAPI), `db` (Postgres 15), and `nginx`
- `init.sql` / `init2.sql` — large SQL dumps mounted into Postgres's `docker-entrypoint-initdb.d` for seeding/restoring data
- `test.py` (repo root) — a standalone scratch script for probing the NEPSE API directly; not part of a test suite

There is no automated test suite in this repository.

## Architecture

**Single FastAPI process does two jobs.** `main.py`'s `on_startup` hook both ensures DB tables exist and launches the APScheduler loop on a background daemon thread (`_start_scheduler_once`). The scheduler thread is a `BlockingScheduler`, so it owns its own thread; the FastAPI/uvicorn thread only serves HTTP.

**Pipeline run flow** (`scraper/scheduler.py: run_pipeline`), triggered every `SCRAPER_INTERVAL_MINUTES`:
1. Scrape all 20 portals (`scraper.scrapers.scrape_all`) — always runs.
2. Write articles to `nepse_news`, deduped by URL.
3. Conditionally scrape live NEPSE index (`scraper.nepse_scraper.scrape_all_nepse_data`) — only if `LIVE_NEPSE_SCRAPE_ENABLED=true` AND the market is currently open (Mon–Fri, 11:00–14:59 NPT, checked in `_is_market_open`).
4. Every run's outcome (success/failure, counts, duration) is written to `pipeline_run_logs`, which the dashboard reads via `/dashboard/pipeline-logs`.

A separate cron-triggered job (`historical_daily_pipeline`, scheduled at `HISTORICAL_DAILY_HOUR_NPT:HISTORICAL_DAILY_MINUTE_NPT` NPT) backfills the previous day's articles if `HISTORICAL_DAILY_ENABLED=true`.

On scheduler startup, if `HISTORICAL_NEPSE_CSV_IMPORT_ON_STARTUP=true`, CSVs under `HISTORICAL_NEPSE_CSV_DIR` are parsed and imported once — idempotency is enforced by checking `pipeline_run_logs` for a prior successful run with message `historical_nepse_csv_import` (`has_successful_pipeline_message`), not by a DB migration flag.

**Auth is separate from the scraping pipeline.** `main.py` implements its own JWT auth (PyJWT, HS256) with a single hardcoded admin user from env vars (`USER_EMAIL`/`USER_PASSWORD`), issuing an httponly cookie (`nepse_access_token`) or bearer token. All `/dashboard/*` and `/admin/*` endpoints require `_require_auth`; `/articles`, `/nepse-index`, and `/health` are public.

**Historical backfill admin endpoints are currently stubbed.** `_start_historical_backfill` and the actual background-thread launch in `admin_start_historical_backfill` are commented out in `main.py` — the endpoint validates dates and returns a response but does not actually trigger a backfill. Same for the startup backfill block at the bottom of `start_scheduler` in `scheduler.py` (also commented out). Be aware of this when touching backfill-related code — the wiring exists but is intentionally disabled.

**Data flow to the frontend:** React dashboard (`dashboard/src/App.tsx`) hits `/api/...` which Nginx proxies to the FastAPI container at `http://nepse-news-api:8001/`. Routes: `/login`, `/` (dashboard overview), `/news`, `/logs`, all behind `ProtectedRoute` except `/login`.

## Configuration

All runtime config flows through `config/config.py: load_app_config()`, reading from `.env` (see `.env.example` for the base set). Key scraper knobs not in `.env.example` but read from env: `LIVE_NEPSE_SCRAPE_ENABLED`, `HISTORICAL_DAILY_ENABLED`, `HISTORICAL_START_DATE`, `HISTORICAL_DAILY_HOUR_NPT`/`_MINUTE_NPT`, `HISTORICAL_REQUEST_TIMEOUT`, `HISTORICAL_MAX_RECORDS_PER_PORTAL_PER_DAY`, `HISTORICAL_NEPSE_CSV_IMPORT_ON_STARTUP`, `HISTORICAL_NEPSE_CSV_DIR`. Auth-related env vars (`USER_EMAIL`, `USER_PASSWORD`, `JWT_SECRET`, `JWT_TTL_MINUTES`, `COOKIE_SECURE`) are read directly in `main.py`, not through `AppConfig`.

## Commands

### Run the full stack (API + Postgres + Nginx/dashboard)
```bash
cp .env.example .env   # fill in DB credentials first
docker-compose up --build
```
- Dashboard: `http://localhost`
- FastAPI direct: `http://localhost:8001`

### Backend only, locally
```bash
cd nepse-news-scraper
pip install -r requirements.txt
python main.py   # or: uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```
Requires a reachable Postgres matching `POSTGRES_*` env vars (defaults point to a `db` host, so override `POSTGRES_HOST` for local runs outside Docker).

### Dashboard only, locally
```bash
cd dashboard
npm install
npm run dev       # Vite dev server on :5173
npm run build     # production build to dashboard/dist
npm run preview   # preview a production build on :4173
```

### Rebuilding just one service
```bash
docker-compose up --build nepse-news-api
docker-compose up --build nginx
```
