"""Store PTAX closing buy and sell observations separately."""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('exchange_rates', sa.Column('rate_side', sa.String(6), nullable=True))
    op.execute(
        "UPDATE exchange_rates SET rate_side = "
        "CASE WHEN rate_type = 'PTAX' THEN 'SELL' ELSE 'MARKET' END"
    )
    op.alter_column('exchange_rates', 'rate_side', nullable=False)
    op.drop_constraint(
        'uq_exchange_rates_currency', 'exchange_rates', type_='unique'
    )
    op.create_unique_constraint(
        'uq_exchange_rates_currency',
        'exchange_rates',
        ['currency', 'rate_type', 'reference_date', 'rate_side'],
    )
    op.create_check_constraint(
        'ck_exchange_rates_rate_side',
        'exchange_rates',
        "rate_side IN ('MARKET', 'BUY', 'SELL')",
    )


def downgrade():
    op.execute(
        "DELETE FROM exchange_rates WHERE rate_side != "
        "CASE WHEN rate_type = 'PTAX' THEN 'SELL' ELSE 'MARKET' END"
    )
    op.drop_constraint('ck_exchange_rates_rate_side', 'exchange_rates', type_='check')
    op.drop_constraint('uq_exchange_rates_currency', 'exchange_rates', type_='unique')
    op.create_unique_constraint(
        'uq_exchange_rates_currency',
        'exchange_rates',
        ['currency', 'rate_type', 'reference_date'],
    )
    op.drop_column('exchange_rates', 'rate_side')
