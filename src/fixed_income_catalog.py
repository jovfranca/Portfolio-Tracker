"""Version-controlled canonical fixed-income product templates."""
import csv
from pathlib import Path

from sqlalchemy import select

from src.config import ROOT
from src.models import FixedIncomeProduct, Instrument


CATALOG_PATH = ROOT / 'data' / 'fixed_income_products.csv'
FIELDS = {'symbol', 'name', 'default_currency', 'day_count_basis', 'compounding',
          'business_day_calendar', 'benchmark_lag_months'}


def read_products(path=CATALOG_PATH):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if set(reader.fieldnames or ()) != FIELDS:
            raise ValueError('Fixed-income product catalog columns do not match the required schema.')
        rows = list(reader)
    if not rows:
        raise ValueError('Fixed-income product catalog is empty.')
    symbols = set()
    for row in rows:
        symbol = row['symbol'] = row['symbol'].strip().upper()
        if not symbol or symbol in symbols or not row['name'].strip():
            raise ValueError(f'Duplicate or invalid fixed-income product: {symbol}.')
        symbols.add(symbol)
        if (len(row['default_currency'].strip()) != 3 or not row['default_currency'].strip().isalpha()
                or row['day_count_basis'] not in {'BUS_252', 'ACT_365', 'ACT_360'}
                or row['compounding'] not in {'SIMPLE', 'COMPOUND'}
                or row['business_day_calendar'] not in {'BR', 'NONE'}):
            raise ValueError(f'Invalid fixed-income defaults for {symbol}.')
        row['default_currency'] = row['default_currency'].strip().upper()
        try:
            lag = int(row['benchmark_lag_months'])
        except ValueError as error:
            raise ValueError(f'Invalid benchmark lag for {symbol}.') from error
        if not 0 <= lag <= 24:
            raise ValueError(f'Invalid benchmark lag for {symbol}.')
        row['benchmark_lag_months'] = lag
    return rows


def seed_products(session, path=CATALOG_PATH):
    rows = read_products(path)
    for row in rows:
        matches = list(session.scalars(select(Instrument).where(
            Instrument.symbol == row['symbol'], Instrument.origin == 'CATALOG')))
        if len(matches) > 1:
            raise ValueError(f'Ambiguous canonical fixed-income product: {row["symbol"]}.')
        instrument = matches[0] if matches else Instrument(symbol=row['symbol'], asset_type='FIXED_INCOME', origin='CATALOG')
        if instrument.asset_type not in ('OTHER', 'FIXED_INCOME'):
            raise ValueError(f'Conflicting canonical product: {row["symbol"]}.')
        session.add(instrument)
        instrument.name = row['name'].strip()
        instrument.asset_type = 'FIXED_INCOME'
        instrument.currency = None
        instrument.exchange = None
        instrument.status = 'ACTIVE'
        session.flush()
        product = session.get(FixedIncomeProduct, instrument.id)
        if product is None:
            product = FixedIncomeProduct(instrument_id=instrument.id)
            session.add(product)
        for field in FIELDS - {'symbol', 'name'}:
            setattr(product, field, row[field])
    session.flush()
    return len(rows)
