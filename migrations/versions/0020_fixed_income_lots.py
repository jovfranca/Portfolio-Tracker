"""Contractual fixed-income lots and monetary movement ledger."""
from alembic import op
import sqlalchemy as sa


revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'fixed_income_lots',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('asset_id', sa.Integer(), sa.ForeignKey('assets.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('product_type', sa.String(40), nullable=False),
        sa.Column('issuer', sa.String(200), nullable=False),
        sa.Column('broker_id', sa.Integer(), sa.ForeignKey('brokers.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('maturity_date', sa.Date()),
        sa.Column('yield_structure', sa.String(32), nullable=False),
        sa.Column('fixed_rate', sa.Numeric(28, 12)),
        sa.Column('benchmark_id', sa.Integer(), sa.ForeignKey('benchmarks.id', ondelete='RESTRICT')),
        sa.Column('benchmark_multiplier', sa.Numeric(28, 12)),
        sa.Column('benchmark_spread', sa.Numeric(28, 12)),
        sa.Column('day_count_basis', sa.String(20), nullable=False),
        sa.Column('compounding', sa.String(20), nullable=False),
        sa.Column('business_day_calendar', sa.String(40), nullable=False),
        sa.Column('benchmark_lag_months', sa.Integer(), nullable=False),
        sa.Column('notes', sa.String(5000), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.CheckConstraint('maturity_date IS NULL OR maturity_date >= start_date', name='ck_fixed_income_lots_valid_dates'),
        sa.CheckConstraint("yield_structure IN ('FIXED_RATE', 'BENCHMARK_MULTIPLE', 'BENCHMARK_SPREAD')",
                           name='ck_fixed_income_lots_yield_structure'),
        sa.CheckConstraint('benchmark_multiplier IS NULL OR benchmark_multiplier >= 0',
                           name='ck_fixed_income_lots_nonnegative_multiplier'),
        sa.CheckConstraint('benchmark_lag_months BETWEEN 0 AND 24', name='ck_fixed_income_lots_valid_benchmark_lag'),
        sa.CheckConstraint("yield_structure <> 'FIXED_RATE' OR "
                           '(fixed_rate IS NOT NULL AND benchmark_id IS NULL AND benchmark_multiplier IS NULL AND benchmark_spread IS NULL)',
                           name='ck_fixed_income_lots_fixed_terms'),
        sa.CheckConstraint("yield_structure <> 'BENCHMARK_MULTIPLE' OR "
                           '(fixed_rate IS NULL AND benchmark_id IS NOT NULL AND benchmark_multiplier IS NOT NULL AND benchmark_spread IS NULL)',
                           name='ck_fixed_income_lots_multiple_terms'),
        sa.CheckConstraint("yield_structure <> 'BENCHMARK_SPREAD' OR "
                           '(fixed_rate IS NULL AND benchmark_id IS NOT NULL AND benchmark_multiplier IS NULL AND benchmark_spread IS NOT NULL)',
                           name='ck_fixed_income_lots_spread_terms'),
    )
    op.create_index('ix_fixed_income_lots_asset', 'fixed_income_lots', ['asset_id'])
    op.create_table(
        'fixed_income_movements',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('lot_id', sa.Integer(), sa.ForeignKey('fixed_income_lots.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('movement_type', sa.String(40), nullable=False),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('amount', sa.Numeric(28, 12), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('notes', sa.String(5000), nullable=False),
        sa.CheckConstraint('amount > 0', name='ck_fixed_income_movements_positive_amount'),
    )
    op.create_index('ix_fixed_income_movements_lot_date', 'fixed_income_movements', ['lot_id', 'effective_date'])


def downgrade():
    op.drop_index('ix_fixed_income_movements_lot_date', table_name='fixed_income_movements')
    op.drop_table('fixed_income_movements')
    op.drop_index('ix_fixed_income_lots_asset', table_name='fixed_income_lots')
    op.drop_table('fixed_income_lots')
