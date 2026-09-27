"""Incremental, reproducible daily reporting history."""
from alembic import op
import sqlalchemy as sa


revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('portfolios', sa.Column('dirty_from', sa.Date(), nullable=True))
    op.add_column('portfolios', sa.Column('history_built_through', sa.Date(), nullable=True))
    op.create_table(
        'position_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('portfolio_id', sa.Integer(), sa.ForeignKey('portfolios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('instrument_id', sa.Integer(), sa.ForeignKey('instruments.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('reporting_currency', sa.String(3), nullable=False),
        sa.Column('quantity', sa.Numeric(38, 12), nullable=False),
        *[sa.Column(name, sa.Numeric(38, 12), nullable=True) for name in (
            'remaining_acquisition_cost', 'average_cost', 'market_value', 'realized_gain',
            'unrealized_gain', 'gross_income', 'total_gain', 'net_flow', 'daily_income')],
        sa.Column('daily_return_pct', sa.Numeric(38, 18), nullable=True),
        sa.Column('cumulative_return_pct', sa.Numeric(38, 18), nullable=True),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('ledger_state', sa.JSON(), nullable=False),
        sa.UniqueConstraint('portfolio_id', 'instrument_id', 'date', name='uq_position_snapshots_portfolio_id'),
    )
    op.create_table(
        'portfolio_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('portfolio_id', sa.Integer(), sa.ForeignKey('portfolios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('reporting_currency', sa.String(3), nullable=False),
        *[sa.Column(name, sa.Numeric(38, 12), nullable=True) for name in (
            'remaining_acquisition_cost', 'market_value', 'realized_gain',
            'unrealized_gain', 'gross_income', 'total_gain')],
        sa.Column('daily_return_pct', sa.Numeric(38, 18), nullable=True),
        sa.Column('cumulative_return_pct', sa.Numeric(38, 18), nullable=True),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('return_factor', sa.Numeric(38, 18), nullable=True),
        sa.UniqueConstraint('portfolio_id', 'date', name='uq_portfolio_snapshots_portfolio_id'),
    )


def downgrade():
    op.drop_table('portfolio_snapshots')
    op.drop_table('position_snapshots')
    op.drop_column('portfolios', 'history_built_through')
    op.drop_column('portfolios', 'dirty_from')
