"""Canonical instrument resolution and provider mapping orchestration."""
from dataclasses import dataclass

from sqlalchemy import func, select

from src.api import market_data
from src.config import market_data_provider
from src.models import Instrument, InstrumentAlias, ProviderInstrument


def normalize_identifier(value):
    return ''.join(str(value).strip().upper().split())


@dataclass(frozen=True)
class InstrumentResolution:
    status: str
    instrument: Instrument | None = None
    candidates: tuple[Instrument, ...] = ()


def resolve_instrument(session, raw_identifier, *, currency=None, instrument_id=None):
    """Resolve locally without guessing or mutating persistence."""
    if instrument_id is not None:
        instrument = session.get(Instrument, instrument_id)
        if instrument is None:
            return InstrumentResolution('unresolved')
        return InstrumentResolution('resolved', instrument, (instrument,))

    normalized = normalize_identifier(raw_identifier)
    currency = currency.upper() if currency else None
    candidate_ids = set(session.scalars(select(InstrumentAlias.instrument_id).where(
        InstrumentAlias.normalized_alias == normalized,
    )))
    candidate_ids.update(session.scalars(select(Instrument.id).where(
        func.upper(Instrument.symbol) == normalized,
    )))
    candidate_ids.update(session.scalars(select(ProviderInstrument.instrument_id).where(
        func.upper(ProviderInstrument.provider_symbol) == normalized,
    )))
    if not candidate_ids:
        return InstrumentResolution('unresolved')
    candidates = tuple(session.scalars(
        select(Instrument).where(Instrument.id.in_(candidate_ids)).order_by(Instrument.id)
    ))
    if currency is not None and len(candidates) > 1:
        mapped_ids = select(ProviderInstrument.instrument_id).where(
            ProviderInstrument.currency == currency
        )
        preferred = tuple(session.scalars(select(Instrument).where(
            Instrument.id.in_(candidate_ids),
            (Instrument.currency == currency) | Instrument.id.in_(mapped_ids)
        ).order_by(Instrument.id)))
        if preferred:
            candidates = preferred
    if len(candidates) == 1:
        return InstrumentResolution('resolved', candidates[0], candidates)
    return InstrumentResolution('ambiguous' if candidates else 'unresolved', candidates=candidates)


def provider_mapping(session, instrument, provider=None, currency=None):
    provider = provider or market_data_provider()
    query = select(ProviderInstrument).where(
        ProviderInstrument.instrument_id == instrument.id,
        ProviderInstrument.provider == provider,
        ProviderInstrument.active.is_(True),
    )
    if currency:
        query = query.where(ProviderInstrument.currency == currency.upper())
    mappings = list(session.scalars(query.order_by(ProviderInstrument.id)))
    if len(mappings) != 1:
        status = 'unavailable' if not mappings else 'ambiguous'
        raise ValueError(f'Provider mapping is {status} for instrument {instrument.symbol}.')
    return mappings[0]


def add_alias(session, instrument, alias, source='manual'):
    normalized = normalize_identifier(alias)
    existing = session.scalar(select(InstrumentAlias).where(
        InstrumentAlias.instrument_id == instrument.id,
        InstrumentAlias.normalized_alias == normalized,
        InstrumentAlias.source == source,
    ))
    if existing is None:
        existing = InstrumentAlias(
            instrument_id=instrument.id, alias=str(alias).strip(),
            normalized_alias=normalized, source=source,
        )
        session.add(existing)
        session.flush()
    return existing


def create_instrument(
    session, *, symbol, currency, name='', asset_type='OTHER', exchange=None,
    status='ACTIVE', isin=None, provider=None, provider_symbol=None,
    provider_exchange=None, aliases=(), alias_source='manual',
):
    """Persist a user-selected provider result or explicit manual instrument."""
    symbol = normalize_identifier(symbol)
    currency = currency.upper()
    instrument = Instrument(
        symbol=symbol, name=name.strip(), asset_type=asset_type.upper(),
        exchange=exchange, currency=currency, status=status.upper(), isin=isin,
    )
    session.add(instrument)
    session.flush()
    add_alias(session, instrument, symbol, alias_source)
    for alias in aliases:
        add_alias(session, instrument, alias, alias_source)
    if provider_symbol:
        session.add(ProviderInstrument(
            instrument_id=instrument.id,
            provider=provider or market_data_provider(),
            provider_symbol=provider_symbol.upper(), currency=currency,
            provider_exchange=provider_exchange, active=True,
        ))
        session.flush()
    return instrument


def search_instruments(session, query):
    """Return local matches first, followed by non-persisted provider results."""
    normalized = normalize_identifier(query)
    local = list(session.scalars(select(Instrument).where(
        (func.upper(Instrument.symbol).contains(normalized, autoescape=True))
        | (func.upper(Instrument.name).contains(query.strip().upper(), autoescape=True))
        | Instrument.id.in_(select(InstrumentAlias.instrument_id).where(
            InstrumentAlias.normalized_alias.contains(normalized, autoescape=True)
        ))
        | Instrument.id.in_(select(ProviderInstrument.instrument_id).where(
            func.upper(ProviderInstrument.provider_symbol).contains(normalized, autoescape=True)
        ))
    ).order_by(Instrument.symbol).limit(20)))
    results = [{
        'instrument_id': item.id, 'symbol': item.symbol, 'name': item.name,
        'asset_type': item.asset_type, 'exchange': item.exchange,
        'currency': item.currency, 'status': item.status, 'provider': None,
        'provider_symbol': None,
    } for item in local]
    known = {(item['symbol'], item['currency'], item['provider_symbol']) for item in results}
    try:
        provider_results = market_data.search_instruments(query)
    except Exception:
        provider_results = []
    for item in provider_results:
        key = (item['symbol'], item['currency'], item['provider_symbol'])
        if key not in known:
            results.append(item | {'instrument_id': None, 'status': 'ACTIVE'})
            known.add(key)
    return results[:20]
