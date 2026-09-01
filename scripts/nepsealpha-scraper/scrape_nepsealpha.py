"""
Downloads missing/gapped historical daily price CSVs from nepsealpha.com/nepse-data
for NEPSE main index + sector indices, matching the existing repo convention:

    data/sector-2021-2026/nepsealpha_export_price_<SYMBOL>_<START>_<END>_unadjusted.csv

Run this on your own machine with a real display -- nepsealpha.com is behind
Cloudflare bot-management and blocks the actual data-fetch (POST /nepse-data)
from fully headless/automated sessions. This script runs a REAL, VISIBLE
browser (headless=False).

For the FIRST job, you drive the whole flow by hand: solve any Cloudflare
challenge, select the symbol/date range yourself, click Filter, and click
whatever actually downloads the CSV. The script records every click you make
during that phase and infers the export control's selector from it, so it
doesn't have to guess -- then it automates the rest of the jobs using that
same selector.

Setup:
    cd scripts/nepsealpha-scraper
    python3 -m venv venv
    ./venv/bin/pip install -r requirements.txt
    ./venv/bin/python -m playwright install chromium

Run:
    ./venv/bin/python scrape_nepsealpha.py
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "sector-2021-2026"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class ScrapeJob:
    symbol: str
    start_date: str  # YYYY-MM-DD
    end_date: str  # YYYY-MM-DD


# Gap plan, derived from comparing the checked-in CSVs' date ranges against
# what's already live-scraped into the nepse_index table (see the project
# conversation this script was built from -- re-verify against your own
# current DB state with the accompanying check_gaps.sql before relying on
# this list if time has passed and the live scraper has filled in more days).
JOBS: list[ScrapeJob] = [
    # Mid-history gap: CSV coverage ends ~2026-01-14, live scraping starts 2026-06-29.
    ScrapeJob("BANKING", "2026-01-14", "2026-06-29"),
    ScrapeJob("HYDROPOWER", "2026-01-14", "2026-06-29"),
    ScrapeJob("MANUFACTURE", "2026-01-14", "2026-06-29"),
    ScrapeJob("MICROFINANCE", "2026-01-14", "2026-06-29"),
    ScrapeJob("NONLIFEINSU", "2026-01-14", "2026-06-29"),
    # OTHERS has no live scraper at all -- gap runs to today.
    ScrapeJob("OTHERS", "2026-01-14", "2026-08-21"),
    # No deep history at all yet -- full range needed.
    ScrapeJob("NEPSE", "2021-01-16", "2026-06-29"),
    ScrapeJob("DEVBANK", "2021-01-16", "2026-06-29"),
    ScrapeJob("FINANCE", "2021-01-16", "2026-06-29"),
    ScrapeJob("HOTELS", "2021-01-16", "2026-06-29"),
    ScrapeJob("INVESTMENT", "2021-01-16", "2026-06-29"),
    ScrapeJob("LIFEINSU", "2021-01-16", "2026-06-29"),
    ScrapeJob("TRADING", "2021-01-16", "2026-06-29"),
]


def _output_path(job: ScrapeJob) -> Path:
    return OUTPUT_DIR / f"nepsealpha_export_price_{job.symbol}_{job.start_date}_{job.end_date}_unadjusted.csv"


def _set_date_input(page: Page, element_handle, value: str, label: str) -> None:
    """Sets a native <input type=date> value robustly.

    Playwright's .fill() on date inputs is unreliable across sites -- it can
    silently no-op if the input doesn't fire the events the page's own JS
    listens for (this site's date range is wired up with a JS framework that
    reads the field's value on 'input'/'change', not just whatever raw value
    ends up in the DOM). Setting .value directly via JS and dispatching both
    events, then reading the value back to confirm, is the robust approach.
    """
    element_handle.evaluate(
        """
        (el, value) => {
            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            setter.call(el, value);
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        }
        """,
        value,
    )
    actual = element_handle.evaluate("el => el.value")
    if actual != value:
        raise RuntimeError(
            f"Failed to set {label} date input: wanted {value!r}, page shows {actual!r}. "
            "The date field may need a different interaction (e.g. it ignores "
            "programmatic .value changes) -- inspect the field manually."
        )


def _submit_filter(page: Page, job: ScrapeJob) -> None:
    page.click('button:has-text("Daily")')
    page.wait_for_timeout(300)
    page.select_option("select[name=symbol]", job.symbol)
    page.wait_for_timeout(200)

    date_inputs = page.query_selector_all("input[type=date]")
    if len(date_inputs) < 2:
        raise RuntimeError(
            "Expected 2 date inputs on the page (start/end) but found "
            f"{len(date_inputs)} -- the page layout may have changed."
        )
    _set_date_input(page, date_inputs[0], job.start_date, "start")
    _set_date_input(page, date_inputs[1], job.end_date, "end")
    page.wait_for_timeout(200)

    page.click('button:has-text("Filter")')


def _discover_export_selector(page: Page) -> str:
    """First-job discovery mode: YOU drive the browser (solve any Cloudflare
    challenge, select the symbol/dates, click Filter, click the real export
    control) while this records every click's element info, so we capture
    the real selector instead of guessing at it a second time.
    """
    clicks: list[str] = []

    page.expose_binding(
        "__recordClick",
        lambda source, info: clicks.append(info),
    )
    page.evaluate(
        """
        () => {
            document.addEventListener('click', (e) => {
                const el = e.target.closest('a, button');
                if (!el) return;
                const info = {
                    tag: el.tagName.toLowerCase(),
                    text: (el.innerText || '').trim().slice(0, 60),
                    id: el.id || null,
                    cls: el.className || null,
                    href: el.getAttribute('href') || null,
                };
                window.__recordClick(info);
            }, true);
        }
        """
    )

    print("\n" + "=" * 70)
    print("MANUAL SETUP -- the browser window is now yours.")
    print("1. Solve any Cloudflare challenge if one appears.")
    print("2. Select the first symbol/date range and click Filter yourself.")
    print("3. Once the table renders, click whatever downloads/exports the CSV.")
    print("4. Confirm the file actually downloaded, then come back here.")
    print("=" * 70)
    input("Press Enter once you've clicked the export/download control and it saved a file... ")

    if not clicks:
        print("(No clicks were recorded -- if the export happened via keyboard or a")
        print(" context menu, the selector below can't be auto-detected. You'll need")
        print(" to tell me what you clicked so I can hardcode the right selector.)")
        return _EXPORT_SELECTOR_FALLBACK

    print("\nRecorded clicks (most recent last):")
    for c in clicks:
        print(f"  <{c['tag']}> text={c['text']!r} id={c['id']} class={c['cls']} href={c['href']}")

    # Heuristic: the export control is almost always the LAST clicked element
    # in this flow (Filter, then possibly a menu, then the actual download).
    last = clicks[-1]
    if last["id"]:
        selector = f"#{last['id']}"
    elif last["text"]:
        selector = f'{last["tag"]}:has-text("{last["text"]}")'
    else:
        selector = last["tag"]

    print(f"\nUsing selector from last click: {selector}")
    print("If that's wrong, stop the script (Ctrl+C), tell Claude which of the")
    print("clicks above was the real export control, and it'll hardcode it.\n")
    return selector


_EXPORT_SELECTOR_FALLBACK = 'a:has-text("Export"), button:has-text("Export")'


def _trigger_export_and_get_download(page: Page, selector: str):
    """Triggers the CSV export/download control and returns the download."""
    with page.expect_download(timeout=30000) as download_info:
        page.click(selector)
    return download_info.value


def run() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    remaining = [job for job in JOBS if not _output_path(job).exists()]
    if not remaining:
        print("Nothing to do -- all job output files already exist.")
        return 0

    print(f"{len(remaining)} of {len(JOBS)} jobs remaining (others already downloaded).")

    export_selector: str | None = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=200)
        context = browser.new_context(user_agent=_USER_AGENT, viewport={"width": 1280, "height": 900})
        page = context.new_page()

        for i, job in enumerate(remaining):
            out_path = _output_path(job)
            print(f"\n[{i + 1}/{len(remaining)}] {job.symbol}: {job.start_date} -> {job.end_date}")

            page.goto("https://nepsealpha.com/nepse-data", timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)

            if export_selector is None:
                # First job: do NOT auto-submit the filter. Let the human drive
                # everything (challenge, symbol, dates, Filter, export) once,
                # so we observe the real export control instead of guessing.
                print(f"\n(Pre-fill hint: symbol={job.symbol}, start={job.start_date}, end={job.end_date})")
                export_selector = _discover_export_selector(page)

                print(
                    "\nIf your manual download in step 3 above already saved a file, "
                    "move/rename it to:\n"
                    f"  {out_path}\n"
                    "so this job counts as done. Either way, this script will now take "
                    "over and automate the remaining jobs using the export control you just used."
                )
                input("Press Enter to continue... ")
                continue

            try:
                _submit_filter(page, job)
                download = _trigger_export_and_get_download(page, export_selector)
            except Exception as e:
                print(f"  FAILED to export {job.symbol}: {e}")
                print("  Skipping -- inspect the page manually and adjust the script if this repeats.")
                continue

            download.save_as(str(out_path))
            print(f"  Saved -> {out_path}")

            # Be a polite, low-volume client between requests -- this is a
            # best-effort personal-use scrape, not a bulk-harvesting job.
            time.sleep(5)

        browser.close()

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
