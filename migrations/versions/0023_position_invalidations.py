"""Track pending canonical position changes by instrument."""
from alembic import op
import sqlalchemy as sa


revision = '0023'
down_revision = '0022'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'position_invalidations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('portfolio_id', sa.Integer(), sa.ForeignKey('portfolios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('instrument_id', sa.Integer(), sa.ForeignKey('instruments.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('dirty_from', sa.Date(), nullable=False),
        sa.Column('reason', sa.String(32), nullable=False),
        sa.UniqueConstraint('portfolio_id', 'instrument_id'),
    )
    # Existing snapshots were built in the portfolio display currency. None
    # can safely serve as an accounting-currency ledger checkpoint.
    op.execute('DELETE FROM position_snapshots')
    op.execute('DELETE FROM portfolio_snapshots')
    op.execute("""
        INSERT INTO position_invalidations (portfolio_id, instrument_id, dirty_from, reason)
        SELECT portfolio_id, instrument_id, MIN(affected_date), 'migration'
        FROM (
            SELECT t.portfolio_id, t.instrument_id, MIN(t.trade_date) AS affected_date
            FROM transactions t JOIN portfolios p ON p.id = t.portfolio_id
            GROUP BY t.portfolio_id, t.instrument_id, p.dirty_from
            UNION ALL
            SELECT a.portfolio_id, a.instrument_id, MIN(l.start_date) AS affected_date
            FROM fixed_income_lots l JOIN assets a ON a.id = l.asset_id
            JOIN portfolios p ON p.id = a.portfolio_id
            GROUP BY a.portfolio_id, a.instrument_id, p.dirty_from
        ) affected
        GROUP BY portfolio_id, instrument_id
    """)
    op.execute("""
        UPDATE portfolios p SET dirty_from = affected.affected_date,
                                history_built_through = NULL
        FROM (SELECT portfolio_id, MIN(dirty_from) AS affected_date FROM position_invalidations
              GROUP BY portfolio_id) affected
        WHERE p.id = affected.portfolio_id
    """)
    op.execute('UPDATE portfolios SET history_built_through = NULL')


def downgrade():
    op.drop_table('position_invalidations')
