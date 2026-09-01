from __future__ import annotations

from datetime import timedelta

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleCalendarSpec,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleRange,
    ScheduleSpec,
    ScheduleUpdate,
)

from nepse_common.config import load_app_config

from workflows.news_scrape_workflow import NewsScrapeWorkflow
from workflows.nepse_index_scrape_workflow import NepseIndexScrapeWorkflow
from workflows.historical_daily_workflow import HistoricalDailyBackfillWorkflow
from workflows.historical_sitemap_backfill_workflow import (
    HistoricalSitemapBackfillTickWorkflow,
    HistoricalBackfillReapWorkflow,
)
from workflows.historical_cursor_backfill_workflow import HistoricalCursorBackfillTickWorkflow
from workflows.historical_idwalk_backfill_workflow import HistoricalIdWalkBackfillTickWorkflow
from workflows.nepse_news_fields_backfill_workflow import NepseNewsFieldsBackfillTickWorkflow

_GENERAL_QUEUE = "nepse-scraper-queue"

_NEWS_SCHEDULE_ID = "news-scrape-schedule"
_NEPSE_INDEX_SCHEDULE_ID = "nepse-index-scrape-schedule"
_HISTORICAL_DAILY_SCHEDULE_ID = "historical-daily-schedule"

# Temporal's ScheduleIntervalSpec grid is anchored to the Unix epoch
# (1970-01-01 00:00 UTC) with no offset unless one is given. NPT is
# UTC+5:45 -- NOT a multiple of 30 (or 60) minutes -- so an unoffset 30-min
# grid lands on :15/:45 past the NPT hour, not :00/:30. This is exactly why
# the NEPSE index schedule (gated to market hours 11:00-14:59 NPT in
# is_market_open_activity) was observed firing at 11:15/14:45 instead of
# 11:00/15:00: it never actually ticked at the open or the last valid
# pre-close minute. NPT has no DST, so this phase is a fixed constant.
_NPT_EPOCH_PHASE = timedelta(hours=5, minutes=45)


def _npt_aligned_offset(interval: timedelta) -> timedelta:
    """The offset to pass to ScheduleIntervalSpec so its firing grid lands
    on clean NPT wall-clock boundaries (:00, interval, 2*interval, ... past
    the NPT hour) instead of wherever the Unix epoch happens to phase to in
    NPT. Only matters for interval values that evenly divide 24h and don't
    already divide 5h45m (e.g. 30/60 min need it, 15/45 min don't)."""
    interval_seconds = int(interval.total_seconds())
    phase_seconds = int(_NPT_EPOCH_PHASE.total_seconds()) % interval_seconds
    if phase_seconds == 0:
        return timedelta(0)
    return interval - timedelta(seconds=phase_seconds)


# One schedule per historical-backfill portal, each on its own independent
# interval and its own work queue (historical_backfill_urls is scoped by
# `source`) so the portals run in parallel with each other. Throughput is
# raised via batch_size (process several URLs per tick, each still its own
# separately-paced request -- see _BATCH_ITEM_PAUSE_SECONDS in the
# workflows) rather than by shortening the interval itself, since a
# shorter interval scales Temporal's own scheduling/history overhead with
# it while a bigger batch does not. SKIP overlap (Temporal's own default,
# set explicitly here for clarity) means a slow tick just causes the next
# firing to be skipped rather than piling up concurrent batches against
# the same site.
SITEMAP_BACKFILL_SOURCES: tuple[str, ...] = ("karobardaily", "myrepublica", "himalayantimes")
CURSOR_BACKFILL_SOURCE = "sharesansar"
# Sequential-numeric-ID sources -- see historical_idwalk_discovery.py.
IDWALK_BACKFILL_SOURCES: tuple[str, ...] = ("setopati", "merolagani", "onlinekhabar")
_BACKFILL_TICK_POLICY = SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP)
_BACKFILL_TICK_INTERVAL = timedelta(minutes=1)
# Each batch item is paced _BATCH_ITEM_PAUSE_SECONDS apart (3s, in the
# workflows) plus its own fetch time, so 15 items comfortably fits inside
# one _BACKFILL_TICK_INTERVAL (60s) without running into the next firing.
_BACKFILL_BATCH_SIZE = 15

# Comfortably more frequent than STALE_CLAIM_TIMEOUT (10 min, in
# historical_sitemap_backfill_activities.py) so an abandoned claim isn't
# stuck for long before being caught and reset.
_BACKFILL_REAP_SCHEDULE_ID = "historical-backfill-reap-schedule"
_BACKFILL_REAP_INTERVAL = timedelta(minutes=5)

# Separate one-time cleanup pass over EXISTING nepse_news rows missing
# published_at/body -- independent of historical_news_backfill_enabled
# (that flag controls discovering NEW pre-2021 articles; this fixes gaps
# in articles already in the table, live-scraped or otherwise).
_FIELDS_BACKFILL_SCHEDULE_ID = "nepse-news-fields-backfill-schedule"
_FIELDS_BACKFILL_INTERVAL = timedelta(minutes=1)
_FIELDS_BACKFILL_BATCH_SIZE = 15


async def upsert_schedule(
    client: Client,
    schedule_id: str,
    spec: ScheduleSpec,
    action: ScheduleActionStartWorkflow,
    policy: SchedulePolicy | None = None,
) -> None:
    """Create the schedule if it does not exist yet, otherwise update it
    in place so re-running the worker is idempotent."""
    try:
        handle = client.get_schedule_handle(schedule_id)

        async def _updater(_input):
            return ScheduleUpdate(
                schedule=Schedule(action=action, spec=spec, policy=policy or SchedulePolicy())
            )

        await handle.update(_updater)
    except Exception:
        # Not found (or any other lookup failure) -- fall back to create.
        try:
            await client.create_schedule(
                schedule_id,
                Schedule(action=action, spec=spec, policy=policy or SchedulePolicy()),
            )
        except Exception as create_err:
            # Schedule may have been created concurrently by another worker
            # instance between the failed get/update and this create call.
            if "already" not in str(create_err).lower():
                raise


async def upsert_all_schedules(client: Client) -> None:
    scraper_cfg = load_app_config().scraper

    news_spec = ScheduleSpec(
        intervals=[ScheduleIntervalSpec(every=timedelta(minutes=scraper_cfg.interval_minutes))]
    )
    news_action = ScheduleActionStartWorkflow(
        NewsScrapeWorkflow.run,
        id="news-scrape-workflow",
        task_queue=_GENERAL_QUEUE,
    )
    await upsert_schedule(client, _NEWS_SCHEDULE_ID, news_spec, news_action)

    nepse_interval = timedelta(minutes=scraper_cfg.interval_minutes)
    nepse_index_spec = ScheduleSpec(
        intervals=[
            ScheduleIntervalSpec(
                every=nepse_interval,
                offset=_npt_aligned_offset(nepse_interval),
            )
        ]
    )
    nepse_index_action = ScheduleActionStartWorkflow(
        NepseIndexScrapeWorkflow.run,
        id="nepse-index-scrape-workflow",
        task_queue=_GENERAL_QUEUE,
    )
    await upsert_schedule(client, _NEPSE_INDEX_SCHEDULE_ID, nepse_index_spec, nepse_index_action)

    if scraper_cfg.historical_daily_enabled:
        historical_spec = ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    hour=[ScheduleRange(start=scraper_cfg.historical_daily_hour_npt)],
                    minute=[ScheduleRange(start=scraper_cfg.historical_daily_minute_npt)],
                )
            ]
        )
        historical_action = ScheduleActionStartWorkflow(
            HistoricalDailyBackfillWorkflow.run,
            id="historical-daily-backfill-workflow",
            task_queue=_GENERAL_QUEUE,
        )
        await upsert_schedule(
            client, _HISTORICAL_DAILY_SCHEDULE_ID, historical_spec, historical_action
        )
    # If historical_daily_enabled is False and the schedule already exists
    # from a prior run, it is intentionally left alone here (out of scope
    # to auto-delete it).

    if scraper_cfg.historical_news_backfill_enabled:
        backfill_tick_spec = ScheduleSpec(intervals=[ScheduleIntervalSpec(every=_BACKFILL_TICK_INTERVAL)])

        for source in SITEMAP_BACKFILL_SOURCES:
            action = ScheduleActionStartWorkflow(
                HistoricalSitemapBackfillTickWorkflow.run,
                args=[source, scraper_cfg.historical_request_timeout, _BACKFILL_BATCH_SIZE],
                id=f"historical-sitemap-backfill-{source}-workflow",
                task_queue=_GENERAL_QUEUE,
            )
            await upsert_schedule(
                client,
                f"historical-sitemap-backfill-{source}-schedule",
                backfill_tick_spec,
                action,
                policy=_BACKFILL_TICK_POLICY,
            )

        cursor_action = ScheduleActionStartWorkflow(
            HistoricalCursorBackfillTickWorkflow.run,
            args=[scraper_cfg.historical_request_timeout, _BACKFILL_BATCH_SIZE],
            id=f"historical-cursor-backfill-{CURSOR_BACKFILL_SOURCE}-workflow",
            task_queue=_GENERAL_QUEUE,
        )
        await upsert_schedule(
            client,
            f"historical-cursor-backfill-{CURSOR_BACKFILL_SOURCE}-schedule",
            backfill_tick_spec,
            cursor_action,
            policy=_BACKFILL_TICK_POLICY,
        )

        for source in IDWALK_BACKFILL_SOURCES:
            idwalk_action = ScheduleActionStartWorkflow(
                HistoricalIdWalkBackfillTickWorkflow.run,
                args=[source, scraper_cfg.historical_request_timeout, _BACKFILL_BATCH_SIZE],
                id=f"historical-idwalk-backfill-{source}-workflow",
                task_queue=_GENERAL_QUEUE,
            )
            await upsert_schedule(
                client,
                f"historical-idwalk-backfill-{source}-schedule",
                backfill_tick_spec,
                idwalk_action,
                policy=_BACKFILL_TICK_POLICY,
            )

        reap_spec = ScheduleSpec(intervals=[ScheduleIntervalSpec(every=_BACKFILL_REAP_INTERVAL)])
        reap_action = ScheduleActionStartWorkflow(
            HistoricalBackfillReapWorkflow.run,
            id="historical-backfill-reap-workflow",
            task_queue=_GENERAL_QUEUE,
        )
        await upsert_schedule(
            client,
            _BACKFILL_REAP_SCHEDULE_ID,
            reap_spec,
            reap_action,
            policy=_BACKFILL_TICK_POLICY,
        )
    # If historical_news_backfill_enabled is False and these schedules
    # already exist from a prior run, they are intentionally left alone
    # here too (same out-of-scope-to-auto-delete rationale as above).

    if scraper_cfg.nepse_news_fields_backfill_enabled:
        fields_backfill_spec = ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=_FIELDS_BACKFILL_INTERVAL)]
        )
        fields_backfill_action = ScheduleActionStartWorkflow(
            NepseNewsFieldsBackfillTickWorkflow.run,
            args=[scraper_cfg.historical_request_timeout, _FIELDS_BACKFILL_BATCH_SIZE],
            id="nepse-news-fields-backfill-workflow",
            task_queue=_GENERAL_QUEUE,
        )
        await upsert_schedule(
            client,
            _FIELDS_BACKFILL_SCHEDULE_ID,
            fields_backfill_spec,
            fields_backfill_action,
            policy=_BACKFILL_TICK_POLICY,
        )
    # Same out-of-scope-to-auto-delete rationale if the flag is off and the
    # schedule already exists.
