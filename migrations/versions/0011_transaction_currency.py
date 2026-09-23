"""Rename the persisted transaction currency without rewriting its values."""
from alembic import op


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'transactions', 'asset_currency', new_column_name='transaction_currency',
    )


def downgrade():
    op.alter_column(
        'transactions', 'transaction_currency', new_column_name='asset_currency',
    )
