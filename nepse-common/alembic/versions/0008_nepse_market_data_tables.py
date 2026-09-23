"""add nepse market-data tables (today-price, floorsheet, sector summary, market depth)

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-14

Adds the 4 tables backing nepse-service's new 1-minute scrapes of the
official nepalstock.com.np JSON API (today's price for all securities,
floor sheet, sector summary, per-security market depth), added when
scraper-service was split into news-service (news only) and nepse-service
(all NEPSE market data). See nepse-service/scraper/nepse_wasm_auth.py and
nepse-service/scraper/nepse_market_data.py for the scraping/auth mechanism,
and nepse-common/nepse_common/models/nepse_{today_price,floorsheet,
sector_summary,market_depth}.py for the corresponding ORM models.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "nepse_today_price",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("security_id", sa.Integer(), nullable=True),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("security_name", sa.Text(), nullable=True),
        sa.Column("open_price", sa.Double(), nullable=True),
        sa.Column("high_price", sa.Double(), nullable=True),
        sa.Column("low_price", sa.Double(), nullable=True),
        sa.Column("close_price", sa.Double(), nullable=True),
        sa.Column("previous_close", sa.Double(), nullable=True),
        sa.Column("ltp", sa.Double(), nullable=True),
        sa.Column("percent_change", sa.Double(), nullable=True),
        sa.Column("total_trade_quantity", sa.BigInteger(), nullable=True),
        sa.Column("total_trade_value", sa.Double(), nullable=True),
        sa.Column("total_trades", sa.Integer(), nullable=True),
        sa.Column("business_date", sa.Text(), nullable=True),
        sa.Column("scraped_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("idx_nepse_today_price_scraped_at", "nepse_today_price", ["scraped_at"])
    op.create_index("idx_nepse_today_price_symbol", "nepse_today_price", ["symbol"])

    op.create_table(
        "nepse_floorsheet",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("contract_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("buyer_broker_name", sa.Text(), nullable=True),
        sa.Column("seller_broker_name", sa.Text(), nullable=True),
        sa.Column("contract_quantity", sa.BigInteger(), nullable=True),
        sa.Column("contract_rate", sa.Double(), nullable=True),
        sa.Column("contract_amount", sa.Double(), nullable=True),
        sa.Column("business_date", sa.Text(), nullable=True),
        sa.Column("trade_time", sa.Text(), nullable=True),
        sa.Column("scraped_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.UniqueConstraint("contract_id", "business_date", name="uq_nepse_floorsheet_contract"),
    )
    op.create_index("idx_nepse_floorsheet_scraped_at", "nepse_floorsheet", ["scraped_at"])
    op.create_index("idx_nepse_floorsheet_symbol", "nepse_floorsheet", ["symbol"])

    op.create_table(
        "nepse_sector_summary",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sector_name", sa.Text(), nullable=False),
        sa.Column("total_turnover", sa.Double(), nullable=True),
        sa.Column("total_trade_quantity", sa.BigInteger(), nullable=True),
        sa.Column("total_transactions", sa.Integer(), nullable=True),
        sa.Column("total_scrips_traded", sa.Integer(), nullable=True),
        sa.Column("business_date", sa.Text(), nullable=True),
        sa.Column("scraped_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("idx_nepse_sector_summary_scraped_at", "nepse_sector_summary", ["scraped_at"])
    op.create_index("idx_nepse_sector_summary_name", "nepse_sector_summary", ["sector_name"])

    op.create_table(
        "nepse_market_depth",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("security_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("total_buy_qty", sa.Integer(), nullable=True),
        sa.Column("total_sell_qty", sa.Integer(), nullable=True),
        sa.Column("buy_levels", postgresql.JSONB(), nullable=True),
        sa.Column("sell_levels", postgresql.JSONB(), nullable=True),
        sa.Column("scraped_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("idx_nepse_market_depth_scraped_at", "nepse_market_depth", ["scraped_at"])
    op.create_index("idx_nepse_market_depth_symbol", "nepse_market_depth", ["symbol"])


def downgrade() -> None:
    op.drop_table("nepse_market_depth")
    op.drop_table("nepse_sector_summary")
    op.drop_table("nepse_floorsheet")
    op.drop_table("nepse_today_price")
