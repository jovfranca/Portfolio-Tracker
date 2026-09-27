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


def test_action_coverage_migration_preserves_sources_and_invalidates_derived_views():
    migration = importlib.import_module('migrations.versions.0017_action_coverage_finality')
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            schema = 'review_' + uuid.uuid4().hex
            connection.execute(text(f'CREATE SCHEMA {schema}'))
            connection.execute(text(f'SET LOCAL search_path TO {schema}'))
            connection.execute(text('CREATE TABLE corporate_action_coverage (id integer, source text)'))
            connection.execute(text("INSERT INTO corporate_action_coverage VALUES (1, 'yfinance')"))
            connection.execute(text('CREATE TABLE portfolios (id integer, dirty_from date, history_built_through date)'))
            connection.execute(text("INSERT INTO portfolios VALUES (1, NULL, '2024-03-01')"))
            connection.execute(text('CREATE TABLE transactions (portfolio_id integer, trade_date date)'))
            connection.execute(text("INSERT INTO transactions VALUES (1, '2024-01-01')"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            assert connection.execute(text('SELECT id, source, is_final FROM corporate_action_coverage')).one() == (
                1, 'yfinance', True)
            assert connection.scalar(text('SELECT dirty_from::text FROM portfolios')) == '2024-01-01'
            assert connection.scalar(text('SELECT history_built_through::text FROM portfolios')) == '2024-03-01'
            assert connection.scalar(text('SELECT count(*) FROM transactions')) == 1
            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade()
            assert connection.execute(text('SELECT * FROM corporate_action_coverage')).one() == (1, 'yfinance')
        finally:
            transaction.rollback()


def test_share_unit_migration_invalidates_only_provider_caches():
    migration = importlib.import_module('migrations.versions.0016_historical_share_units')
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            schema = 'review_' + uuid.uuid4().hex
            connection.execute(text(f'CREATE SCHEMA {schema}'))
            connection.execute(text(f'SET LOCAL search_path TO {schema}'))
            for table in ('market_prices', 'market_price_coverage', 'corporate_actions',
                          'corporate_action_coverage', 'user_defined_prices', 'user_corporate_events'):
                connection.execute(text(f'CREATE TABLE {table} (source text)'))
                connection.execute(text(f"INSERT INTO {table} VALUES ('yfinance'), ('manual'), ('legacy')"))
            connection.execute(text('CREATE TABLE position_snapshots (id integer)'))
            connection.execute(text('CREATE TABLE portfolios (id integer, dirty_from date, history_built_through date)'))
            connection.execute(text("INSERT INTO portfolios VALUES (1, '2024-02-01', '2024-03-01')"))
            connection.execute(text('CREATE TABLE transactions (portfolio_id integer, trade_date date)'))
            connection.execute(text("INSERT INTO transactions VALUES (1, '2024-01-01')"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            assert connection.scalar(text('SELECT dirty_from::text FROM portfolios')) == '2024-01-01'
            assert connection.scalar(text('SELECT history_built_through FROM portfolios')) is None
            for table in ('market_prices', 'market_price_coverage', 'corporate_actions', 'corporate_action_coverage'):
                assert connection.scalar(text(f'SELECT count(*) FROM {table}')) == 2
            for table in ('user_defined_prices', 'user_corporate_events'):
                assert connection.scalar(text(f'SELECT count(*) FROM {table}')) == 3
            assert connection.scalar(text('SELECT count(*) FROM transactions')) == 1
        finally:
            transaction.rollback()


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
