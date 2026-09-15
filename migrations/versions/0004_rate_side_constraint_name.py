"""Align the rate-side constraint name with the SQLAlchemy metadata."""
from alembic import op


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        'ALTER TABLE exchange_rates RENAME CONSTRAINT '
        'ck_exchange_rates_ck_exchange_rates_rate_side TO ck_exchange_rates_rate_side'
    )


def downgrade():
    op.execute(
        'ALTER TABLE exchange_rates RENAME CONSTRAINT '
        'ck_exchange_rates_rate_side TO ck_exchange_rates_ck_exchange_rates_rate_side'
    )
