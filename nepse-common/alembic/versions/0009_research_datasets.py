"""research datasets: daily index/stock OHLCV, intraday ticks, security master,
backfill state; broker ids on floor sheet; VWAP/last-trade time on today-price

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-15

Adds the tables backing the thesis datasets (see CLAUDE.md "Research
datasets"): nepse_index_daily, nepse_stock_daily, nepse_intraday_tick,
nepse_security, research_backfill_state. Also adds columns NEPSE serves but
the scrapers previously dropped:
  - nepse_floorsheet: stock_id, trade_book_id, buyer/seller_member_id
    (broker ids, published by NEPSE only after the close).
  - nepse_today_price: average_traded_price, last_updated_time.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "nepse_index_daily",
        sa.Column("index_name", sa.Text(), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("open", sa.Double(), nullable=True),
        sa.Column("high", sa.Double(), nullable=True),
        sa.Column("low", sa.Double(), nullable=True),
        sa.Column("close", sa.Double(), nullable=True),
        sa.Column("volume", sa.Double(), nullable=True),
        sa.Column("turnover", sa.Double(), nullable=True),
        sa.Column("total_transactions", sa.Integer(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("idx_nepse_index_daily_trade_date", "nepse_index_daily", ["trade_date"])

    op.create_table(
        "nepse_stock_daily",
        sa.Column("symbol", sa.Text(), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("security_id", sa.Integer(), nullable=True),
        sa.Column("open", sa.Double(), nullable=True),
        sa.Column("high", sa.Double(), nullable=True),
        sa.Column("low", sa.Double(), nullable=True),
        sa.Column("close", sa.Double(), nullable=True),
        sa.Column("volume", sa.Double(), nullable=True),
        sa.Column("turnover", sa.Double(), nullable=True),
        sa.Column("total_trades", sa.Integer(), nullable=True),
        sa.Column("adj_open", sa.Double(), nullable=True),
        sa.Column("adj_high", sa.Double(), nullable=True),
        sa.Column("adj_low", sa.Double(), nullable=True),
        sa.Column("adj_close", sa.Double(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("idx_nepse_stock_daily_trade_date", "nepse_stock_daily", ["trade_date"])

    op.create_table(
        "nepse_intraday_tick",
        sa.Column("symbol", sa.Text(), primary_key=True),
        sa.Column("tick_time", sa.DateTime(), primary_key=True),
        sa.Column("instrument_type", sa.Text(), nullable=False),
        sa.Column("price", sa.Double(), nullable=False),
        sa.Column("volume", sa.Double(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
    )
    op.create_index("idx_nepse_intraday_tick_tick_time", "nepse_intraday_tick", ["tick_time"])

    op.create_table(
        "nepse_security",
        sa.Column("security_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("security_name", sa.Text(), nullable=True),
        sa.Column("company_name", sa.Text(), nullable=True),
        sa.Column("sector_name", sa.Text(), nullable=True),
        sa.Column("instrument_type", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("idx_nepse_security_symbol", "nepse_security", ["symbol"])

    op.create_table(
        "research_backfill_state",
        sa.Column("dataset", sa.Text(), primary_key=True),
        sa.Column("symbol", sa.Text(), primary_key=True),
        sa.Column("oldest_covered", sa.DateTime(), nullable=True),
        sa.Column("newest_covered", sa.DateTime(), nullable=True),
        sa.Column("exhausted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("rows_written", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )

    op.add_column("nepse_floorsheet", sa.Column("stock_id", sa.Integer(), nullable=True))
    op.add_column("nepse_floorsheet", sa.Column("trade_book_id", sa.BigInteger(), nullable=True))
    op.add_column("nepse_floorsheet", sa.Column("buyer_member_id", sa.Integer(), nullable=True))
    op.add_column("nepse_floorsheet", sa.Column("seller_member_id", sa.Integer(), nullable=True))

    op.add_column("nepse_today_price", sa.Column("average_traded_price", sa.Double(), nullable=True))
    op.add_column("nepse_today_price", sa.Column("last_updated_time", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("nepse_today_price", "last_updated_time")
    op.drop_column("nepse_today_price", "average_traded_price")

    op.drop_column("nepse_floorsheet", "seller_member_id")
    op.drop_column("nepse_floorsheet", "buyer_member_id")
    op.drop_column("nepse_floorsheet", "trade_book_id")
    op.drop_column("nepse_floorsheet", "stock_id")

    op.drop_table("research_backfill_state")
    op.drop_index("idx_nepse_security_symbol", table_name="nepse_security")
    op.drop_table("nepse_security")
    op.drop_index("idx_nepse_intraday_tick_tick_time", table_name="nepse_intraday_tick")
    op.drop_table("nepse_intraday_tick")
    op.drop_index("idx_nepse_stock_daily_trade_date", table_name="nepse_stock_daily")
    op.drop_table("nepse_stock_daily")
    op.drop_index("idx_nepse_index_daily_trade_date", table_name="nepse_index_daily")
    op.drop_table("nepse_index_daily")
