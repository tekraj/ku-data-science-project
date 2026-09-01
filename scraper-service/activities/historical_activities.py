from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from temporalio import activity

from nepse_common.schemas.scraped import ScrapedArticle

from scraper.historical_scraper import scrape_historical_for_date


@activity.defn
async def scrape_historical_day_activity(
    day_iso: str, timeout: int, max_records_per_portal_per_day: int
) -> list[dict[str, Any]]:
    """Scrape GDELT-backed historical articles for one day (unchanged
    business logic, including the module-global _last_gdelt_call_ts rate
    limiter inside historical_scraper.py). Registered ONLY on the dedicated
    historical-gdelt-queue worker (max_concurrent_activities=1) so the
    rate limiter behaves correctly under a single-process worker.

    scrape_historical_for_date is synchronous (blocking requests.get() +
    time.sleep() for GDELT's own retry/backoff, up to ~60s+ per call when
    GDELT is flaky) -- run it via asyncio.to_thread so those blocking calls
    happen on a separate OS thread instead of the shared asyncio event
    loop. Confirmed directly in production: without this, a slow/flaky
    GDELT response froze the ENTIRE worker process's event loop for
    30-60+ seconds at a time, starving every other workflow/activity in
    the same process (including the unrelated historical news backfill
    workflows on the general worker) of the ability to even respond to
    Temporal's workflow task polls -- not a site block, not "done", a
    starvation bug from this call being awaited in-loop instead of
    threaded."""
    target_day = datetime.strptime(day_iso, "%Y-%m-%d").date()

    raw_articles = await asyncio.to_thread(
        scrape_historical_for_date,
        target_day=target_day,
        timeout=timeout,
        max_records_per_portal_per_day=max_records_per_portal_per_day,
    )

    validated: list[dict[str, Any]] = []
    for raw in raw_articles:
        article = ScrapedArticle.model_validate(raw)
        validated.append(article.model_dump(mode="json"))

    return validated
