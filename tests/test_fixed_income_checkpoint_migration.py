"""Upgrade preserves sources and market history while scheduling unbuilt lots."""
import importlib
import os
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import text

from src.database import engine


@pytest.mark.integration
@pytest.mark.skipif(os.getenv('RUN_DB_TESTS') != '1', reason='Requires a migrated PostgreSQL test database.')
def test_fixed_income_checkpoint_migration_preserves_sources_and_market_history():
    migration = importlib.import_module('migrations.versions.0025_fixed_income_checkpoints')
    schema = 'checkpoint_' + uuid4().hex
    with engine.connect() as connection, connection.begin():
        connection.execute(text(f'CREATE SCHEMA {schema}'))
        connection.execute(text(f'SET LOCAL search_path TO {schema}'))
        connection.execute(text('CREATE TABLE portfolios (id integer PRIMARY KEY, dirty_from date)'))
        connection.execute(text('CREATE TABLE instruments (id integer PRIMARY KEY)'))
        connection.execute(text('CREATE TABLE assets (id integer PRIMARY KEY, portfolio_id integer, instrument_id integer)'))
        connection.execute(text('CREATE TABLE fixed_income_lots (id integer PRIMARY KEY, asset_id integer, start_date date)'))
        connection.execute(text('CREATE TABLE fixed_income_movements (id integer PRIMARY KEY, lot_id integer, amount numeric)'))
        connection.execute(text('CREATE TABLE position_snapshots (id integer PRIMARY KEY, reporting_currency text)'))
        connection.execute(text('CREATE TABLE position_invalidations (portfolio_id integer, instrument_id integer, dirty_from date, reason text, UNIQUE (portfolio_id, instrument_id))'))
        connection.execute(text('INSERT INTO portfolios VALUES (1, NULL)'))
        connection.execute(text('INSERT INTO instruments VALUES (1), (2)'))
        connection.execute(text('INSERT INTO assets VALUES (1, 1, 1), (2, 1, 2)'))
        connection.execute(text("INSERT INTO fixed_income_lots VALUES (1, 1, '2024-01-02'), (2, 1, '2024-03-01')"))
        connection.execute(text('INSERT INTO fixed_income_movements VALUES (1, 1, 1000), (2, 2, 2000)'))
        connection.execute(text("INSERT INTO position_snapshots VALUES (42, 'USD')"))
        connection.execute(text("INSERT INTO position_invalidations VALUES (1, 1, '2023-01-01', 'source')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert connection.execute(text('SELECT lot_id, dirty_from::text FROM fixed_income_invalidations ORDER BY lot_id')).all() == [
            (1, '2024-01-02'), (2, '2024-03-01')]
        assert connection.scalar(text('SELECT dirty_from::text FROM portfolios')) == '2023-01-01'
        assert connection.execute(text('SELECT id, reporting_currency FROM position_snapshots')).one() == (42, 'USD')
        assert connection.scalar(text('SELECT SUM(amount) FROM fixed_income_movements')) == 3000
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
