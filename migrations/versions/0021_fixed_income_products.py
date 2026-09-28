"""Canonical fixed-income product templates and portfolio-owned custom identities."""
from alembic import op
import sqlalchemy as sa


revision = '0021'
down_revision = '0020'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('instruments') as batch:
        batch.add_column(sa.Column('portfolio_id', sa.Integer(),
                                   sa.ForeignKey('portfolios.id', ondelete='RESTRICT',
                                                 name='fk_instruments_portfolio_id'), nullable=True))
    op.create_index('ix_instruments_portfolio_id', 'instruments', ['portfolio_id'])
    # Adopt legacy custom identities only when their existing assets have one owner.
    op.execute("""
        UPDATE instruments SET portfolio_id = (
            SELECT MIN(assets.portfolio_id) FROM assets
            WHERE assets.instrument_id = instruments.id
        )
        WHERE asset_type = 'FIXED_INCOME' AND origin = 'CUSTOM'
          AND (SELECT COUNT(DISTINCT assets.portfolio_id) FROM assets
               WHERE assets.instrument_id = instruments.id) = 1
    """)
    op.create_table(
        'fixed_income_products',
        sa.Column('instrument_id', sa.Integer(), sa.ForeignKey('instruments.id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('default_currency', sa.String(3), nullable=False),
        sa.Column('day_count_basis', sa.String(20), nullable=False),
        sa.Column('compounding', sa.String(20), nullable=False),
        sa.Column('business_day_calendar', sa.String(40), nullable=False),
        sa.Column('benchmark_lag_months', sa.Integer(), nullable=False),
        sa.CheckConstraint('benchmark_lag_months BETWEEN 0 AND 24', name='ck_fixed_income_products_valid_lag'),
    )


def downgrade():
    op.drop_table('fixed_income_products')
    op.drop_index('ix_instruments_portfolio_id', table_name='instruments')
    with op.batch_alter_table('instruments') as batch:
        batch.drop_column('portfolio_id')
