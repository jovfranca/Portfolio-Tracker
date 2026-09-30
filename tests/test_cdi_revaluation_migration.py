import importlib.util
import os
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


@pytest.mark.parametrize('backend', ['sqlite', pytest.param(
    'postgres', marks=pytest.mark.skipif(os.getenv('RUN_DB_TESTS') != '1',
                                        reason='Requires a migrated PostgreSQL test database.'))])
def test_cdi_revaluation_invalidates_only_affected_portfolios_from_earliest_date(backend):
    path = Path(__file__).parents[1] / 'migrations/versions/0022_cdi_completed_periods.py'
    spec = importlib.util.spec_from_file_location('cdi_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    if backend == 'postgres':
        from src.database import engine
    else:
        engine = create_engine('sqlite://')
    with engine.begin() as connection:
        for statement in (
            'CREATE TEMPORARY TABLE portfolios (id INTEGER, dirty_from DATE)',
            'CREATE TEMPORARY TABLE assets (id INTEGER, portfolio_id INTEGER)',
            'CREATE TEMPORARY TABLE benchmarks (id INTEGER, code TEXT)',
            'CREATE TEMPORARY TABLE fixed_income_lots (asset_id INTEGER, benchmark_id INTEGER, start_date DATE)',
            "INSERT INTO portfolios VALUES (1, NULL), (2, '2023-01-01'), (3, NULL), (4, NULL)",
            'INSERT INTO assets VALUES (1, 1), (2, 2), (3, 3)',
            "INSERT INTO benchmarks VALUES (1, 'CDI'), (2, 'IPCA')",
            "INSERT INTO fixed_income_lots VALUES (1, 1, '2024-02-01'), (1, 1, '2024-01-02'), (2, 1, '2024-01-02'), (3, 2, '2024-01-02')",
        ):
            connection.execute(text(statement))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
        assert connection.execute(text('SELECT id, CAST(dirty_from AS TEXT) FROM portfolios ORDER BY id')).all() == [
            (1, '2024-01-02'), (2, '2023-01-01'), (3, None), (4, None)]
        for table in ('fixed_income_lots', 'benchmarks', 'assets', 'portfolios'):
            connection.execute(text(f'DROP TABLE {table}'))
    if backend == 'sqlite':
        engine.dispose()
