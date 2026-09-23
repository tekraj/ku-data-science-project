from __future__ import annotations

from datetime import timedelta

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleUpdate,
)

from nepse_common.config import load_app_config

from workflows.nepse_index_scrape_workflow import NepseIndexScrapeWorkflow
from workflows.nepse_today_price_workflow import NepseTodayPriceScrapeWorkflow
from workflows.nepse_sector_summary_workflow import NepseSectorSummaryScrapeWorkflow
from workflows.nepse_floor_sheet_workflow import NepseFloorSheetScrapeWorkflow
from workflows.nepse_market_depth_workflow import NepseMarketDepthScrapeWorkflow

_GENERAL_QUEUE = "nepse-market-queue"

_NEPSE_INDEX_SCHEDULE_ID = "nepse-index-scrape-schedule"
_TODAY_PRICE_SCHEDULE_ID = "nepse-today-price-scrape-schedule"
_SECTOR_SUMMARY_SCHEDULE_ID = "nepse-sector-summary-scrape-schedule"
_FLOOR_SHEET_SCHEDULE_ID = "nepse-floor-sheet-scrape-schedule"
_MARKET_DEPTH_SCHEDULE_ID = "nepse-market-depth-scrape-schedule"

# Temporal's ScheduleIntervalSpec grid is anchored to the Unix epoch
# (1970-01-01 00:00 UTC) with no offset unless one is given. NPT is UTC+5:45
# -- NOT a multiple of 30 (or 60) minutes -- so an unoffset 30-min grid
# lands on :15/:45 past the NPT hour, not :00/:30. This is exactly why the
# live NEPSE index schedule (gated to market hours 11:00-14:59 NPT in
# is_market_open_activity) was observed firing at 11:15/14:45 instead of
# 11:00/15:00 back when its interval was 30 min: it never actually ticked
# at the open or the last valid pre-close minute. NPT has no DST, so this
# phase is a fixed constant. Ported verbatim from the pre-split
# register_schedules.py (news-service keeps its own identical copy) --
# every interval used in this file (1 min, and the configurable NEPSE
# index interval which defaults to 1 min too) already evenly divides
# 5h45m, so _npt_aligned_offset is a no-op here today, but is kept in case
# nepse_interval_minutes is ever configured to something that needs it
# (e.g. 30/60 min).
_NPT_EPOCH_PHASE = timedelta(hours=5, minutes=45)


def _npt_aligned_offset(interval: timedelta) -> timedelta:
    """The offset to pass to ScheduleIntervalSpec so its firing grid lands
    on clean NPT wall-clock boundaries (:00, interval, 2*interval, ... past
    the NPT hour) instead of wherever the Unix epoch happens to phase to in
    NPT. Only matters for interval values that evenly divide 24h and don't
    already divide 5h45m (e.g. 30/60 min need it, 1/15/45 min don't)."""
    interval_seconds = int(interval.total_seconds())
    phase_seconds = int(_NPT_EPOCH_PHASE.total_seconds()) % interval_seconds
    if phase_seconds == 0:
        return timedelta(0)
    return interval - timedelta(seconds=phase_seconds)


# All 4 new nepalstock.com.np market-data scrapes run on a flat 1-minute
# interval per the explicit ask, independent of the configurable NEPSE
# index interval above.
_MARKET_DATA_INTERVAL = timedelta(minutes=1)


async def upsert_schedule(
    client: Client,
    schedule_id: str,
    spec: ScheduleSpec,
    action: ScheduleActionStartWorkflow,
    policy: SchedulePolicy | None = None,
) -> None:
    """Create the schedule if it does not exist yet, otherwise update it
    in place so re-running the worker is idempotent. Copied verbatim from
    news-service/register_schedules.py -- fully generic, no news/nepse-
    specific logic, so both services keep their own copy rather than
    sharing it as a package import (see nepse-service/activities/
    pipeline_log_activities.py for the same reasoning)."""
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

    nepse_interval = timedelta(minutes=scraper_cfg.nepse_interval_minutes)
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

    market_data_spec = ScheduleSpec(
        intervals=[
            ScheduleIntervalSpec(
                every=_MARKET_DATA_INTERVAL,
                offset=_npt_aligned_offset(_MARKET_DATA_INTERVAL),
            )
        ]
    )

    today_price_action = ScheduleActionStartWorkflow(
        NepseTodayPriceScrapeWorkflow.run,
        id="nepse-today-price-scrape-workflow",
        task_queue=_GENERAL_QUEUE,
    )
    await upsert_schedule(client, _TODAY_PRICE_SCHEDULE_ID, market_data_spec, today_price_action)

    sector_summary_action = ScheduleActionStartWorkflow(
        NepseSectorSummaryScrapeWorkflow.run,
        id="nepse-sector-summary-scrape-workflow",
        task_queue=_GENERAL_QUEUE,
    )
    await upsert_schedule(
        client, _SECTOR_SUMMARY_SCHEDULE_ID, market_data_spec, sector_summary_action
    )

    floor_sheet_action = ScheduleActionStartWorkflow(
        NepseFloorSheetScrapeWorkflow.run,
        id="nepse-floor-sheet-scrape-workflow",
        task_queue=_GENERAL_QUEUE,
    )
    await upsert_schedule(client, _FLOOR_SHEET_SCHEDULE_ID, market_data_spec, floor_sheet_action)

    market_depth_action = ScheduleActionStartWorkflow(
        NepseMarketDepthScrapeWorkflow.run,
        id="nepse-market-depth-scrape-workflow",
        task_queue=_GENERAL_QUEUE,
    )
    await upsert_schedule(
        client, _MARKET_DEPTH_SCHEDULE_ID, market_data_spec, market_depth_action
    )
