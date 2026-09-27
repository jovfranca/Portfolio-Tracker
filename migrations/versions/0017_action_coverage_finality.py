"""Separate provisional current action checks from finalized history coverage."""
from alembic import op
import sqlalchemy as sa

revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('corporate_action_coverage', sa.Column(
        'is_final', sa.Boolean(), nullable=False, server_default=sa.true()))
    # Existing coverage was restricted to completed days. Rebuild derived views
    # so previously ignored coverage gaps cannot remain certified as complete.
    op.execute("""
        UPDATE portfolios SET dirty_from = first_trade.day
        FROM (SELECT portfolio_id, MIN(trade_date) AS day
              FROM transactions GROUP BY portfolio_id) AS first_trade
        WHERE portfolios.id = first_trade.portfolio_id
    """)


def downgrade():
    op.drop_column('corporate_action_coverage', 'is_final')
