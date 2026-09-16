"""Add transaction dates, currency, stored FX and import batches."""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    for column in [
        sa.Column('trade_date', sa.Date(), nullable=True),
        sa.Column('settlement_date', sa.Date(), nullable=True),
        sa.Column('asset_currency', sa.String(3), nullable=True),
        sa.Column('fx_rate', sa.Numeric(28, 12), nullable=True),
    ]:
        op.add_column('transactions', column)
    op.execute(
        "UPDATE transactions SET trade_date = CAST(date_time AS date), "
        "settlement_date = CAST(date_time AS date), asset_currency = 'BRL', fx_rate = 1"
    )
    for name in ['trade_date', 'settlement_date', 'asset_currency', 'fx_rate']:
        op.alter_column('transactions', name, nullable=False)
    for name in ['quantity', 'price', 'brokerage_fee', 'other_fees']:
        op.alter_column(
            'transactions', name, type_=sa.Numeric(28, 12),
            postgresql_using=f'{name}::numeric(28, 12)', existing_nullable=False,
        )
    op.create_check_constraint(
        'ck_transactions_currency', 'transactions',
        "asset_currency ~ '^[A-Z]{3}$' AND fx_rate > 0",
    )
    op.create_check_constraint(
        'ck_transactions_dates', 'transactions', 'settlement_date >= trade_date',
    )
    op.create_table(
        'transaction_imports',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('portfolio_id', sa.Integer(), sa.ForeignKey('portfolios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('digest', sa.String(64), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('records', sa.Integer(), nullable=False),
        sa.Column('imported_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('portfolio_id', 'digest'),
    )


def downgrade():
    op.drop_table('transaction_imports')
    op.drop_constraint('ck_transactions_dates', 'transactions', type_='check')
    op.drop_constraint('ck_transactions_currency', 'transactions', type_='check')
    for name in ['quantity', 'price', 'brokerage_fee', 'other_fees']:
        op.alter_column(
            'transactions', name, type_=sa.Float(),
            postgresql_using=f'{name}::double precision', existing_nullable=False,
        )
    for name in ['fx_rate', 'asset_currency', 'settlement_date', 'trade_date']:
        op.drop_column('transactions', name)
