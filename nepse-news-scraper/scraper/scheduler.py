from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import date, datetime, time as dtime, timedelta
import pytz

from config import ScraperConfig, load_app_config
from db import has_successful_pipeline_message
from db import write_articles, write_nepse_index, write_nepse_index_history, write_pipeline_run_log
from scraper.historical_nepse_loader import parse_historical_nepse_csvs
from scraper.historical_scraper import scrape_historical_for_date
from scraper.scrapers import scrape_all
from scraper.nepse_scraper import scrape_all_nepse_data

_NST = pytz.timezone("Asia/Kathmandu")


def _now_nst() -> datetime:
    return datetime.now(_NST)


def _is_market_open() -> bool:
    """Return True only on Mon–Fri between 11:00 and 14:59 NPT (market hours)."""
    now = _now_nst()
    if now.weekday() > 4:          # 5=Sat, 6=Sun
        return False
    return dtime(11, 0) <= now.time() < dtime(15, 0)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def run_pipeline() -> None:
    config = load_app_config()
    started_at = _now_nst()
    market_open = _is_market_open()
    status = "success"
    message = "completed"
    error_text = None
    news_total = 0
    news_inserted = 0
    nepse_records = 0
    nepse_source = "none"

    print("\n" + "=" * 60)
    now_str = started_at.strftime("%Y-%m-%d %H:%M:%S %Z")
    weekday = started_at.strftime("%A")
    print(f"[Pipeline] Starting scrape run at {now_str} ({weekday})")
    print(f"[Pipeline] Market open: {market_open}")
    print("=" * 60)

    try:
        # Step 1 — Scrape news portals (always runs)
        articles = scrape_all(
            timeout=config.scraper.request_timeout,
            max_articles_per_portal=config.scraper.max_articles_per_portal,
        )
        news_total = len(articles)

        # Step 2 — Save articles to DB
        news_inserted = write_articles(articles, config.database)

        # Step 3 — optional live NEPSE index scrape (can be disabled when CSV history is used)
        if config.scraper.live_nepse_scrape_enabled and market_open:
            nepse_data = scrape_all_nepse_data(timeout=config.scraper.request_timeout)
            nepse_records = write_nepse_index(nepse_data, config.database)
            nepse_source = str(nepse_data.get("source_used") or nepse_data.get("source") or "unknown")
        else:
            if not config.scraper.live_nepse_scrape_enabled:
                message = "live nepse scrape disabled - news only"
                print("[Pipeline] LIVE_NEPSE_SCRAPE_ENABLED=false — skipping NEPSE index scrape.")
            else:
                message = "market closed - nepse skipped"
                print("[Pipeline] Market closed — skipping NEPSE index scrape.")

        print("[Pipeline] Run complete.")
    except Exception as e:
        status = "failed"
        message = "pipeline crashed"
        error_text = str(e)
        print(f"[Pipeline] Run failed: {e}")
    finally:
        finished_at = _now_nst()
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        try:
            write_pipeline_run_log(
                {
                    "status": status,
                    "message": message,
                    "error_text": error_text,
                    "news_total": news_total,
                    "news_inserted": news_inserted,
                    "nepse_records": nepse_records,
                    "nepse_source": nepse_source,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "duration_ms": duration_ms,
                },
                config.database,
            )
        except Exception as log_err:
            print(f"[Pipeline] Failed to write run log: {log_err}")


def run_historical_daily_pipeline(target_day: date | None = None) -> dict[str, int | str]:
    """Scrape a single day's historical articles and save to DB."""
    config = load_app_config()
    day = target_day or (_now_nst().date() - timedelta(days=1))

    print("\n" + "=" * 60)
    print(f"[Historical] Starting daily historical ingest for {day.isoformat()}")
    print("=" * 60)

    articles = scrape_historical_for_date(
        target_day=day,
        timeout=config.scraper.historical_request_timeout,
        max_records_per_portal_per_day=config.scraper.historical_max_records_per_portal_per_day,
    )
    inserted = write_articles(articles, config.database)

    print(
        f"[Historical] Completed day {day.isoformat()} | "
        f"fetched={len(articles)} inserted={inserted}"
    )
    return {
        "day": day.isoformat(),
        "fetched": len(articles),
        "inserted": inserted,
    }


def run_historical_backfill(start_date: date, end_date: date) -> dict[str, int | str]:
    """Backfill selected portals from start_date to end_date (inclusive), day by day."""
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date")

    total_days = 0
    total_fetched = 0
    total_inserted = 0

    current = start_date
    while current <= end_date:
        result = run_historical_daily_pipeline(current)
        total_days += 1
        total_fetched += int(result["fetched"])
        total_inserted += int(result["inserted"])
        current += timedelta(days=1)

    print("\n" + "=" * 60)
    print(
        f"[Historical] Backfill finished {start_date.isoformat()} -> {end_date.isoformat()} | "
        f"days={total_days} fetched={total_fetched} inserted={total_inserted}"
    )
    print("=" * 60)

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "days": total_days,
        "fetched": total_fetched,
        "inserted": total_inserted,
    }


def _run_historical_for_previous_day() -> None:
    try:
        run_historical_daily_pipeline(target_day=_now_nst().date() - timedelta(days=1))
    except Exception as e:
        print(f"[Historical] Daily run failed: {e}")


def start_scheduler(interval_minutes: int, scraper_config: ScraperConfig | None = None) -> None:
    scraper_cfg = scraper_config or load_app_config().scraper

    if scraper_cfg.historical_nepse_csv_import_on_startup:
        historical_log_message = "historical_nepse_csv_import"
        try:
            config = load_app_config()
            already_done = has_successful_pipeline_message(
                historical_log_message,
                config.database,
            )

            if already_done:
                print("[Scheduler] Historical NEPSE CSV import already completed previously. Skipping startup import.")
            else:
                started_at = _now_nst()
                rows = parse_historical_nepse_csvs(scraper_cfg.historical_nepse_csv_dir)
                inserted = write_nepse_index_history(rows, config.database)
                finished_at = _now_nst()

                write_pipeline_run_log(
                    {
                        "status": "success",
                        "message": historical_log_message,
                        "error_text": None,
                        "news_total": 0,
                        "news_inserted": 0,
                        "nepse_records": inserted,
                        "nepse_source": "csv_historical",
                        "started_at": started_at,
                        "finished_at": finished_at,
                        "duration_ms": int((finished_at - started_at).total_seconds() * 1000),
                    },
                    config.database,
                )

                print(
                    "[Scheduler] Historical NEPSE CSV import completed "
                    f"from {scraper_cfg.historical_nepse_csv_dir} | parsed={len(rows)} inserted={inserted}"
                )
        except Exception as e:
            print(f"[Scheduler] Historical NEPSE CSV import failed: {e}")
            try:
                config = load_app_config()
                now = _now_nst()
                write_pipeline_run_log(
                    {
                        "status": "failed",
                        "message": historical_log_message,
                        "error_text": str(e),
                        "news_total": 0,
                        "news_inserted": 0,
                        "nepse_records": 0,
                        "nepse_source": "csv_historical",
                        "started_at": now,
                        "finished_at": now,
                        "duration_ms": 0,
                    },
                    config.database,
                )
            except Exception as log_err:
                print(f"[Scheduler] Failed to write historical import log: {log_err}")

    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_pipeline,
        trigger="interval",
        minutes=interval_minutes,
        id="nepse_pipeline",
        max_instances=1,
    )

    if scraper_cfg.historical_daily_enabled:
        scheduler.add_job(
            _run_historical_for_previous_day,
            trigger="cron",
            hour=scraper_cfg.historical_daily_hour_npt,
            minute=scraper_cfg.historical_daily_minute_npt,
            timezone=_NST,
            id="historical_daily_pipeline",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )

    print(f"[Scheduler] Pipeline will run every {interval_minutes} minutes.")
    if scraper_cfg.historical_daily_enabled:
        print(
            "[Scheduler] Historical daily ingest scheduled at "
            f"{scraper_cfg.historical_daily_hour_npt:02d}:{scraper_cfg.historical_daily_minute_npt:02d} NPT "
            "for previous day."
        )

    print("[Scheduler] Running first pass now...")
    run_pipeline()

    # if scraper_cfg.historical_backfill_on_startup:
    #     historical_news_log_message = "historical_news_backfill_startup"
    #     try:
    #         config = load_app_config()
    #         already_done = has_successful_pipeline_message(
    #             historical_news_log_message,
    #             config.database,
    #         )

    #         if already_done:
    #             print("[Scheduler] Historical news backfill already completed previously. Skipping startup backfill.")
    #         else:
    #             start_date = _parse_date(scraper_cfg.historical_start_date)
    #             end_date = _now_nst().date() - timedelta(days=1)
    #             if end_date >= start_date:
    #                 started_at = _now_nst()
    #                 print(
    #                     "[Scheduler] HISTORICAL_BACKFILL_ON_STARTUP is enabled. "
    #                     f"Backfilling {start_date.isoformat()} -> {end_date.isoformat()}"
    #                 )
    #                 summary = run_historical_backfill(start_date, end_date)
    #                 finished_at = _now_nst()

    #                 write_pipeline_run_log(
    #                     {
    #                         "status": "success",
    #                         "message": historical_news_log_message,
    #                         "error_text": None,
    #                         "news_total": int(summary.get("fetched", 0) or 0),
    #                         "news_inserted": int(summary.get("inserted", 0) or 0),
    #                         "nepse_records": 0,
    #                         "nepse_source": "historical_news",
    #                         "started_at": started_at,
    #                         "finished_at": finished_at,
    #                         "duration_ms": int((finished_at - started_at).total_seconds() * 1000),
    #                     },
    #                     config.database,
    #                 )
    #             else:
    #                 print("[Scheduler] Historical news backfill skipped: end_date is before start_date.")
    #     except Exception as e:
    #         print(f"[Scheduler] Historical backfill startup failed: {e}")
    #         try:
    #             config = load_app_config()
    #             now = _now_nst()
    #             write_pipeline_run_log(
    #                 {
    #                     "status": "failed",
    #                     "message": historical_news_log_message,
    #                     "error_text": str(e),
    #                     "news_total": 0,
    #                     "news_inserted": 0,
    #                     "nepse_records": 0,
    #                     "nepse_source": "historical_news",
    #                     "started_at": now,
    #                     "finished_at": now,
    #                     "duration_ms": 0,
    #                 },
    #                 config.database,
    #             )
    #         except Exception as log_err:
    #             print(f"[Scheduler] Failed to write historical news backfill log: {log_err}")

    scheduler.start()
