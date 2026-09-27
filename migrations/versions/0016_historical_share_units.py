"""Re-fetch ambiguous Yahoo caches in historical share units; audit carried prices."""
from alembic import op
import sqlalchemy as sa

revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('position_snapshots', sa.Column('quote_date', sa.Date(), nullable=True))
    # These provider caches cannot be safely repaired from partial split history.
    # Private prices/events and transactions are retained unchanged.
    for table in ('market_prices', 'market_price_coverage',
                  'corporate_actions', 'corporate_action_coverage'):
        op.execute(sa.text(f"DELETE FROM {table} WHERE source = 'yfinance'"))
    op.execute("""
        UPDATE portfolios SET dirty_from = first_trade.day, history_built_through = NULL
        FROM (SELECT portfolio_id, MIN(trade_date) AS day
              FROM transactions GROUP BY portfolio_id) AS first_trade
        WHERE portfolios.id = first_trade.portfolio_id
    """)


def downgrade():
    op.drop_column('position_snapshots', 'quote_date')
