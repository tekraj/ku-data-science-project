"""add fields_backfill_attempts to nepse_news

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-28

Adds nepse_news.fields_backfill_attempts, incremented by
NepseNewsFieldsBackfillTickWorkflow on every claim that does not result in
a real update. Fixes a confirmed head-of-line-blocking bug: a row whose
content is genuinely unfixable (e.g. a nepalipaisa article that's only a
video embed, no text) was always re-claimed first (lowest id wins ties in
the claim query), permanently blocking every other row behind it in the
queue -- ~10,900 rows made zero progress because of a single stuck row.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "nepse_news",
        sa.Column("fields_backfill_attempts", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("nepse_news", "fields_backfill_attempts")
