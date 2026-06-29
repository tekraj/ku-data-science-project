from __future__ import annotations
from typing import Any
from psycopg2.extras import execute_values
from db.connection import get_connection
from config import DatabaseConfig

_INSERT_NEWS_SQL = """
INSERT INTO nepse_news (source, portal_tier, url, title, body, category, published_at)
VALUES %s
ON CONFLICT (url) DO NOTHING
"""

_INSERT_INDEX_SQL = """
INSERT INTO nepse_index (index_name, value, change, percent_change)
VALUES %s
"""

_INSERT_INDEX_HISTORY_SQL = """
INSERT INTO nepse_index (index_name, value, change, percent_change, scraped_at)
SELECT v.index_name, v.value, v.change, v.percent_change, v.scraped_at
FROM (VALUES %s) AS v(index_name, value, change, percent_change, scraped_at)
WHERE NOT EXISTS (
        SELECT 1
        FROM nepse_index n
        WHERE n.index_name = v.index_name
            AND n.scraped_at = v.scraped_at
)
"""

_INSERT_PIPELINE_LOG_SQL = """
INSERT INTO pipeline_run_logs (
    status,
    message,
    error_text,
    news_total,
    news_inserted,
    nepse_records,
    nepse_source,
    started_at,
    finished_at,
    duration_ms
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def write_articles(articles: list[dict[str, Any]], db_config: DatabaseConfig) -> int:
    """Save scraped news articles to DB. Skips duplicates by URL."""
    if not articles:
        return 0

    records = [
        (
            a["source"],
            a.get("portal_tier", "general"),
            a["url"],
            a.get("title"),
            a.get("body"),
            a.get("category"),
            a.get("published_at"),
        )
        for a in articles
    ]

    conn = get_connection(db_config)
    try:
        with conn:
            with conn.cursor() as cur:
                execute_values(cur, _INSERT_NEWS_SQL, records)
                inserted = cur.rowcount
        print(f"[DB] Inserted {inserted} new articles.")
        return inserted
    finally:
        conn.close()


def write_nepse_index(index_data: dict[str, Any], db_config: DatabaseConfig) -> int:
    """Save NEPSE main index + sector indices to DB."""
    records = []

    # Main NEPSE index
    main = index_data.get("nepse_index")
    if main and main.get("value"):
        records.append((
            main.get("index", "NEPSE"),
            main.get("value"),
            main.get("change"),
            main.get("percent_change"),
        ))

    # Sector indices
    for sector in index_data.get("sector_indices", []):
        if sector.get("value"):
            records.append((
                sector.get("index"),
                sector.get("value"),
                sector.get("change"),
                sector.get("percent_change"),
            ))

    if not records:
        print("[DB] No NEPSE index data to save.")
        return 0

    conn = get_connection(db_config)
    try:
        with conn:
            with conn.cursor() as cur:
                execute_values(cur, _INSERT_INDEX_SQL, records)
        print(f"[DB] Saved {len(records)} NEPSE index records.")
        return len(records)
    finally:
        conn.close()


def write_pipeline_run_log(log_data: dict[str, Any], db_config: DatabaseConfig) -> None:
    conn = get_connection(db_config)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    _INSERT_PIPELINE_LOG_SQL,
                    (
                        log_data.get("status", "failed"),
                        log_data.get("message"),
                        log_data.get("error_text"),
                        int(log_data.get("news_total", 0) or 0),
                        int(log_data.get("news_inserted", 0) or 0),
                        int(log_data.get("nepse_records", 0) or 0),
                        log_data.get("nepse_source"),
                        log_data.get("started_at"),
                        log_data.get("finished_at"),
                        int(log_data.get("duration_ms", 0) or 0),
                    ),
                )
        print("[DB] Saved pipeline run log.")
    finally:
        conn.close()


def has_successful_pipeline_message(message: str, db_config: DatabaseConfig) -> bool:
    """Return True when pipeline_run_logs contains a successful row for message."""
    conn = get_connection(db_config)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM pipeline_run_logs
                WHERE status = 'success'
                  AND message = %s
                LIMIT 1
                """,
                (message,),
            )
            return cur.fetchone() is not None
    finally:
        conn.close()


def write_nepse_index_history(rows: list[dict[str, Any]], db_config: DatabaseConfig) -> int:
    """Insert historical NEPSE index rows, de-duplicated by (index_name, scraped_at)."""
    if not rows:
        return 0

    records = [
        (
            row.get("index_name"),
            row.get("value"),
            row.get("change"),
            row.get("percent_change"),
            row.get("scraped_at"),
        )
        for row in rows
        if row.get("index_name") and row.get("scraped_at")
    ]

    if not records:
        return 0

    conn = get_connection(db_config)
    try:
        with conn:
            with conn.cursor() as cur:
                execute_values(cur, _INSERT_INDEX_HISTORY_SQL, records)
                inserted = cur.rowcount
        print(f"[DB] Inserted {inserted} historical NEPSE rows.")
        return inserted
    finally:
        conn.close()
