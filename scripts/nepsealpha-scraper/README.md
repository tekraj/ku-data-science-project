# NEPSE historical index data scraper

Fills gaps in the `nepse_index` table for NEPSE main index + sectors that
either have no deep history yet, or have a mid-history gap between the
checked-in CSV exports (2021-01-16 to ~2026-01-14) and when live scraping
started (2026-06-29).

## Which script to use: `scrape_sharesansar.py` (recommended)

`sharesansar.com` has no Cloudflare protection and its historical-index page
is powered by a plain server-side DataTables JSON endpoint
(`GET /index-history-data`) that a normal HTTP client can call directly — no
browser, no manual challenge-solving. This is the script to use.

```bash
cd scripts/nepsealpha-scraper
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python scrape_sharesansar.py
```

It runs unattended, paginating through each symbol/date-range job and
writing CSVs to `data/sector-2021-2026/` in the same filename convention and
column layout the existing pipeline already expects (kept the
`nepsealpha_export_price_...` prefix so `seed_from_csv.py` /
`historical_nepse_loader.py` pick these up with zero changes, even though
the source site is now different).

**Known quirk**: the endpoint occasionally returns an empty page
(`recordsTotal: 0`) for a request that should have data — observed
directly during development, not reliably reproducible on demand, so the
exact trigger is unconfirmed (tests suggest it's *not* simple request-rate
throttling: several rapid identical requests in a row succeeded in one
test, while a slower retry loop failed in another). The script retries each
page several times with a delay and a fresh session before giving up on
that page — if a job comes back with `FAILED` or fewer rows than expected,
just rerun the script later; already-fully-downloaded jobs are skipped.

Safe to stop and resume: it checks for each job's expected output file
before starting and skips ones that already exist.

## Fallback: `scrape_nepsealpha.py` (Playwright, semi-manual)

Kept in case sharesansar.com ever stops being usable as a source.
`nepsealpha.com` has the same data but sits behind Cloudflare
bot-management — page navigation works, but the actual data-fetch
(`POST /nepse-data`, triggered by the "Filter" button) gets a 403 challenge
in headless mode. This script opens a **real, visible** browser
(`headless=False`); for the first job, you drive the entire flow by hand
(solve any Cloudflare challenge, select symbol/dates, click Filter, click
whatever downloads the CSV) while the script records your clicks and infers
the export control's selector from them, then automates the rest of the
jobs using that selector.

```bash
cd scripts/nepsealpha-scraper
python3 -m venv venv
./venv/bin/pip install playwright
./venv/bin/python -m playwright install chromium
./venv/bin/python scrape_nepsealpha.py
```

This needs a real display (run it on your own machine, not a headless
box/container), and does not attempt to spoof a browser fingerprint or
solve CAPTCHAs programmatically.

## Job list / gap plan

Both scripts share the same job list (symbol + date range). Re-check
against the live DB before running if time has passed (the gap dates below
reflect the state as of 2026-08-21):

| Symbol | Date range needed | Why |
|---|---|---|
| BANKING, HYDROPOWER, MANUFACTURE, MICROFINANCE, NONLIFEINSU | 2026-01-14 → 2026-06-29 | Mid-history gap between CSV export and live scraping |
| OTHERS | 2026-01-14 → 2026-08-21 | No live scraper for this index; gap runs to today |
| NEPSE, DEVBANK, FINANCE, HOTELS, INVESTMENT, LIFEINSU, TRADING | 2021-01-16 → 2026-06-29 | No deep history at all yet, only live data since 2026-06-29 |

To re-derive this list yourself:
```bash
docker exec nepse-postgres-db psql -U superset -d nepse -c "
SELECT index_name, min(scraped_at)::date, max(scraped_at)::date
FROM nepse_index GROUP BY index_name ORDER BY index_name;"
```

sharesansar's own numeric `index_id` values (from its `<select name="index">`
on `/index-history-data`) are hardcoded per job in `scrape_sharesansar.py`'s
`JOBS` list — re-verify them there if sharesansar ever renumbers its indices.

## After downloading

Run the seeding script to import everything (existing CSVs + newly
downloaded ones) into `nepse_index`, deduping against what's already there:

```bash
cd ../../nepse-common   # or wherever your venv with nepse-common installed lives
python ../scripts/nepsealpha-scraper/seed_from_csv.py
```

See that script's own docstring for details.
