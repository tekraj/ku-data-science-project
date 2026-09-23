import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str


@dataclass(frozen=True)
class ScraperConfig:
    # NOTE: interval_minutes was split into news_interval_minutes and
    # nepse_interval_minutes when scraper-service was split into
    # news-service (20 news portals + news historical backfills) and
    # nepse-service (live NEPSE index + nepalstock.com.np market-data
    # scrapes). Both services import this same shared config loader --
    # the loader itself is NOT forked -- so each service just reads the
    # field it cares about.
    news_interval_minutes: int
    nepse_interval_minutes: int
    request_timeout: int
    max_articles_per_portal: int
    live_nepse_scrape_enabled: bool
    historical_daily_enabled: bool
    historical_start_date: str
    historical_daily_hour_npt: int
    historical_daily_minute_npt: int
    historical_request_timeout: int
    historical_max_records_per_portal_per_day: int
    historical_backfill_on_startup: bool
    historical_nepse_csv_import_on_startup: bool
    historical_nepse_csv_dir: str
    historical_news_backfill_enabled: bool
    nepse_news_fields_backfill_enabled: bool


@dataclass(frozen=True)
class AuthConfig:
    jwt_secret: str
    jwt_ttl_minutes: int
    cookie_secure: bool


@dataclass(frozen=True)
class AppConfig:
    database: DatabaseConfig
    scraper: ScraperConfig
    auth: AuthConfig


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _load_auth_config() -> AuthConfig:
    return AuthConfig(
        jwt_secret=os.getenv("JWT_SECRET", "dev-only-nepse-jwt-secret-change-me"),
        jwt_ttl_minutes=int(os.getenv("JWT_TTL_MINUTES", "480")),
        cookie_secure=_env_bool("COOKIE_SECURE", False),
    )


def load_app_config() -> AppConfig:
    return AppConfig(
        database=DatabaseConfig(
            host=os.getenv("POSTGRES_HOST", "db"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            dbname=os.getenv("POSTGRES_DB", "wikipedia"),
            user=os.getenv("POSTGRES_USER", "superset"),
            password=os.getenv("POSTGRES_PASSWORD", "superset_pass"),
        ),
        scraper=ScraperConfig(
            # News portal scraping cadence. Default lowered from 30 to 15
            # minutes per explicit ask -- 15 minutes also happens to divide
            # NPT's 5h45m UTC offset evenly, so it needs no NPT-alignment
            # offset in register_schedules.py (see _npt_aligned_offset there).
            news_interval_minutes=int(os.getenv("SCRAPER_INTERVAL_MINUTES", "15")),
            # NEPSE market-data scraping cadence (nepse-service): live index
            # plus the 4 nepalstock.com.np endpoints (today-price, floor
            # sheet, sector summary, market depth), all on a tight 1-minute
            # schedule since market data goes stale fast during trading hours.
            nepse_interval_minutes=int(os.getenv("NEPSE_SCRAPER_INTERVAL_MINUTES", "1")),
            request_timeout=int(os.getenv("SCRAPER_REQUEST_TIMEOUT", "15")),
            max_articles_per_portal=int(os.getenv("SCRAPER_MAX_ARTICLES_PER_PORTAL", "20")),
            live_nepse_scrape_enabled=_env_bool("LIVE_NEPSE_SCRAPE_ENABLED", False),
            historical_daily_enabled=_env_bool("HISTORICAL_DAILY_ENABLED", True),
            historical_start_date=os.getenv("HISTORICAL_START_DATE", "2020-01-01"),
            historical_daily_hour_npt=int(os.getenv("HISTORICAL_DAILY_HOUR_NPT", "2")),
            historical_daily_minute_npt=int(os.getenv("HISTORICAL_DAILY_MINUTE_NPT", "30")),
            historical_request_timeout=int(os.getenv("HISTORICAL_REQUEST_TIMEOUT", "20")),
            historical_max_records_per_portal_per_day=int(
                os.getenv("HISTORICAL_MAX_RECORDS_PER_PORTAL_PER_DAY", "50")
            ),
            historical_backfill_on_startup=_env_bool("HISTORICAL_BACKFILL_ON_STARTUP", True),
            historical_nepse_csv_import_on_startup=_env_bool(
                "HISTORICAL_NEPSE_CSV_IMPORT_ON_STARTUP", True
            ),
            historical_nepse_csv_dir=os.getenv(
                "HISTORICAL_NEPSE_CSV_DIR", "/app/historical-data"
            ),
            historical_news_backfill_enabled=_env_bool(
                "HISTORICAL_NEWS_BACKFILL_ENABLED", False
            ),
            nepse_news_fields_backfill_enabled=_env_bool(
                "NEPSE_NEWS_FIELDS_BACKFILL_ENABLED", False
            ),
        ),
        auth=_load_auth_config(),
    )
