"""add historical news backfill tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-24

Adds the tables backing the historical news backfill worker (2021-01-01 to
2026-06-29, for portals with a discoverable archive):

  historical_backfill_urls     -- per-portal work queue of candidate article
                                   URLs discovered from sitemaps/cursors,
                                   fetched at 1 request/minute per portal.
  historical_backfill_progress -- per (source, date) completion log so a
                                   re-run never re-processes a finished day.
  historical_cursor_state      -- resume point (opaque cursor string) for
                                   cursor-paginated sources (sharesansar.com)
                                   that have no sitemap and can only be
                                   walked sequentially from newest to oldest.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "historical_backfill_urls",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("discovered_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("source", "url", name="uq_historical_backfill_urls_source_url"),
    )
    op.create_index(
        "idx_historical_backfill_urls_source_status",
        "historical_backfill_urls",
        ["source", "status"],
    )

    op.create_table(
        "historical_backfill_progress",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("articles_found", sa.Integer(), server_default="0"),
        sa.Column("articles_inserted", sa.Integer(), server_default="0"),
        sa.Column("completed_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.UniqueConstraint(
            "source", "target_date", name="uq_historical_backfill_progress_source_date"
        ),
    )

    op.create_table(
        "historical_cursor_state",
        sa.Column("source", sa.Text(), primary_key=True),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("exhausted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("historical_cursor_state")
    op.drop_table("historical_backfill_progress")
    op.drop_index("idx_historical_backfill_urls_source_status", table_name="historical_backfill_urls")
    op.drop_table("historical_backfill_urls")
