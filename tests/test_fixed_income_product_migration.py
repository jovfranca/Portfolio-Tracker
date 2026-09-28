"""Migration 0021 preserves existing fixed-income identities and assigns known owners."""
import importlib

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def test_product_migration_backfills_unambiguous_private_owner():
    migration = importlib.import_module('migrations.versions.0021_fixed_income_products')
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE portfolios (id integer PRIMARY KEY)'))
        connection.execute(text('CREATE TABLE instruments (id integer PRIMARY KEY, symbol text, asset_type text, origin text)'))
        connection.execute(text('CREATE TABLE assets (id integer PRIMARY KEY, instrument_id integer, portfolio_id integer)'))
        connection.execute(text('INSERT INTO portfolios VALUES (1), (2)'))
        connection.execute(text("INSERT INTO instruments VALUES (1, 'PRIVATE-A', 'FIXED_INCOME', 'CUSTOM'), "
                                "(2, 'PRIVATE-B', 'FIXED_INCOME', 'CUSTOM'), "
                                "(3, 'CDB', 'FIXED_INCOME', 'CATALOG')"))
        connection.execute(text('INSERT INTO assets VALUES (1, 1, 1), (2, 2, 1), (3, 2, 2)'))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert connection.execute(text('SELECT id, portfolio_id FROM instruments ORDER BY id')).all() == [
            (1, 1), (2, None), (3, None)]
        assert connection.scalar(text('SELECT count(*) FROM fixed_income_products')) == 0
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert 'portfolio_id' not in [row[1] for row in connection.execute(text('PRAGMA table_info(instruments)'))]
    engine.dispose()
