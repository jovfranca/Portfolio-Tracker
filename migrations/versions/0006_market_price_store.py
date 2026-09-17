"""Add shared market prices, cached quotes, and private manual prices."""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'instruments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('symbol', sa.String(40), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.UniqueConstraint('symbol', 'currency'),
    )
    op.add_column('assets', sa.Column('instrument_id', sa.Integer(), nullable=True))
    op.execute("""
        INSERT INTO instruments (symbol, currency)
        SELECT DISTINCT a.ticker, COALESCE(
            (SELECT t.asset_currency FROM transactions t
             WHERE t.portfolio_id = a.portfolio_id AND t.asset = a.ticker LIMIT 1),
            'BRL'
        )
        FROM assets a
    """)
    op.execute("""
        UPDATE assets a SET instrument_id = i.id
        FROM instruments i
        WHERE i.symbol = a.ticker AND i.currency = COALESCE(
            (SELECT t.asset_currency FROM transactions t
             WHERE t.portfolio_id = a.portfolio_id AND t.asset = a.ticker LIMIT 1),
            'BRL'
        )
    """)
    op.alter_column('assets', 'instrument_id', nullable=False)
    op.create_foreign_key(
        'fk_assets_instrument_id_instruments', 'assets', 'instruments',
        ['instrument_id'], ['id'], ondelete='RESTRICT',
    )

    op.create_table(
        'market_prices',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('instrument_id', sa.Integer(), sa.ForeignKey('instruments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('interval', sa.String(12), nullable=False),
        sa.Column('reference_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('price', sa.Numeric(28, 12), nullable=False),
        sa.Column('open', sa.Numeric(28, 12), nullable=True),
        sa.Column('high', sa.Numeric(28, 12), nullable=True),
        sa.Column('low', sa.Numeric(28, 12), nullable=True),
        sa.Column('volume', sa.BigInteger(), nullable=True),
        sa.Column('dividends', sa.Numeric(28, 12), nullable=False, server_default='0'),
        sa.Column('stock_splits', sa.Numeric(28, 12), nullable=False, server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('source', sa.String(80), nullable=False),
        sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('price > 0', name='ck_market_prices_positive_price'),
        sa.UniqueConstraint('instrument_id', 'interval', 'reference_at', 'source'),
    )
    op.create_index(
        'ix_market_prices_lookup', 'market_prices',
        ['instrument_id', 'interval', 'reference_at'],
    )
    op.create_table(
        'market_price_coverage',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('instrument_id', sa.Integer(), sa.ForeignKey('instruments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('interval', sa.String(12), nullable=False),
        sa.Column('source', sa.String(80), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('end_date >= start_date', name='ck_market_price_coverage_valid_range'),
        sa.UniqueConstraint('instrument_id', 'interval', 'source', 'start_date', 'end_date'),
    )
    op.create_index(
        'ix_market_price_coverage_lookup', 'market_price_coverage',
        ['instrument_id', 'interval', 'source'],
    )
    op.create_table(
        'latest_market_quotes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('instrument_id', sa.Integer(), sa.ForeignKey('instruments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('price', sa.Numeric(28, 12), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('source', sa.String(80), nullable=False),
        sa.Column('market_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('price > 0', name='ck_latest_market_quotes_positive_price'),
        sa.UniqueConstraint('instrument_id', 'source'),
    )
    op.create_index(
        'ix_latest_market_quotes_lookup', 'latest_market_quotes',
        ['instrument_id', 'retrieved_at'],
    )
    op.create_table(
        'user_defined_prices',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('asset_id', sa.Integer(), sa.ForeignKey('assets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('reference_date', sa.Date(), nullable=False),
        sa.Column('price', sa.Numeric(28, 12), nullable=False),
        sa.Column('dividends', sa.Numeric(28, 12), nullable=False, server_default='0'),
        sa.Column('stock_splits', sa.Numeric(28, 12), nullable=False, server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('source', sa.String(80), nullable=False),
        sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('price >= 0', name='ck_user_defined_prices_nonnegative_price'),
        sa.UniqueConstraint('asset_id', 'reference_date'),
    )

    # Existing observations have portfolio ownership, potentially different
    # values and (for Yahoo) an adjusted price basis. Keep each observation
    # private with its original source; only new verified fetches are shared.
    # The old schema had no retrieval timestamps or queried-range metadata.
    op.execute("""
        INSERT INTO user_defined_prices
            (asset_id, reference_date, price, dividends, stock_splits,
             currency, source, retrieved_at)
        SELECT h.asset_id, h.date, h.close, h.dividends, h.stock_splits,
               i.currency, h.source, NULL
        FROM asset_history h
        JOIN assets a ON a.id = h.asset_id
        JOIN instruments i ON i.id = a.instrument_id
    """)
    op.drop_table('asset_history')


def downgrade():
    op.create_table(
        'asset_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('asset_id', sa.Integer(), sa.ForeignKey('assets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('close', sa.Float(), nullable=False),
        sa.Column('dividends', sa.Float(), nullable=False, server_default='0'),
        sa.Column('stock_splits', sa.Float(), nullable=False, server_default='0'),
        sa.Column('source', sa.String(30), nullable=False),
        sa.CheckConstraint('close >= 0', name='ck_asset_history_close'),
        sa.UniqueConstraint('asset_id', 'date'),
    )
    op.execute("""
        INSERT INTO asset_history (asset_id, date, close, dividends, stock_splits, source)
        SELECT a.id, (p.reference_at AT TIME ZONE 'UTC')::date,
               p.price, p.dividends, p.stock_splits, p.source
        FROM market_prices p JOIN assets a ON a.instrument_id = p.instrument_id
        ON CONFLICT (asset_id, date) DO NOTHING
    """)
    op.execute("""
        INSERT INTO asset_history (asset_id, date, close, dividends, stock_splits, source)
        SELECT asset_id, reference_date, price, dividends, stock_splits, source
        FROM user_defined_prices
        ON CONFLICT (asset_id, date) DO UPDATE SET
            close = EXCLUDED.close, dividends = EXCLUDED.dividends,
            stock_splits = EXCLUDED.stock_splits, source = EXCLUDED.source
    """)
    op.drop_table('user_defined_prices')
    op.drop_index('ix_latest_market_quotes_lookup', table_name='latest_market_quotes')
    op.drop_table('latest_market_quotes')
    op.drop_index('ix_market_price_coverage_lookup', table_name='market_price_coverage')
    op.drop_table('market_price_coverage')
    op.drop_index('ix_market_prices_lookup', table_name='market_prices')
    op.drop_table('market_prices')
    op.drop_constraint('fk_assets_instrument_id_instruments', 'assets', type_='foreignkey')
    op.drop_column('assets', 'instrument_id')
    op.drop_table('instruments')
