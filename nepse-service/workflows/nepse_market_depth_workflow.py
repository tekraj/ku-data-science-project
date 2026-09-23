from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from nepse_common.config import load_app_config

    from activities.nepse_activities import is_market_open_activity
    from activities.nepse_market_activities import (
        MARKET_DEPTH_BATCH_ITEM_PAUSE_SECONDS,
        MARKET_DEPTH_BATCH_SIZE,
        get_security_ids_activity,
        scrape_market_depth_for_security_activity,
        write_market_depth_activity,
    )
    from activities.pipeline_log_activities import write_pipeline_run_log_activity

_DEFAULT_RETRY_POLICY = RetryPolicy(maximum_attempts=3)


@workflow.defn
class NepseMarketDepthScrapeWorkflow:
    """Scrapes the bid/ask market-depth ladder for a bounded batch of
    listed securities per tick and writes to nepse_market_depth. Gated to
    market hours (see NepseTodayPriceScrapeWorkflow for the rationale).

    Unlike today-price/sector-summary/floor-sheet (one request per tick),
    market depth is one request PER SECURITY (~250+ listed companies), so
    scraping all of them on every 1-minute tick would hammer
    nepalstock.com.np and likely blow the tick's activity timeout. Instead:
      1. Fetch the full security-id list (one request).
      2. Walk through it MARKET_DEPTH_BATCH_SIZE securities at a time,
         starting from an offset derived from workflow.now() (see below)
         that changes tick to tick, wrapping around the list, so every
         security gets refreshed periodically rather than only ever
         scraping the first MARKET_DEPTH_BATCH_SIZE.
      3. Pace consecutive per-security fetches
         MARKET_DEPTH_BATCH_ITEM_PAUSE_SECONDS apart via workflow.sleep --
         same pattern as HistoricalSitemapBackfillTickWorkflow's
         _BATCH_ITEM_PAUSE_SECONDS (news-service), just renamed/re-tuned
         for this workflow's own batch size.

    A full rotation through every listed security thus takes
    ceil(total_securities / MARKET_DEPTH_BATCH_SIZE) ticks (minutes), not
    one tick -- an accepted tradeoff for keeping each individual tick fast
    and polite to nepalstock.com.np, per the brief's ask for a small
    per-request pause pattern rather than N rapid-fire requests every
    minute.

    NOTE: the market-depth endpoint path
    (/api/nots/nepse-data/marketdepth/{id}/) is UNVERIFIED against a live
    nepalstock.com.np response -- see scraper/nepse_market_data.py module
    docstring. A wrong path here fails every per-security fetch, which is
    caught per-security (see below) so one bad path degrades gracefully to
    "zero records written, logged once" rather than looping/crashing.
    """

    @workflow.run
    async def run(self) -> dict[str, Any]:
        scraper_cfg = load_app_config().scraper

        started_at = workflow.now()
        status = "success"
        message = "completed"
        error_text: str | None = None
        records = 0

        try:
            market_open = await workflow.execute_activity(
                is_market_open_activity,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DEFAULT_RETRY_POLICY,
            )

            if not market_open:
                message = "market closed - market-depth skipped"
            else:
                securities = await workflow.execute_activity(
                    get_security_ids_activity,
                    args=[scraper_cfg.request_timeout],
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=_DEFAULT_RETRY_POLICY,
                )

                if not securities:
                    message = "no securities returned - market-depth skipped"
                else:
                    # Rotate the starting offset using workflow.now() (the
                    # workflow's own logical clock -- replay-deterministic,
                    # unlike wall-clock datetime.now() or Python's salted
                    # built-in hash()) so successive invocations (each a
                    # fresh workflow execution, per the 1-minute schedule)
                    # walk through the security list over time rather than
                    # only ever scraping the first MARKET_DEPTH_BATCH_SIZE,
                    # with no persisted cursor state needed.
                    total = len(securities)
                    batch_size = min(MARKET_DEPTH_BATCH_SIZE, total)
                    start_offset = int(workflow.now().timestamp()) % total

                    written_entries: list[dict[str, Any]] = []
                    for i in range(batch_size):
                        if i > 0:
                            await workflow.sleep(
                                timedelta(seconds=MARKET_DEPTH_BATCH_ITEM_PAUSE_SECONDS)
                            )

                        security = securities[(start_offset + i) % total]
                        entry = await workflow.execute_activity(
                            scrape_market_depth_for_security_activity,
                            args=[
                                security["security_id"],
                                security["symbol"],
                                scraper_cfg.request_timeout,
                            ],
                            start_to_close_timeout=timedelta(seconds=30),
                            retry_policy=_DEFAULT_RETRY_POLICY,
                        )
                        if entry is not None:
                            written_entries.append(entry)

                    if written_entries:
                        records = await workflow.execute_activity(
                            write_market_depth_activity,
                            args=[written_entries],
                            start_to_close_timeout=timedelta(minutes=1),
                            retry_policy=_DEFAULT_RETRY_POLICY,
                        )
        except Exception as e:  # noqa: BLE001 - mirrors NepseIndexScrapeWorkflow's broad except
            status = "failed"
            message = "market-depth pipeline crashed"
            error_text = str(e)

        finished_at = workflow.now()
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)

        try:
            await workflow.execute_activity(
                write_pipeline_run_log_activity,
                args=[
                    {
                        "status": status,
                        "message": message,
                        "error_text": error_text,
                        "news_total": 0,
                        "news_inserted": 0,
                        "nepse_records": records,
                        "nepse_source": "nepalstock_market_depth",
                        "started_at": started_at.isoformat(),
                        "finished_at": finished_at.isoformat(),
                        "duration_ms": duration_ms,
                    }
                ],
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=_DEFAULT_RETRY_POLICY,
            )
        except Exception as log_err:  # noqa: BLE001
            workflow.logger.error(f"[MarketDepth] Failed to write run log: {log_err}")

        return {"status": status, "message": message, "error_text": error_text, "records": records}
