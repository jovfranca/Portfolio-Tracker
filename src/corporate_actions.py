"""Resolution, caching, and persistence for corporate actions."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import hashlib
from types import SimpleNamespace

from sqlalchemy import select

from src.api import market_data
from src.config import market_data_provider
from src.instruments import provider_mapping
from src.models import (
    CorporateAction, CorporateActionCoverage, MarketPrice, MarketPriceCoverage,
    UserCorporateEvent,
)


SPLIT_TYPES = {'STOCK_SPLIT', 'REVERSE_SPLIT'}
INCOME_TYPES = {'DIVIDEND', 'JCP', 'AMORTIZATION'}


@dataclass(frozen=True)
class ResolvedCorporateEvent:
    id: int
    event_type: str
    effective_date: date
    payment_date: date | None
    amount_per_unit: Decimal | None
    conversion_factor: Decimal | None
    currency: str | None
    source: str
    origin: str
    retrieved_at: datetime | None
    notes: str = ''


@dataclass(frozen=True)
class CorporateActionResult:
    actions: list[ResolvedCorporateEvent]
    missing_ranges: list[tuple[date, date]]

    @property
    def complete(self):
        return not self.missing_ranges


def _missing_ranges(start, end, coverage):
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


def _event_key(values):
    provider_id = values.get('provider_event_id')
    if values.get('source') == 'yfinance':
        # Yahoo's history has one aggregate dividend and split value per day.
        # Its event IDs and payment dates may change between retrievals, while
        # the original observation must remain the one applied to positions.
        kind = 'SPLIT' if values['event_type'] in SPLIT_TYPES else values['event_type']
        raw = f"daily:{kind}:{values['effective_date']}"
    elif provider_id:
        raw = f"provider:{provider_id}"
    else:
        fields = (
            values['event_type'], values['effective_date'], values.get('payment_date'),
        )
        raw = 'fallback:' + '|'.join('' if value is None else str(value) for value in fields)
    return hashlib.sha256(raw.encode()).hexdigest()


def actions_from_history_rows(rows):
    """Normalize provider price-response metadata into separate action values."""
    actions = []
    for row in rows:
        effective_date = row.get('date') or row['reference_at'].date()
        retrieved_at = row.get('retrieved_at', datetime.now(timezone.utc))
        source = row.get('source', market_data_provider())
        dividend = Decimal(str(row.get('dividends', 0)))
        if not dividend.is_finite() or dividend < 0:
            raise ValueError('Invalid provider dividend.')
        if dividend > 0:
            actions.append({
                'event_type': 'DIVIDEND', 'effective_date': effective_date,
                'payment_date': None, 'amount_per_unit': dividend,
                'conversion_factor': None, 'currency': row.get('currency'),
                'source': source, 'provider_event_id': row.get('dividend_event_id'),
                'retrieved_at': retrieved_at,
            })
        factor = Decimal(str(row.get('stock_splits', 0)))
        if not factor.is_finite() or factor < 0:
            raise ValueError('Invalid provider split factor.')
        if factor > 0 and factor != 1:
            actions.append({
                'event_type': 'STOCK_SPLIT' if factor > 1 else 'REVERSE_SPLIT',
                'effective_date': effective_date, 'payment_date': None,
                'amount_per_unit': None, 'conversion_factor': factor,
                'currency': None, 'source': source,
                'provider_event_id': row.get('split_event_id'),
                'retrieved_at': retrieved_at,
            })
    return actions


def store_provider_actions(session, instrument_id, values):
    """Insert new provider facts without rewriting an existing historical event."""
    inserted = 0
    for item in values:
        event_key = _event_key(item)
        exists = session.scalar(select(CorporateAction.id).where(
            CorporateAction.instrument_id == instrument_id,
            CorporateAction.source == item['source'],
            CorporateAction.event_key == event_key,
        ))
        if exists is not None:
            continue
        # An event first reported without a provider ID must not be applied
        # again when a later response supplies one (or vice versa).
        equivalent = select(CorporateAction.id).where(
            CorporateAction.instrument_id == instrument_id,
            CorporateAction.source == item['source'],
            CorporateAction.event_type.in_(
                SPLIT_TYPES if item['source'] == 'yfinance' and item['event_type'] in SPLIT_TYPES
                else {item['event_type']}
            ),
            CorporateAction.effective_date == item['effective_date'],
        )
        if item['source'] != 'yfinance':
            equivalent = equivalent.where(CorporateAction.payment_date == item.get('payment_date'))
            if item.get('provider_event_id'):
                equivalent = equivalent.where(CorporateAction.provider_event_id.is_(None))
        if session.scalar(equivalent) is not None:
            continue
        session.add(CorporateAction(
            instrument_id=instrument_id, event_key=event_key, **item,
        ))
        inserted += 1
    session.flush()
    return inserted


def record_coverage(session, instrument_id, source, start, end, retrieved_at=None):
    exists = session.scalar(select(CorporateActionCoverage.id).where(
        CorporateActionCoverage.instrument_id == instrument_id,
        CorporateActionCoverage.source == source,
        CorporateActionCoverage.start_date == start,
        CorporateActionCoverage.end_date == end,
    ))
    if exists is None:
        session.add(CorporateActionCoverage(
            instrument_id=instrument_id, source=source, start_date=start, end_date=end,
            retrieved_at=retrieved_at or datetime.now(timezone.utc),
        ))
        session.flush()


def store_actions_from_history(session, instrument_id, rows, start, end, source=None):
    rows = list(rows)
    source = source or market_data_provider()
    inserted = store_provider_actions(session, instrument_id, actions_from_history_rows(rows))
    record_coverage(session, instrument_id, source, start, end)
    return inserted


def _resolved_shared(row):
    return ResolvedCorporateEvent(
        row.id, row.event_type, row.effective_date, row.payment_date,
        row.amount_per_unit, row.conversion_factor, row.currency, row.source,
        'provider', row.retrieved_at,
    )


def _resolved_manual(row):
    return ResolvedCorporateEvent(
        row.id, row.event_type, row.effective_date, row.payment_date,
        row.amount_per_unit, row.conversion_factor, row.currency, row.source,
        'manual', row.updated_at, row.notes,
    )


def get_stored_actions(session, asset, start=None, end=None):
    shared = select(CorporateAction).where(CorporateAction.instrument_id == asset.instrument_id)
    manual = select(UserCorporateEvent).where(UserCorporateEvent.asset_id == asset.id)
    if start is not None:
        shared = shared.where(CorporateAction.effective_date >= start)
        manual = manual.where(UserCorporateEvent.effective_date >= start)
    if end is not None:
        shared = shared.where(CorporateAction.effective_date <= end)
        manual = manual.where(UserCorporateEvent.effective_date <= end)

    # A manual event is the portfolio owner's explicit resolution for an event
    # type/date and therefore replaces equivalent shared provider observations.
    manual_rows = list(session.scalars(manual.order_by(
        UserCorporateEvent.effective_date, UserCorporateEvent.event_type, UserCorporateEvent.id,
    )))
    overridden = {(
        'SPLIT' if row.event_type in SPLIT_TYPES else row.event_type,
        row.effective_date,
    ) for row in manual_rows}
    result = [
        _resolved_shared(row) for row in session.scalars(shared.order_by(
            CorporateAction.effective_date, CorporateAction.event_type, CorporateAction.id,
        ))
        if (
            'SPLIT' if row.event_type in SPLIT_TYPES else row.event_type,
            row.effective_date,
        ) not in overridden
    ]
    result.extend(_resolved_manual(row) for row in manual_rows)
    return sorted(result, key=lambda row: (
        row.effective_date, 0 if row.event_type in SPLIT_TYPES else 1,
        row.event_type, row.origin != 'manual', row.id,
    ))


def get_actions(session, asset, start, end, fetcher=None):
    """Return local actions and query only provider ranges not checked before."""
    if end < start:
        raise ValueError('A data final deve ser igual ou posterior à data inicial.')
    if end >= date.today():
        raise ValueError('O histórico de eventos deve terminar antes da data atual.')
    source = market_data_provider()
    try:
        mapping = provider_mapping(session, asset.instrument, provider=source)
    except ValueError:
        return CorporateActionResult(get_stored_actions(session, asset, start, end), [(start, end)])
    coverage = list(session.scalars(select(CorporateActionCoverage).where(
        CorporateActionCoverage.instrument_id == asset.instrument_id,
        CorporateActionCoverage.source == source,
    )))
    price_coverage = session.scalars(select(MarketPriceCoverage).where(
        MarketPriceCoverage.provider_instrument_id == mapping.id,
        MarketPriceCoverage.interval == '1d',
        MarketPriceCoverage.source == source,
        MarketPriceCoverage.end_date >= start,
        MarketPriceCoverage.start_date <= end,
    ).order_by(MarketPriceCoverage.start_date, MarketPriceCoverage.end_date))
    for checked in price_coverage:
        for gap_start, gap_end in _missing_ranges(start, end, coverage):
            cached_start = max(gap_start, checked.start_date)
            cached_end = min(gap_end, checked.end_date)
            if cached_start > cached_end:
                continue
            prices = list(session.scalars(select(MarketPrice).where(
                MarketPrice.provider_instrument_id == mapping.id,
                MarketPrice.interval == '1d',
                MarketPrice.reference_at >= datetime.combine(cached_start, time.min, timezone.utc),
                MarketPrice.reference_at < datetime.combine(
                    cached_end + timedelta(days=1), time.min, timezone.utc,
                ),
            )))
            rows = []
            for price in prices:
                reference_at = price.reference_at
                if reference_at.tzinfo is None:
                    reference_at = reference_at.replace(tzinfo=timezone.utc)
                if price.source != source or price.currency != mapping.quote_currency:
                    break
                rows.append({
                    'date': reference_at.astimezone(timezone.utc).date(),
                    'dividends': price.dividends, 'stock_splits': price.stock_splits,
                    'currency': price.currency, 'source': price.source,
                    'retrieved_at': price.retrieved_at,
                })
            else:
                try:
                    actions_from_history_rows(rows)
                except ValueError:
                    continue
                store_actions_from_history(
                    session, asset.instrument_id, rows, cached_start, cached_end, source,
                )
                coverage.append(SimpleNamespace(start_date=cached_start, end_date=cached_end))
    missing = []
    fetcher = fetcher or market_data.fetch_history
    for gap_start, gap_end in _missing_ranges(start, end, coverage):
        try:
            rows = list(fetcher(
                mapping.provider_symbol, mapping.quote_currency, gap_start, gap_end,
            ))
            for row in rows:
                if row.get('currency') != mapping.quote_currency:
                    raise ValueError('Invalid provider currency.')
                day = row.get('date') or row['reference_at'].date()
                if not gap_start <= day <= gap_end:
                    raise ValueError('Provider date outside requested range.')
            store_actions_from_history(
                session, asset.instrument_id, rows, gap_start, gap_end, source,
            )
        except Exception:
            missing.append((gap_start, gap_end))
    return CorporateActionResult(get_stored_actions(session, asset, start, end), missing)
