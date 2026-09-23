"""Regression coverage for migration 0008 on PostgreSQL."""
import importlib
import os
import uuid
from decimal import Decimal

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from src.database import engine


pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.getenv('RUN_DB_TESTS') != '1', reason='Requires a migrated PostgreSQL test database.',
)]


def test_canonical_identity_migration_backfills_transactions_and_prices():
    migration = importlib.import_module('migrations.versions.0008_canonical_instrument_identity')
    currency_migration = importlib.import_module('migrations.versions.0009_provider_quote_currency')
    catalog_migration = importlib.import_module('migrations.versions.0010_catalog_primary_mapping')
    transaction_currency_migration = importlib.import_module('migrations.versions.0011_transaction_currency')
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            schema = 'identity_' + uuid.uuid4().hex
            connection.execute(text(f'CREATE SCHEMA {schema}'))
            connection.execute(text(f'SET LOCAL search_path TO {schema}'))
            connection.execute(text('''CREATE TABLE instruments (
                id integer PRIMARY KEY, symbol varchar(40) NOT NULL, currency varchar(3) NOT NULL,
                CONSTRAINT uq_instruments_symbol UNIQUE (symbol, currency))'''))
            connection.execute(text('''CREATE TABLE assets (
                id integer PRIMARY KEY, portfolio_id integer NOT NULL, ticker varchar(40) NOT NULL,
                instrument_id integer NOT NULL REFERENCES instruments(id),
                CONSTRAINT uq_assets_portfolio_id UNIQUE (portfolio_id, ticker))'''))
            connection.execute(text('''CREATE TABLE transactions (
                id integer PRIMARY KEY, portfolio_id integer NOT NULL, asset varchar(40) NOT NULL,
                asset_currency varchar(3) NOT NULL, fx_rate numeric NOT NULL)'''))
            connection.execute(text('''CREATE TABLE market_prices (
                id integer PRIMARY KEY, instrument_id integer NOT NULL REFERENCES instruments(id),
                interval varchar(12) NOT NULL, reference_at timestamptz NOT NULL,
                price numeric(28,12) NOT NULL, source varchar(80) NOT NULL,
                CONSTRAINT uq_market_prices_instrument_id UNIQUE
                    (instrument_id, interval, reference_at, source))'''))
            connection.execute(text('CREATE INDEX ix_market_prices_lookup ON market_prices (instrument_id, interval, reference_at)'))
            connection.execute(text('''CREATE TABLE market_price_coverage (
                id integer PRIMARY KEY, instrument_id integer NOT NULL REFERENCES instruments(id),
                interval varchar(12) NOT NULL, source varchar(80) NOT NULL,
                start_date date NOT NULL, end_date date NOT NULL,
                CONSTRAINT uq_market_price_coverage_instrument_id UNIQUE
                    (instrument_id, interval, source, start_date, end_date))'''))
            connection.execute(text('CREATE INDEX ix_market_price_coverage_lookup ON market_price_coverage (instrument_id, interval, source)'))
            connection.execute(text('''CREATE TABLE latest_market_quotes (
                id integer PRIMARY KEY, instrument_id integer NOT NULL REFERENCES instruments(id),
                price numeric(28,12) NOT NULL, source varchar(80) NOT NULL,
                retrieved_at timestamptz NOT NULL,
                CONSTRAINT uq_latest_market_quotes_instrument_id UNIQUE (instrument_id, source))'''))
            connection.execute(text('CREATE INDEX ix_latest_market_quotes_lookup ON latest_market_quotes (instrument_id, retrieved_at)'))
            connection.execute(text("INSERT INTO instruments VALUES (1, 'AAPL', 'USD')"))
            connection.execute(text("INSERT INTO instruments VALUES (2, 'PRIVATE', 'BRL')"))
            connection.execute(text("INSERT INTO assets VALUES (1, 10, 'AAPL', 1)"))
            connection.execute(text("INSERT INTO transactions VALUES (1, 10, 'AAPL', 'USD', 5.12)"))
            connection.execute(text("INSERT INTO assets VALUES (2, 10, 'PRIVATE', 2)"))
            connection.execute(text("INSERT INTO transactions VALUES (2, 10, 'PRIVATE', 'BRL', 1)"))
            connection.execute(text('CREATE TABLE user_defined_prices (id integer PRIMARY KEY, asset_id integer, price numeric, source text)'))
            connection.execute(text("INSERT INTO user_defined_prices VALUES (1, 2, 123.45, 'manual')"))
            connection.execute(text('CREATE TABLE exchange_rates (id integer PRIMARY KEY, currency text, rate_type text, rate numeric)'))
            connection.execute(text("INSERT INTO exchange_rates VALUES (1, 'USD', 'FX', 5.12), (2, 'USD', 'PTAX', 5.13)"))
            connection.execute(text("""INSERT INTO market_prices VALUES
                (1, 1, '1d', '2024-01-08T00:00:00Z', 185.50, 'yfinance')"""))
            connection.execute(text("""INSERT INTO market_price_coverage VALUES
                (1, 1, '1d', 'yfinance', '2024-01-01', '2024-01-08')"""))
            connection.execute(text("""INSERT INTO latest_market_quotes VALUES
                (1, 1, 186, 'yfinance', '2024-01-08T20:00:00Z')"""))

            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                currency_migration.upgrade()
                catalog_migration.upgrade()
                transaction_currency_migration.upgrade()

            assert connection.scalar(text('SELECT instrument_id FROM transactions WHERE id = 1')) == 1
            assert connection.scalar(text('SELECT count(*) FROM provider_instruments')) == 1
            assert connection.scalar(text('SELECT quote_currency FROM provider_instruments WHERE instrument_id = 1')) == 'USD'
            assert connection.scalar(text('SELECT active FROM provider_instruments WHERE instrument_id = 1')) is False
            assert connection.scalar(text('SELECT is_primary FROM provider_instruments WHERE instrument_id = 1')) is False
            assert connection.scalar(text("SELECT origin FROM instruments WHERE id = 1")) == 'MIGRATED'
            assert connection.scalar(text('SELECT count(*) FROM provider_instruments WHERE instrument_id = 2')) == 0
            assert connection.scalar(text("SELECT is_nullable FROM information_schema.columns WHERE table_schema = :schema AND table_name = 'instruments' AND column_name = 'currency'"), {'schema': schema}) == 'YES'
            assert connection.scalar(text("SELECT count(*) FROM pg_indexes WHERE schemaname = :schema AND indexname = 'uq_instruments_crypto_symbol'"), {'schema': schema}) == 1
            assert connection.scalar(text('SELECT instrument_id FROM transactions WHERE id = 2')) == 2
            assert connection.scalar(text('SELECT transaction_currency FROM transactions WHERE id = 1')) == 'USD'
            assert connection.scalar(text('SELECT fx_rate FROM transactions WHERE id = 1')) == Decimal('5.12')
            assert connection.scalar(text('SELECT price FROM user_defined_prices')) == connection.scalar(text('SELECT 123.45::numeric'))
            assert connection.scalar(text('SELECT count(*) FROM exchange_rates')) == 2
            assert connection.scalar(text("SELECT provider_symbol FROM provider_instruments WHERE instrument_id = 1")) == 'AAPL'
            assert connection.scalar(text('SELECT price FROM market_prices WHERE id = 1')) == 185.5
            assert connection.scalar(text('SELECT provider_instrument_id FROM market_prices WHERE id = 1')) == 1
            assert connection.scalar(text("SELECT normalized_alias FROM instrument_aliases WHERE instrument_id = 1")) == 'AAPL'
            assert connection.scalar(text('SELECT count(*) FROM market_price_coverage')) == 1
            assert connection.scalar(text('SELECT price FROM latest_market_quotes')) == 186
            with Operations.context(MigrationContext.configure(connection)):
                transaction_currency_migration.downgrade()
                catalog_migration.downgrade()
                currency_migration.downgrade()
                migration.downgrade()
            assert connection.scalar(text('SELECT instrument_id FROM market_prices')) == 1
            assert connection.scalar(text('SELECT price FROM market_prices')) == 185.5
            assert connection.scalar(text('SELECT instrument_id FROM market_price_coverage')) == 1
            assert connection.scalar(text('SELECT price FROM latest_market_quotes')) == 186
        finally:
            transaction.rollback()
