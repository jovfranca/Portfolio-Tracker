"""The populated single-user upgrade retains all source and derived data."""
import importlib
import os
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import text

from src.database import Base, engine


@pytest.mark.integration
@pytest.mark.skipif(os.getenv('RUN_DB_TESTS') != '1', reason='Requires a migrated PostgreSQL test database.')
def test_identity_upgrade_preserves_financial_and_shared_rows():
    migration = importlib.import_module('migrations.versions.0026_identity_and_financial_spaces')
    schema = 'identity_' + uuid4().hex
    with engine.connect() as connection, connection.begin():
        connection.execute(text(f'CREATE SCHEMA {schema}'))
        connection.execute(text(f'SET LOCAL search_path TO {schema}'))
        connection.execute(text('CREATE TABLE portfolios (id integer PRIMARY KEY, name text, dirty_from date)'))
        connection.execute(text('CREATE TABLE instruments (id integer PRIMARY KEY, symbol text, asset_type text, origin text, portfolio_id integer)'))
        connection.execute(text("CREATE UNIQUE INDEX uq_instruments_crypto_symbol ON instruments(symbol) WHERE asset_type = 'CRYPTO'"))
        connection.execute(text("INSERT INTO portfolios VALUES (42, 'Retained', '2024-01-02')"))
        connection.execute(text("INSERT INTO instruments VALUES (12, 'CATALOG', 'STOCK', 'CATALOG', NULL), (13, 'PRIVATE', 'OTHER', 'CUSTOM', NULL), (14, 'BOND', 'FIXED_INCOME', 'CUSTOM', 42), (15, 'LEGACY', 'OTHER', 'MIGRATED', NULL)"))
        tables = ('transactions', 'assets', 'user_corporate_events', 'user_defined_prices',
                  'legacy_imports', 'transaction_imports', 'fixed_income_lots', 'fixed_income_movements',
                  'position_snapshots', 'fixed_income_snapshots', 'provider_instruments',
                  'market_prices', 'corporate_actions', 'exchange_rates', 'benchmark_observations')
        for table in tables:
            connection.execute(text(f'CREATE TABLE {table} (id integer PRIMARY KEY, retained jsonb)'))
            connection.execute(text(f"INSERT INTO {table} VALUES (42, '{{\"amount\": 123.456, \"currency\": \"USD\", \"date\": \"2024-01-02\"}}')"))
        before = {table: connection.execute(text(f'SELECT * FROM {table}')).all() for table in tables}
        context = MigrationContext.configure(connection, opts={'target_metadata': Base.metadata})
        with Operations.context(context):
            migration.upgrade()
        assert connection.execute(text('SELECT user_id, household_id, role FROM memberships')).one() == (1, 1, 'OWNER')
        assert connection.execute(text('SELECT id, name, dirty_from::text, household_id FROM portfolios')).one() == (42, 'Retained', '2024-01-02', 1)
        assert connection.execute(text('SELECT id, household_id FROM instruments ORDER BY id')).all() == [(12, None), (13, 1), (14, 1), (15, 1)]
        for table in tables:
            assert connection.execute(text(f'SELECT * FROM {table}')).all() == before[table]
        assert connection.execute(text('SELECT provider, provider_subject FROM auth_identities')).one() == ('LOCAL', 'local')
        with Operations.context(context):
            migration.downgrade()
        assert connection.execute(text('SELECT id, name FROM portfolios')).one() == (42, 'Retained')
        connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
