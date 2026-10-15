"""index nepse_floorsheet.business_date

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-15

Per-session lookups (post-close sweep and merolagani history backfill
completeness checks, broker-name lookups, research queries by day) filter
on business_date alone, which the (contract_id, business_date) unique
constraint can't serve. Needed before the floor-sheet history backfill
grows the table to ~100M rows (sessions back to 2020).
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("idx_nepse_floorsheet_business_date", "nepse_floorsheet", ["business_date"])


def downgrade() -> None:
    op.drop_index("idx_nepse_floorsheet_business_date", table_name="nepse_floorsheet")
