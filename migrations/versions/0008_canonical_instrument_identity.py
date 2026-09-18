"""Separate canonical instruments from provider symbols and raw aliases."""
from alembic import op
import sqlalchemy as sa


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('instruments', sa.Column('name', sa.String(200), nullable=False, server_default=''))
    op.add_column('instruments', sa.Column('asset_type', sa.String(40), nullable=False, server_default='OTHER'))
    op.add_column('instruments', sa.Column('exchange', sa.String(40), nullable=True))
    op.add_column('instruments', sa.Column('status', sa.String(16), nullable=False, server_default='ACTIVE'))
    op.add_column('instruments', sa.Column('isin', sa.String(12), nullable=True))
    op.drop_constraint('uq_instruments_symbol', 'instruments', type_='unique')

    op.create_table(
        'provider_instruments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('instrument_id', sa.Integer(), sa.ForeignKey('instruments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('provider', sa.String(80), nullable=False),
        sa.Column('provider_symbol', sa.String(80), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('provider_exchange', sa.String(80), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint('provider', 'provider_symbol', 'currency'),
    )
    op.create_index(
        'ix_provider_instruments_instrument_provider', 'provider_instruments',
        ['instrument_id', 'provider'],
    )
    op.create_table(
        'instrument_aliases',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('instrument_id', sa.Integer(), sa.ForeignKey('instruments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('alias', sa.String(120), nullable=False),
        sa.Column('normalized_alias', sa.String(120), nullable=False),
        sa.Column('source', sa.String(80), nullable=False, server_default='migration'),
        sa.UniqueConstraint('instrument_id', 'normalized_alias', 'source'),
    )
    op.create_index('ix_instrument_aliases_normalized_alias', 'instrument_aliases', ['normalized_alias'])

    # Existing symbols already work with the configured MVP provider. Preserve
    # every source represented by provider-backed rows, plus the default mapping.
    op.execute("""
        INSERT INTO provider_instruments
            (instrument_id, provider, provider_symbol, currency, active)
        SELECT id, 'yfinance', symbol, currency, true FROM instruments
    """)
    op.execute("""
        INSERT INTO provider_instruments
            (instrument_id, provider, provider_symbol, currency, active)
        SELECT DISTINCT i.id, sources.source, i.symbol, i.currency, true
        FROM instruments i
        CROSS JOIN LATERAL (
            SELECT source FROM market_prices WHERE instrument_id = i.id
            UNION SELECT source FROM market_price_coverage WHERE instrument_id = i.id
            UNION SELECT source FROM latest_market_quotes WHERE instrument_id = i.id
        ) sources
        ON CONFLICT (provider, provider_symbol, currency) DO NOTHING
    """)
    op.execute("""
        INSERT INTO instrument_aliases
            (instrument_id, alias, normalized_alias, source)
        SELECT id, symbol, upper(regexp_replace(symbol, '\\s+', '', 'g')), 'migration'
        FROM instruments
    """)

    op.add_column('transactions', sa.Column('instrument_id', sa.Integer(), nullable=True))
    op.execute("""
        UPDATE transactions t SET instrument_id = a.instrument_id
        FROM assets a
        WHERE a.portfolio_id = t.portfolio_id AND a.ticker = t.asset
    """)
    op.alter_column('transactions', 'instrument_id', nullable=False)
    op.create_foreign_key(
        'fk_transactions_instrument_id_instruments', 'transactions', 'instruments',
        ['instrument_id'], ['id'], ondelete='RESTRICT',
    )

    provider_fk_names = {
        'market_prices': 'fk_market_prices_provider_mapping',
        'market_price_coverage': 'fk_market_price_coverage_provider_mapping',
        'latest_market_quotes': 'fk_latest_market_quotes_provider_mapping',
    }
    for table in ('market_prices', 'market_price_coverage', 'latest_market_quotes'):
        op.add_column(table, sa.Column('provider_instrument_id', sa.Integer(), nullable=True))
        op.execute(f"""
            UPDATE {table} p SET provider_instrument_id = pi.id
            FROM provider_instruments pi
            WHERE pi.instrument_id = p.instrument_id
              AND pi.provider = p.source
              AND pi.currency = (SELECT currency FROM instruments WHERE id = p.instrument_id)
        """)
        op.alter_column(table, 'provider_instrument_id', nullable=False)
        op.create_foreign_key(
            provider_fk_names[table],
            table, 'provider_instruments', ['provider_instrument_id'], ['id'],
            ondelete='CASCADE',
        )

    op.drop_index('ix_market_prices_lookup', table_name='market_prices')
    op.drop_constraint('uq_market_prices_instrument_id', 'market_prices', type_='unique')
    op.create_unique_constraint(
        'uq_market_prices_provider_instrument_id', 'market_prices',
        ['provider_instrument_id', 'interval', 'reference_at'],
    )
    op.create_index(
        'ix_market_prices_lookup', 'market_prices',
        ['provider_instrument_id', 'interval', 'reference_at'],
    )

    op.drop_index('ix_market_price_coverage_lookup', table_name='market_price_coverage')
    op.drop_constraint('uq_market_price_coverage_instrument_id', 'market_price_coverage', type_='unique')
    op.create_unique_constraint(
        'uq_market_price_coverage_provider_instrument_id', 'market_price_coverage',
        ['provider_instrument_id', 'interval', 'start_date', 'end_date'],
    )
    op.create_index(
        'ix_market_price_coverage_lookup', 'market_price_coverage',
        ['provider_instrument_id', 'interval'],
    )

    op.drop_index('ix_latest_market_quotes_lookup', table_name='latest_market_quotes')
    op.drop_constraint('uq_latest_market_quotes_instrument_id', 'latest_market_quotes', type_='unique')
    op.create_unique_constraint(
        'uq_latest_market_quotes_provider_instrument_id', 'latest_market_quotes',
        ['provider_instrument_id'],
    )
    op.create_index(
        'ix_latest_market_quotes_lookup', 'latest_market_quotes',
        ['provider_instrument_id', 'retrieved_at'],
    )

    for table in ('market_prices', 'market_price_coverage', 'latest_market_quotes'):
        op.drop_column(table, 'instrument_id')

    op.drop_constraint('uq_assets_portfolio_id', 'assets', type_='unique')
    op.create_unique_constraint(
        'uq_assets_portfolio_id', 'assets', ['portfolio_id', 'instrument_id'],
    )


def downgrade():
    for table in ('market_prices', 'market_price_coverage', 'latest_market_quotes'):
        op.add_column(table, sa.Column('instrument_id', sa.Integer(), nullable=True))
        op.execute(f"""
            UPDATE {table} p SET instrument_id = pi.instrument_id
            FROM provider_instruments pi WHERE pi.id = p.provider_instrument_id
        """)
        op.alter_column(table, 'instrument_id', nullable=False)
        op.create_foreign_key(
            f'fk_{table}_instrument_id_instruments', table, 'instruments',
            ['instrument_id'], ['id'], ondelete='CASCADE',
        )

    op.drop_index('ix_market_prices_lookup', table_name='market_prices')
    op.drop_constraint('uq_market_prices_provider_instrument_id', 'market_prices', type_='unique')
    op.create_unique_constraint(
        'uq_market_prices_instrument_id', 'market_prices',
        ['instrument_id', 'interval', 'reference_at', 'source'],
    )
    op.create_index('ix_market_prices_lookup', 'market_prices', ['instrument_id', 'interval', 'reference_at'])

    op.drop_index('ix_market_price_coverage_lookup', table_name='market_price_coverage')
    op.drop_constraint('uq_market_price_coverage_provider_instrument_id', 'market_price_coverage', type_='unique')
    op.create_unique_constraint(
        'uq_market_price_coverage_instrument_id', 'market_price_coverage',
        ['instrument_id', 'interval', 'source', 'start_date', 'end_date'],
    )
    op.create_index('ix_market_price_coverage_lookup', 'market_price_coverage', ['instrument_id', 'interval', 'source'])

    op.drop_index('ix_latest_market_quotes_lookup', table_name='latest_market_quotes')
    op.drop_constraint('uq_latest_market_quotes_provider_instrument_id', 'latest_market_quotes', type_='unique')
    op.create_unique_constraint(
        'uq_latest_market_quotes_instrument_id', 'latest_market_quotes', ['instrument_id', 'source'],
    )
    op.create_index('ix_latest_market_quotes_lookup', 'latest_market_quotes', ['instrument_id', 'retrieved_at'])

    for table in ('market_prices', 'market_price_coverage', 'latest_market_quotes'):
        op.drop_column(table, 'provider_instrument_id')

    op.drop_constraint('uq_assets_portfolio_id', 'assets', type_='unique')
    op.create_unique_constraint('uq_assets_portfolio_id', 'assets', ['portfolio_id', 'ticker'])
    op.drop_constraint('fk_transactions_instrument_id_instruments', 'transactions', type_='foreignkey')
    op.drop_column('transactions', 'instrument_id')
    op.drop_index('ix_instrument_aliases_normalized_alias', table_name='instrument_aliases')
    op.drop_table('instrument_aliases')
    op.drop_index('ix_provider_instruments_instrument_provider', table_name='provider_instruments')
    op.drop_table('provider_instruments')
    op.create_unique_constraint('uq_instruments_symbol', 'instruments', ['symbol', 'currency'])
    for column in ('isin', 'status', 'exchange', 'asset_type', 'name'):
        op.drop_column('instruments', column)
