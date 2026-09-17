"""Resolution and persistence for shared and user-defined market prices."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select

from src.api import market_data
from src.config import market_data_provider, quote_ttl
from src.models import (
    Instrument, LatestMarketQuote, MarketPrice, MarketPriceCoverage, UserDefinedPrice,
)


@dataclass(frozen=True)
class ResolvedPrice:
    date: date
    close: Decimal
    currency: str
    source: str
    origin: str
    market_at: datetime | None
    retrieved_at: datetime | None
    dividends: Decimal = Decimal('0')
    stock_splits: Decimal = Decimal('0')


@dataclass(frozen=True)
class LatestPriceResult:
    price: ResolvedPrice | None
    stale: bool = False

    @property
    def available(self):
        return self.price is not None


@dataclass(frozen=True)
class HistoricalPriceResult:
    prices: list[ResolvedPrice]
    missing_ranges: list[tuple[date, date]]

    @property
    def complete(self):
        return not self.missing_ranges


def ensure_instrument(session, symbol, currency):
    symbol, currency = symbol.upper(), currency.upper()
    instrument = session.scalar(select(Instrument).where(
        Instrument.symbol == symbol, Instrument.currency == currency,
    ))
    if instrument is None:
        instrument = Instrument(symbol=symbol, currency=currency)
        session.add(instrument)
        session.flush()
    return instrument


def _utc(value):
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _daily_reference(day):
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def _reference_date(value):
    """Read the UTC daily key independently of the database session timezone."""
    return _utc(value).astimezone(timezone.utc).date()


def _local_date(value):
    return value.astimezone().date()


def _missing_ranges(start, end, coverage):
    """Return gaps after merging successful provider-query intervals."""
    intervals = sorted(
        (max(start, row.start_date), min(end, row.end_date))
        for row in coverage if row.end_date >= start and row.start_date <= end
    )
    gaps = []
    cursor = start
    for covered_start, covered_end in intervals:
        if covered_start > cursor:
            gaps.append((cursor, covered_start - timedelta(days=1)))
        cursor = max(cursor, covered_end + timedelta(days=1))
    if cursor <= end:
        gaps.append((cursor, end))
    return gaps


def _stored_history(session, asset, start=None, end=None):
    shared_query = select(MarketPrice).where(
        MarketPrice.instrument_id == asset.instrument_id,
        MarketPrice.interval == '1d',
    )
    manual_query = select(UserDefinedPrice).where(UserDefinedPrice.asset_id == asset.id)
    if start is not None:
        shared_query = shared_query.where(MarketPrice.reference_at >= _daily_reference(start))
        manual_query = manual_query.where(UserDefinedPrice.reference_date >= start)
    if end is not None:
        shared_query = shared_query.where(
            MarketPrice.reference_at < _daily_reference(end + timedelta(days=1))
        )
        manual_query = manual_query.where(UserDefinedPrice.reference_date <= end)

    by_date = {}
    for row in session.scalars(shared_query.order_by(
        MarketPrice.reference_at, MarketPrice.retrieved_at
    )):
        reference_date = _reference_date(row.reference_at)
        current = by_date.get(reference_date)
        if current is not None and row.source != market_data_provider():
            continue
        by_date[reference_date] = ResolvedPrice(
            reference_date, row.price, row.currency, row.source, 'shared',
            _utc(row.reference_at), _utc(row.retrieved_at),
            row.dividends, row.stock_splits,
        )
    for row in session.scalars(manual_query.order_by(UserDefinedPrice.reference_date)):
        by_date[row.reference_date] = ResolvedPrice(
            row.reference_date, row.price, row.currency, row.source, 'user-defined',
            None, _utc(row.retrieved_at), row.dividends, row.stock_splits,
        )
    return [by_date[day] for day in sorted(by_date)]


def get_stored_history(session, asset, start=None, end=None):
    """Resolve local daily history, with private values winning on the same date."""
    return _stored_history(session, asset, start, end)


def save_user_price(
    session, asset, reference_date, price, currency=None,
    dividends=Decimal('0'), stock_splits=Decimal('0'),
):
    currency = (currency or asset.instrument.currency).upper()
    if currency != asset.instrument.currency:
        raise ValueError(
            f'A cotação de {asset.ticker} deve usar {asset.instrument.currency}; '
            'conversão de moedas não é aplicada automaticamente.'
        )
    existing = session.scalar(select(UserDefinedPrice).where(
        UserDefinedPrice.asset_id == asset.id,
        UserDefinedPrice.reference_date == reference_date,
    ))
    now = datetime.now(timezone.utc)
    if existing is None:
        existing = UserDefinedPrice(
            asset_id=asset.id, reference_date=reference_date, price=price,
            currency=currency, source='manual', retrieved_at=now,
            dividends=dividends, stock_splits=stock_splits,
        )
        session.add(existing)
    else:
        existing.price = price
        existing.source = 'manual'
        existing.currency = currency
        existing.retrieved_at = now
        existing.dividends = dividends
        existing.stock_splits = stock_splits
    session.flush()
    return existing


def _store_market_prices(session, instrument, rows):
    inserted = 0
    for values in rows:
        reference_at = values.get('reference_at')
        if reference_at is None:
            reference_at = _daily_reference(values['date'])
        source = values.get('source', market_data_provider())
        existing = session.scalar(select(MarketPrice.id).where(
            MarketPrice.instrument_id == instrument.id,
            MarketPrice.interval == '1d',
            MarketPrice.reference_at == reference_at,
            MarketPrice.source == source,
        ))
        if existing is not None:
            continue
        session.add(MarketPrice(
            instrument_id=instrument.id,
            interval='1d',
            reference_at=reference_at,
            price=values.get('price', values.get('close')),
            open=values.get('open'), high=values.get('high'), low=values.get('low'),
            volume=values.get('volume'),
            dividends=values.get('dividends', 0),
            stock_splits=values.get('stock_splits', 0),
            currency=values.get('currency', instrument.currency),
            source=source,
            retrieved_at=values.get('retrieved_at', datetime.now(timezone.utc)),
        ))
        inserted += 1
    session.flush()
    return inserted


def _validate_provider_price(values, currency):
    price = Decimal(str(values.get('price', values.get('close'))))
    if not price.is_finite() or not 0 < price <= Decimal('1e15'):
        raise ValueError('Invalid provider price.')
    if values.get('currency') != currency:
        raise ValueError('Invalid provider currency.')


def get_history(session, asset, start, end, fetcher=None):
    """Return local history and fetch only provider ranges not queried before."""
    if end < start:
        raise ValueError('A data final deve ser igual ou posterior à data inicial.')
    if end >= date.today():
        raise ValueError('O histórico diário deve terminar antes da data atual.')
    source = market_data_provider()
    coverage = list(session.scalars(select(MarketPriceCoverage).where(
        MarketPriceCoverage.instrument_id == asset.instrument_id,
        MarketPriceCoverage.interval == '1d',
        MarketPriceCoverage.source == source,
    )))
    for row in session.scalars(select(MarketPrice).where(
        MarketPrice.instrument_id == asset.instrument_id,
        MarketPrice.interval == '1d', MarketPrice.source == source,
        MarketPrice.reference_at >= _daily_reference(start),
        MarketPrice.reference_at < _daily_reference(end + timedelta(days=1)),
    )):
        day = _reference_date(row.reference_at)
        coverage.append(SimpleNamespace(start_date=day, end_date=day))
    for day in session.scalars(select(UserDefinedPrice.reference_date).where(
        UserDefinedPrice.asset_id == asset.id,
        UserDefinedPrice.reference_date >= start,
        UserDefinedPrice.reference_date <= end,
    )):
        coverage.append(SimpleNamespace(start_date=day, end_date=day))
    gaps = _missing_ranges(start, end, coverage)
    fetcher = fetcher or market_data.fetch_history
    missing = []
    for gap_start, gap_end in gaps:
        try:
            rows = fetcher(asset.instrument.symbol, asset.instrument.currency, gap_start, gap_end)
            rows = list(rows)
            for values in rows:
                _validate_provider_price(values, asset.instrument.currency)
                day = values.get('date') or values['reference_at'].date()
                if not gap_start <= day <= gap_end:
                    raise ValueError('Provider date outside requested range.')
        except Exception:
            missing.append((gap_start, gap_end))
            continue
        _store_market_prices(session, asset.instrument, rows)
        session.add(MarketPriceCoverage(
            instrument_id=asset.instrument_id, interval='1d', source=source,
            start_date=gap_start, end_date=gap_end,
            retrieved_at=datetime.now(timezone.utc),
        ))
        session.flush()
    return HistoricalPriceResult(_stored_history(session, asset, start, end), missing)


def _as_resolved(row, origin='shared'):
    market_at = _utc(row.market_at)
    return ResolvedPrice(
        row.reference_date or (market_at or _utc(row.retrieved_at)).astimezone(timezone.utc).date(), row.price, row.currency,
        row.source, origin, market_at, _utc(row.retrieved_at),
    )


def get_latest(session, asset, fetcher=None, now=None):
    """Resolve latest manual/shared value and refresh a stale provider quote."""
    now = now or datetime.now(timezone.utc)
    local_date = _local_date(now)
    local = _stored_history(session, asset, end=local_date)
    if local and local[-1].date == local_date and local[-1].origin == 'user-defined':
        return LatestPriceResult(local[-1])
    source = market_data_provider()
    cached = session.scalar(select(LatestMarketQuote).where(
        LatestMarketQuote.instrument_id == asset.instrument_id,
        LatestMarketQuote.source == source,
    ))
    if cached is not None and cached.reference_date is not None and now - _utc(cached.retrieved_at) <= quote_ttl():
        provider_price = _as_resolved(cached)
    else:
        provider_price = _as_resolved(cached) if cached is not None else None
        fetcher = fetcher or market_data.fetch_latest
        try:
            values = fetcher(asset.instrument.symbol, asset.instrument.currency)
            _validate_provider_price(values, asset.instrument.currency)
        except Exception:
            candidates = local + ([provider_price] if provider_price else [])
            return LatestPriceResult(max(candidates, key=lambda row: row.date) if candidates else None, True)
        if cached is None:
            cached = LatestMarketQuote(instrument_id=asset.instrument_id, source=source)
            session.add(cached)
        cached.price = values['price']
        cached.currency = values.get('currency', asset.instrument.currency)
        cached.market_at = values.get('market_at')
        cached.retrieved_at = values.get('retrieved_at', now)
        # TIMESTAMPTZ retains the instant but discards the provider's timezone.
        cached.reference_date = (cached.market_at or _utc(cached.retrieved_at)).date()
        session.flush()
        provider_price = _as_resolved(cached)

    candidates = local + ([provider_price] if provider_price else [])
    if not candidates:
        return LatestPriceResult(None)
    # Manual values explicitly win ties with shared/provider-backed observations.
    return LatestPriceResult(max(candidates, key=lambda row: (row.date, row.origin == 'user-defined')))


def history_for_domain(session, asset):
    """Provide the small quote shape expected by the pure calculation layer."""
    prices = _stored_history(session, asset)
    cached = session.scalar(select(LatestMarketQuote).where(
        LatestMarketQuote.instrument_id == asset.instrument_id,
        LatestMarketQuote.source == market_data_provider(),
    ))
    if cached is not None:
        quote = _as_resolved(cached)
        by_date = {row.date: row for row in prices}
        current = by_date.get(quote.date)
        if current is None:
            by_date[quote.date] = quote
        prices = [by_date[day] for day in sorted(by_date)]
    return prices
