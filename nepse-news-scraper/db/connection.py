import time
import psycopg2
from psycopg2 import sql
from config import DatabaseConfig

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS nepse_news (
    id              SERIAL PRIMARY KEY,
    source          TEXT NOT NULL,
    portal_tier     TEXT NOT NULL,
    url             TEXT UNIQUE NOT NULL,
    title           TEXT,
    body            TEXT,
    category        TEXT,
    published_at    TIMESTAMP,
    scraped_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nepse_news_scraped_at ON nepse_news (scraped_at);
CREATE INDEX IF NOT EXISTS idx_nepse_news_source     ON nepse_news (source);
CREATE INDEX IF NOT EXISTS idx_nepse_news_tier       ON nepse_news (portal_tier);

CREATE TABLE IF NOT EXISTS nepse_index (
    id              SERIAL PRIMARY KEY,
    index_name      TEXT NOT NULL,
    value           DOUBLE PRECISION,
    change          DOUBLE PRECISION,
    percent_change  DOUBLE PRECISION,
    scraped_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nepse_index_scraped_at  ON nepse_index (scraped_at);
CREATE INDEX IF NOT EXISTS idx_nepse_index_name        ON nepse_index (index_name);

CREATE TABLE IF NOT EXISTS pipeline_run_logs (
    id                  SERIAL PRIMARY KEY,
    status              TEXT NOT NULL,
    message             TEXT,
    error_text          TEXT,
    news_total          INTEGER DEFAULT 0,
    news_inserted       INTEGER DEFAULT 0,
    nepse_records       INTEGER DEFAULT 0,
    nepse_source        TEXT,
    started_at          TIMESTAMP,
    finished_at         TIMESTAMP,
    duration_ms         INTEGER,
    created_at          TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pipeline_run_logs_started_at ON pipeline_run_logs (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_pipeline_run_logs_status ON pipeline_run_logs (status);
"""


def get_connection(db_config: DatabaseConfig) -> psycopg2.extensions.connection:
    return psycopg2.connect(
        host=db_config.host,
        port=db_config.port,
        dbname=db_config.dbname,
        user=db_config.user,
        password=db_config.password,
    )


def _maintenance_connection(db_config: DatabaseConfig) -> psycopg2.extensions.connection:
    # Connect to a maintenance DB to manage/create the target application DB.
    return psycopg2.connect(
        host=db_config.host,
        port=db_config.port,
        dbname="postgres",
        user=db_config.user,
        password=db_config.password,
    )


def ensure_database_exists(db_config: DatabaseConfig) -> None:
    conn = _maintenance_connection(db_config)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_config.dbname,))
            exists = cur.fetchone() is not None
            if not exists:
                cur.execute(sql.SQL("CREATE DATABASE {};").format(sql.Identifier(db_config.dbname)))
                print(f"[DB] Database created: {db_config.dbname}")
    finally:
        conn.close()


def ensure_table_exists(db_config: DatabaseConfig, max_retries: int = 12, retry_delay: int = 5) -> None:
    for attempt in range(1, max_retries + 1):
        try:
            ensure_database_exists(db_config)
            conn = get_connection(db_config)
            with conn:
                with conn.cursor() as cur:
                    cur.execute(_CREATE_TABLES_SQL)
            conn.close()
            print("[DB] Tables ready: nepse_news, nepse_index, pipeline_run_logs.")
            return
        except Exception as e:
            if attempt == max_retries:
                raise
            print(f"[DB] Connection attempt {attempt}/{max_retries} failed: {e}. Retrying in {retry_delay}s...")
            time.sleep(retry_delay)
