"""Exercise the new migration with synthetic pre-existing data in a rolled-back schema."""
import importlib
import os
import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from src.database import engine


pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.getenv('RUN_DB_TESTS') != '1', reason='Requires migrated PostgreSQL test database.',
)]


@pytest.mark.parametrize('round_trip', [False, True])
def test_migration_preserves_private_history_and_zero_prices(round_trip):
    migration = importlib.import_module('migrations.versions.0006_market_price_store')
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            schema = 'review_' + uuid.uuid4().hex
            connection.execute(text(f'CREATE SCHEMA {schema}'))
            connection.execute(text(f'SET LOCAL search_path TO {schema}'))
            connection.execute(text('CREATE TABLE assets (id integer PRIMARY KEY, portfolio_id integer, ticker text)'))
            connection.execute(text('CREATE TABLE transactions (portfolio_id integer, asset text, asset_currency text)'))
            connection.execute(text('''CREATE TABLE asset_history (
                id integer PRIMARY KEY, asset_id integer, date date, close float,
                dividends float, stock_splits float, source text)'''))
            connection.execute(text("INSERT INTO assets VALUES (1, 1, 'TEST'), (2, 2, 'TEST')"))
            connection.execute(text("""INSERT INTO asset_history VALUES
                (1, 1, '2024-01-01', 0, 0, 0, 'manual'),
                (2, 1, '2024-01-02', 10, 0, 0, 'legacy'),
                (3, 2, '2024-01-02', 20, 0, 0, 'legacy'),
                (4, 1, '2024-01-04', 30, 0.5, 2, 'yfinance'),
                (5, 2, '2024-01-01', 12, 0, 0, 'manual'),
                (6, 2, '2024-01-04', 0, 0, 0, 'yfinance')"""))
            original = connection.execute(text(
                'SELECT asset_id, date, close, dividends, stock_splits, source FROM asset_history ORDER BY asset_id, date'
            )).all()
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            private = connection.execute(text(
                'SELECT asset_id, price, source FROM user_defined_prices ORDER BY asset_id, reference_date'
            )).all()
            assert private == [(1, 0, 'manual'), (1, 10, 'legacy'), (1, 30, 'yfinance'),
                               (2, 12, 'manual'), (2, 20, 'legacy'), (2, 0, 'yfinance')]
            assert connection.scalar(text('SELECT count(*) FROM user_defined_prices WHERE retrieved_at IS NOT NULL')) == 0
            # Old Yahoo closes were adjusted; their price basis and retrieval time
            # cannot be asserted to match fresh provider observations.
            assert connection.scalar(text('SELECT count(*) FROM market_prices')) == 0
            assert connection.scalar(text('SELECT count(*) FROM market_price_coverage')) == 0
            if round_trip:
                with Operations.context(MigrationContext.configure(connection)):
                    migration.downgrade()
                restored = connection.execute(text(
                    'SELECT asset_id, date, close, dividends, stock_splits, source FROM asset_history ORDER BY asset_id, date'
                )).all()
                assert restored == original
        finally:
            transaction.rollback()
