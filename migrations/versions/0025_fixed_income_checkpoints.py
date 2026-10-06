"""Persist canonical lot checkpoints and lot-specific invalidation boundaries."""
from alembic import op
import sqlalchemy as sa

revision = '0025'
down_revision = '0024'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('fixed_income_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('portfolio_id', sa.Integer(), sa.ForeignKey('portfolios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('instrument_id', sa.Integer(), sa.ForeignKey('instruments.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('lot_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('accounting_currency', sa.String(3), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('valuation', sa.JSON(), nullable=False),
        sa.Column('ledger_state', sa.JSON(), nullable=True),
        sa.Column('lot_metadata', sa.JSON(), nullable=False),
        sa.Column('net_flow', sa.Numeric(38, 12), nullable=False),
        sa.Column('purchases', sa.Numeric(38, 12), nullable=False),
        sa.UniqueConstraint('portfolio_id', 'lot_id', 'date'))
    op.create_index('ix_fixed_income_snapshots_lot_id', 'fixed_income_snapshots', ['lot_id'])
    op.create_table('fixed_income_invalidations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('portfolio_id', sa.Integer(), sa.ForeignKey('portfolios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('instrument_id', sa.Integer(), sa.ForeignKey('instruments.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('lot_id', sa.Integer(), nullable=False),
        sa.Column('dirty_from', sa.Date(), nullable=False),
        sa.UniqueConstraint('portfolio_id', 'lot_id'))
    op.create_index('ix_fixed_income_invalidations_lot_id', 'fixed_income_invalidations', ['lot_id'])
    op.execute('''
        INSERT INTO fixed_income_invalidations (portfolio_id, instrument_id, lot_id, dirty_from)
        SELECT a.portfolio_id, a.instrument_id, l.id, l.start_date
        FROM fixed_income_lots l JOIN assets a ON a.id = l.asset_id
    ''')
    op.execute('''
        INSERT INTO position_invalidations (portfolio_id, instrument_id, dirty_from, reason)
        SELECT portfolio_id, instrument_id, MIN(dirty_from), 'fixed_income'
        FROM fixed_income_invalidations GROUP BY portfolio_id, instrument_id
        ON CONFLICT (portfolio_id, instrument_id) DO UPDATE
        SET dirty_from = LEAST(position_invalidations.dirty_from, EXCLUDED.dirty_from)
    ''')
    op.execute('''
        UPDATE portfolios SET dirty_from = (
            SELECT MIN(i.dirty_from) FROM position_invalidations i
            WHERE i.portfolio_id = portfolios.id)
    ''')


def downgrade():
    op.drop_table('fixed_income_invalidations')
    op.drop_table('fixed_income_snapshots')
