"""Add catalog provenance and deterministic primary provider mappings.

Legacy mappings created speculatively by 0008 are not trusted. Unreferenced
ones are removed; mappings that own historical observations are retained but
inactive so their data remains reachable. The catalog seed can reactivate a
matching mapping after validating its ownership.
"""
from alembic import op
import sqlalchemy as sa


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'instruments',
        sa.Column('origin', sa.String(16), nullable=False, server_default='MIGRATED'),
    )
    op.alter_column('instruments', 'origin', server_default='CUSTOM')
    op.add_column(
        'provider_instruments',
        sa.Column('is_primary', sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # 0008 could not distinguish a real provider identity from an old ticker.
    # Remove only untouched migration guesses. Preserve mappings that own
    # observations or have post-migration aliases, but never use them for new
    # network calls until the controlled catalog explicitly confirms them.
    op.execute("""
        DELETE FROM provider_instruments pi
        WHERE NOT EXISTS (
            SELECT 1 FROM market_prices p WHERE p.provider_instrument_id = pi.id
        ) AND NOT EXISTS (
            SELECT 1 FROM market_price_coverage c WHERE c.provider_instrument_id = pi.id
        ) AND NOT EXISTS (
            SELECT 1 FROM latest_market_quotes q WHERE q.provider_instrument_id = pi.id
        ) AND NOT EXISTS (
            SELECT 1 FROM instrument_aliases a
            WHERE a.instrument_id = pi.instrument_id AND a.source <> 'migration'
        )
    """)
    op.execute("UPDATE provider_instruments SET active = false")
    op.create_check_constraint(
        'ck_provider_instruments_primary_mapping_active',
        'provider_instruments',
        'NOT is_primary OR active',
    )
    op.create_index(
        'uq_provider_instruments_primary',
        'provider_instruments',
        ['instrument_id', 'provider'],
        unique=True,
        postgresql_where=sa.text('is_primary'),
    )


def downgrade():
    op.drop_index('uq_provider_instruments_primary', table_name='provider_instruments')
    op.drop_constraint(
        'ck_provider_instruments_primary_mapping_active',
        'provider_instruments',
        type_='check',
    )
    op.drop_column('provider_instruments', 'is_primary')
    op.drop_column('instruments', 'origin')
