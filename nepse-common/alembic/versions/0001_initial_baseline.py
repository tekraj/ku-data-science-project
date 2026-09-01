"""initial baseline

Revision ID: 0001
Revises:
Create Date: 2026-08-21

This migration mirrors the exact CREATE TABLE / CREATE INDEX statements from the
old monolith's db/connection.py (_CREATE_TABLES_SQL), reproduced here verbatim
for future auditing:

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

Note: the old monolith's idx_pipeline_run_logs_started_at index sorts DESC;
Postgres B-tree indexes are traversable in either direction, and DESC there is a
query-time concern only, so this migration creates a plain (ASC) index of the
same name, matching the build instructions.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "nepse_news",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("portal_tier", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False, unique=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("scraped_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("idx_nepse_news_scraped_at", "nepse_news", ["scraped_at"])
    op.create_index("idx_nepse_news_source", "nepse_news", ["source"])
    op.create_index("idx_nepse_news_tier", "nepse_news", ["portal_tier"])

    op.create_table(
        "nepse_index",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("index_name", sa.Text(), nullable=False),
        sa.Column("value", sa.Double(), nullable=True),
        sa.Column("change", sa.Double(), nullable=True),
        sa.Column("percent_change", sa.Double(), nullable=True),
        sa.Column("scraped_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("idx_nepse_index_scraped_at", "nepse_index", ["scraped_at"])
    op.create_index("idx_nepse_index_name", "nepse_index", ["index_name"])

    op.create_table(
        "pipeline_run_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("news_total", sa.Integer(), server_default="0", nullable=True),
        sa.Column("news_inserted", sa.Integer(), server_default="0", nullable=True),
        sa.Column("nepse_records", sa.Integer(), server_default="0", nullable=True),
        sa.Column("nepse_source", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("idx_pipeline_run_logs_started_at", "pipeline_run_logs", ["started_at"])
    op.create_index("idx_pipeline_run_logs_status", "pipeline_run_logs", ["status"])


def downgrade() -> None:
    op.drop_index("idx_pipeline_run_logs_status", table_name="pipeline_run_logs")
    op.drop_index("idx_pipeline_run_logs_started_at", table_name="pipeline_run_logs")
    op.drop_table("pipeline_run_logs")

    op.drop_index("idx_nepse_index_name", table_name="nepse_index")
    op.drop_index("idx_nepse_index_scraped_at", table_name="nepse_index")
    op.drop_table("nepse_index")

    op.drop_index("idx_nepse_news_tier", table_name="nepse_news")
    op.drop_index("idx_nepse_news_source", table_name="nepse_news")
    op.drop_index("idx_nepse_news_scraped_at", table_name="nepse_news")
    op.drop_table("nepse_news")
