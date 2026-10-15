"""research_index_drawdown view: daily log returns, running peak and drawdown
per index (crash ground truth for detector training/backtesting)

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-15

A plain view over nepse_index_daily, so it is always current. Crash
episodes are derived from it by `python manage_data.py crash-events`
(nepse-service); the threshold that turns a drawdown into a "crash" is a
modelling choice and is deliberately not baked in here.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE VIEW research_index_drawdown AS
        SELECT
            index_name,
            trade_date,
            close,
            ln(close / lag(close) OVER w) AS log_return,
            max(close) OVER w AS running_peak,
            close / max(close) OVER w - 1 AS drawdown
        FROM nepse_index_daily
        WHERE close > 0
        WINDOW w AS (PARTITION BY index_name ORDER BY trade_date)
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS research_index_drawdown")
