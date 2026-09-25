"""Preserve gross purchases for daily return denominators."""
from alembic import op
import sqlalchemy as sa


revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('position_snapshots', sa.Column('purchases', sa.Numeric(38, 12), nullable=True))
    # Net flow cannot recover gross purchases; rebuild derived returns from source.
    op.execute("""
        UPDATE portfolios SET dirty_from = CASE
            WHEN dirty_from IS NULL THEN first_trade.day
            ELSE LEAST(dirty_from, first_trade.day) END
        FROM (SELECT portfolio_id, MIN(trade_date) AS day
              FROM transactions GROUP BY portfolio_id) AS first_trade
        WHERE portfolios.id = first_trade.portfolio_id
    """)


def downgrade():
    op.drop_column('position_snapshots', 'purchases')
