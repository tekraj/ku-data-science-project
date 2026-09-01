"""add historical_idwalk_cursor table

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-31

Adds historical_idwalk_cursor: resume point for sequential-numeric-ID
historical backfill sources (setopati, merolagani, onlinekhabar) -- portals
confirmed, via a dedicated overnight research pass targeting calendar year
2014, to have no sitemap and no working date-archive listing that reaches
old content, only a guessable numeric ID embedded in each article's URL.
See scraper/historical_idwalk_discovery.py for the full per-portal
calibration and discovery-mechanism notes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "historical_idwalk_cursor",
        sa.Column("source", sa.Text(), primary_key=True),
        sa.Column("next_id", sa.Integer(), nullable=False),
        sa.Column("exhausted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("historical_idwalk_cursor")
