"""Resolution and persistence for shared and user-defined market prices."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select

from src.api import market_data
from src.config import market_data_provider, quote_ttl
from src.instruments import provider_mapping
from src.models import (
    LatestMarketQuote, MarketPrice, MarketPriceCoverage, UserDefinedPrice,
    ProviderInstrument, Transaction,
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


def valuation_currency(session, asset):
    """Portfolio accounting currency; quote pairs never determine it."""
    currencies = set(session.scalars(select(Transaction.transaction_currency).where(
        Transaction.portfolio_id == asset.portfolio_id,
        Transaction.instrument_id == asset.instrument_id,
    ).distinct()))
    if currencies:
        if len(currencies) == 1:
            return next(iter(currencies))
        return asset.instrument.currency
    if asset.instrument.currency:
        return asset.instrument.currency
    manual_currencies = set(session.scalars(select(UserDefinedPrice.currency).where(
        UserDefinedPrice.asset_id == asset.id,
    ).distinct()))
    return next(iter(manual_currencies)) if len(manual_currencies) == 1 else None


def _stored_mapping(session, asset):
    """Use the primary mapping without consulting transaction currency."""
    try:
        return provider_mapping(session, asset.instrument)
    except ValueError:
        try:
            return provider_mapping(session, asset.instrument, include_inactive=True)
        except ValueError:
            return None


def _stored_history(session, asset, start=None, end=None, *, currency=None):
    target_currency = currency or valuation_currency(session, asset)
    mapping = _stored_mapping(session, asset)
    # Mapping activity controls network access, never ownership of stored history.
    shared_query = select(MarketPrice).join(ProviderInstrument).where(
        ProviderInstrument.instrument_id == asset.instrument_id,
        _stored_mapping_filter(mapping),
        ProviderInstrument.quote_currency == target_currency,
        MarketPrice.currency == target_currency,
        MarketPrice.interval == '1d',
    )
    manual_query = select(UserDefinedPrice).where(UserDefinedPrice.asset_id == asset.id)
    if target_currency is not None:
        manual_query = manual_query.where(UserDefinedPrice.currency == target_currency)
    if start is not None:
        shared_query = shared_query.where(MarketPrice.reference_at >= _daily_reference(start))
        manual_query = manual_query.where(UserDefinedPrice.reference_date >= start)
    if end is not None:
        shared_query = shared_query.where(
            MarketPrice.reference_at < _daily_reference(end + timedelta(days=1))
        )
        manual_query = manual_query.where(UserDefinedPrice.reference_date <= end)

    by_date = {}
    shared_rows = session.scalars(shared_query.order_by(
        MarketPrice.reference_at, ProviderInstrument.active, MarketPrice.retrieved_at
    ))
    for row in shared_rows:
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


def _stored_mapping_filter(mapping):
    # A replacement does not erase the instrument's earlier observations.
    # Still refuse ambiguous active mappings and never mix quote currencies.
    if mapping is None:
        return (ProviderInstrument.provider == market_data_provider()) & ProviderInstrument.active.is_(False)
    return (ProviderInstrument.provider == mapping.provider) & (
        (ProviderInstrument.id == mapping.id) | ProviderInstrument.active.is_(False)
    )


def get_stored_history(session, asset, start=None, end=None, *, currency=None):
    """Resolve local daily history, with private values winning on the same date."""
    return _stored_history(session, asset, start, end, currency=currency)


def get_quote_history(session, asset, start=None, end=None):
    """Expose quote currency for display, never as an accounting-price input."""
    accounting_prices = _stored_history(session, asset, start, end)
    mapping = _stored_mapping(session, asset)
    if mapping is None or mapping.quote_currency == valuation_currency(session, asset):
        return accounting_prices
    by_date = {row.date: row for row in accounting_prices}
    by_date.update({row.date: row for row in _stored_history(
        session, asset, start, end, currency=mapping.quote_currency,
    )})
    # Private accounting-currency overrides still win over provider quotes.
    by_date.update({row.date: row for row in accounting_prices if row.origin == 'user-defined'})
    return [by_date[day] for day in sorted(by_date)]


def save_user_price(
    session, asset, reference_date, price, currency=None,
    dividends=Decimal('0'), stock_splits=Decimal('0'),
):
    target = valuation_currency(session, asset)
    currency = (currency or target or '').upper()
    if not currency:
        raise ValueError('Select a transaction currency before entering a manual price.')
    if target and currency != target:
        raise ValueError(
            f'A cotação de {asset.ticker} deve usar {target}; '
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


def _store_market_prices(session, mapping, rows):
    inserted = 0
    for values in rows:
        reference_at = values.get('reference_at')
        if reference_at is None:
            reference_at = _daily_reference(values['date'])
        source = values.get('source', market_data_provider())
        existing = session.scalar(select(MarketPrice.id).where(
            MarketPrice.provider_instrument_id == mapping.id,
            MarketPrice.interval == '1d',
            MarketPrice.reference_at == reference_at,
        ))
        if existing is not None:
            continue
        session.add(MarketPrice(
            provider_instrument_id=mapping.id,
            interval='1d',
            reference_at=reference_at,
            price=values.get('price', values.get('close')),
            open=values.get('open'), high=values.get('high'), low=values.get('low'),
            volume=values.get('volume'),
            dividends=values.get('dividends', 0),
            stock_splits=values.get('stock_splits', 0),
            currency=values.get('currency', mapping.quote_currency),
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
    target_currency = valuation_currency(session, asset)
    if end < start:
        raise ValueError('A data final deve ser igual ou posterior à data inicial.')
    if end >= date.today():
        raise ValueError('O histórico diário deve terminar antes da data atual.')
    source = market_data_provider()
    try:
        mapping = provider_mapping(session, asset.instrument, provider=source)
    except ValueError:
        return HistoricalPriceResult(
            get_quote_history(session, asset, start, end), [(start, end)],
        )
    coverage = list(session.scalars(select(MarketPriceCoverage).where(
        MarketPriceCoverage.provider_instrument_id == mapping.id,
        MarketPriceCoverage.interval == '1d',
    )))
    for row in session.scalars(select(MarketPrice).where(
        MarketPrice.provider_instrument_id == mapping.id,
        MarketPrice.currency == mapping.quote_currency,
        MarketPrice.interval == '1d',
        MarketPrice.reference_at >= _daily_reference(start),
        MarketPrice.reference_at < _daily_reference(end + timedelta(days=1)),
    )):
        day = _reference_date(row.reference_at)
        coverage.append(SimpleNamespace(start_date=day, end_date=day))
    if target_currency == mapping.quote_currency:
        for day in session.scalars(select(UserDefinedPrice.reference_date).where(
            UserDefinedPrice.asset_id == asset.id,
            UserDefinedPrice.currency == target_currency,
            UserDefinedPrice.reference_date >= start,
            UserDefinedPrice.reference_date <= end,
        )):
            coverage.append(SimpleNamespace(start_date=day, end_date=day))
    gaps = _missing_ranges(start, end, coverage)
    fetcher = fetcher or market_data.fetch_history
    missing = []
    for gap_start, gap_end in gaps:
        try:
            rows = fetcher(mapping.provider_symbol, mapping.quote_currency, gap_start, gap_end)
            rows = list(rows)
            for values in rows:
                _validate_provider_price(values, mapping.quote_currency)
                day = values.get('date') or values['reference_at'].date()
                if not gap_start <= day <= gap_end:
                    raise ValueError('Provider date outside requested range.')
        except Exception:
            missing.append((gap_start, gap_end))
            continue
        _store_market_prices(session, mapping, rows)
        session.add(MarketPriceCoverage(
            provider_instrument_id=mapping.id, interval='1d', source=source,
            start_date=gap_start, end_date=gap_end,
            retrieved_at=datetime.now(timezone.utc),
        ))
        session.flush()
    return HistoricalPriceResult(get_quote_history(session, asset, start, end), missing)


def _as_resolved(row, origin='shared'):
    market_at = _utc(row.market_at)
    return ResolvedPrice(
        row.reference_date or (market_at or _utc(row.retrieved_at)).astimezone(timezone.utc).date(), row.price, row.currency,
        row.source, origin, market_at, _utc(row.retrieved_at),
    )


def get_latest(session, asset, fetcher=None, now=None):
    """Resolve latest manual/shared value and refresh a stale provider quote."""
    target_currency = valuation_currency(session, asset)
    now = now or datetime.now(timezone.utc)
    local_date = _local_date(now)
    local = _stored_history(session, asset, end=local_date)
    if local and local[-1].date == local_date and local[-1].origin == 'user-defined':
        return LatestPriceResult(local[-1])
    source = market_data_provider()
    try:
        mapping = provider_mapping(session, asset.instrument, provider=source)
    except ValueError:
        local = history_for_domain(session, asset)
        local = [row for row in local if row.date <= local_date]
        return LatestPriceResult(local[-1] if local else None, True)
    cached = session.scalar(select(LatestMarketQuote).where(
        LatestMarketQuote.provider_instrument_id == mapping.id,
        LatestMarketQuote.currency == mapping.quote_currency,
    ))
    if cached is not None and cached.reference_date is not None and now - _utc(cached.retrieved_at) <= quote_ttl():
        provider_price = _as_resolved(cached)
    else:
        provider_price = _as_resolved(cached) if cached is not None else None
        fetcher = fetcher or market_data.fetch_latest
        try:
            values = fetcher(mapping.provider_symbol, mapping.quote_currency)
            _validate_provider_price(values, mapping.quote_currency)
        except Exception:
            local = [row for row in history_for_domain(session, asset) if row.date <= local_date]
            candidates = local + ([provider_price] if provider_price else [])
            return LatestPriceResult(max(candidates, key=lambda row: row.date) if candidates else None, True)
        if cached is None:
            cached = LatestMarketQuote(provider_instrument_id=mapping.id, source=source)
            session.add(cached)
        cached.price = values['price']
        cached.currency = values.get('currency', mapping.quote_currency)
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


def history_for_domain(session, asset, *, currency=None):
    """Provide the small quote shape expected by the pure calculation layer."""
    target_currency = currency or valuation_currency(session, asset)
    mapping = _stored_mapping(session, asset)
    prices = _stored_history(session, asset, currency=target_currency)
    cached_quotes = session.scalars(select(LatestMarketQuote).join(ProviderInstrument).where(
        ProviderInstrument.instrument_id == asset.instrument_id,
        _stored_mapping_filter(mapping),
        ProviderInstrument.quote_currency == target_currency,
        LatestMarketQuote.currency == target_currency,
    ).order_by(ProviderInstrument.active.desc(), LatestMarketQuote.retrieved_at.desc()))
    for cached in cached_quotes:
        quote = _as_resolved(cached)
        by_date = {row.date: row for row in prices}
        current = by_date.get(quote.date)
        if current is None:
            by_date[quote.date] = quote
        prices = [by_date[day] for day in sorted(by_date)]
    return prices
