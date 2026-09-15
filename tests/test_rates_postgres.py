"""Rate persistence checks against a migrated, disposable PostgreSQL database."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal
import os
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from src.database import engine
from src.models import ExchangeRate
from src.rates import store_rates

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.getenv('RUN_DB_TESTS') != '1', reason='Requires a migrated test database.')]


def test_migrated_rate_check_constraints_match_model():
    expected = {constraint.name for constraint in ExchangeRate.__table__.constraints
                if constraint.__class__.__name__ == 'CheckConstraint'}
    actual = {constraint['name'] for constraint in inspect(engine).get_check_constraints('exchange_rates')}
    assert actual == expected


def test_concurrent_rate_inserts_preserve_winner_and_both_requests_succeed():
    schema = 'rates_test_' + uuid4().hex
    test_engine = engine.execution_options(schema_translate_map={None: schema})
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    barrier = Barrier(2)

    def synchronize_inserts(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith('INSERT INTO') and 'exchange_rates' in statement:
            barrier.wait(timeout=10)

    def insert_rate(value):
        with Session(test_engine) as session:
            inserted = store_rates(session, [{
                'currency': 'USD', 'rate_type': 'FX', 'rate_side': 'MARKET',
                'reference_date': date(2024, 1, 8), 'rate': Decimal(value),
                'source': value, 'retrieved_at': datetime.now(timezone.utc),
            }])
            session.commit()
            return inserted, value

    try:
        ExchangeRate.__table__.create(test_engine)
        event.listen(test_engine, 'before_cursor_execute', synchronize_inserts)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(insert_rate, ['4.90', '5.10']))
        assert sorted(count for count, _ in results) == [0, 1]
        winner = next(value for count, value in results if count == 1)
        with Session(test_engine) as session:
            stored = session.scalars(select(ExchangeRate)).all()
            assert len(stored) == 1
            assert stored[0].rate == Decimal(winner)
            assert stored[0].source == winner
    finally:
        event.remove(test_engine, 'before_cursor_execute', synchronize_inserts)
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
