"""add claimed_at to historical_backfill_urls

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-26

Adds historical_backfill_urls.claimed_at, stamped when a ticker claims a
row (sets status to "processing"). Needed to detect and recover stale
claims: a row can get stuck in "processing" forever if the worker process
that claimed it is killed/restarted before finishing (observed directly in
production -- container restarts during deploys left dozens of rows
permanently stuck). A periodic reap step (see
reap_stale_processing_urls_activity) resets any "processing" row whose
claimed_at is older than a timeout back to "pending" so it gets retried.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "historical_backfill_urls",
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("historical_backfill_urls", "claimed_at")
