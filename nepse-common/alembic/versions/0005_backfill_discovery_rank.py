"""add discovery_rank to historical_backfill_urls

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-26

Adds historical_backfill_urls.discovery_rank: a coarse "likely age" signal
captured at discovery time so the per-portal ticker can claim
probably-older URLs first instead of processing strictly in discovery
order. Populated from the sub-sitemap index for portals where that's a
reliable age proxy (karobardaily's post-sitemapN.xml -- N=1 newest, higher
N older); left at its default 0 for portals with no such reliable signal
(myrepublica).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "historical_backfill_urls",
        sa.Column("discovery_rank", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "idx_historical_backfill_urls_source_status_rank",
        "historical_backfill_urls",
        ["source", "status", "discovery_rank"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_historical_backfill_urls_source_status_rank",
        table_name="historical_backfill_urls",
    )
    op.drop_column("historical_backfill_urls", "discovery_rank")
