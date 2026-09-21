"""Separate quote currency without rewriting the already applied identity migration."""
from alembic import op
import sqlalchemy as sa

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('provider_instruments', 'currency', new_column_name='quote_currency')
    op.alter_column('instruments', 'currency', nullable=True)
    op.create_index('uq_instruments_crypto_symbol', 'instruments', ['symbol'], unique=True,
                    postgresql_where=sa.text("asset_type = 'CRYPTO'"))


def downgrade():
    # Refuse a lossy downgrade if new instruments have no native currency.
    op.alter_column('instruments', 'currency', nullable=False)
    op.drop_index('uq_instruments_crypto_symbol', table_name='instruments')
    op.alter_column('provider_instruments', 'quote_currency', new_column_name='currency')
