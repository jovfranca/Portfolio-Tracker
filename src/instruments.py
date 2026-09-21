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
    """Resolve locally; transaction currency never disambiguates identity."""
    if instrument_id is not None:
        instrument = session.get(Instrument, instrument_id)
        if instrument is None:
            return InstrumentResolution('unresolved')
        return InstrumentResolution('resolved', instrument, (instrument,))

    normalized = normalize_identifier(raw_identifier)
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
    if len(candidates) == 1:
        return InstrumentResolution('resolved', candidates[0], candidates)
    return InstrumentResolution('ambiguous' if candidates else 'unresolved', candidates=candidates)


def provider_mapping(session, instrument, provider=None, currency=None, *, include_inactive=False):
    provider = provider or market_data_provider()
    query = select(ProviderInstrument).where(
        ProviderInstrument.instrument_id == instrument.id,
        ProviderInstrument.provider == provider,
    )
    if not include_inactive:
        query = query.where(ProviderInstrument.active.is_(True))
    if currency:
        query = query.where(ProviderInstrument.quote_currency == currency.upper())
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
    session, *, symbol, currency=None, name='', asset_type='OTHER', exchange=None,
    status='ACTIVE', isin=None, provider=None, provider_symbol=None,
    provider_exchange=None, quote_currency=None, aliases=(), alias_source='manual', instrument_id=None,
):
    """Persist a user-selected provider result or explicit manual instrument."""
    symbol = normalize_identifier(symbol)
    asset_type = asset_type.upper()
    currency = currency.upper() if currency else None
    quote_currency = quote_currency.upper() if quote_currency else None
    if provider_symbol and not quote_currency:
        raise ValueError('Provider quote currency must be explicitly confirmed.')
    if not symbol or (asset_type == 'CRYPTO' and '-' in symbol):
        raise ValueError('Confirm the canonical crypto base symbol, not a quote pair.')
    if asset_type in ('STOCK', 'ETF') and currency and quote_currency and currency != quote_currency:
        raise ValueError('Provider quote currency conflicts with native listing currency.')
    provider = provider or market_data_provider()
    instrument = session.get(Instrument, instrument_id) if instrument_id else None
    if instrument_id and instrument is None:
        raise ValueError('Unknown canonical instrument.')
    if provider_symbol:
        existing_mappings = list(session.scalars(select(ProviderInstrument).where(
            ProviderInstrument.provider == provider,
            ProviderInstrument.provider_symbol == provider_symbol.upper(),
        )))
        matching = [mapping for mapping in existing_mappings if mapping.quote_currency == quote_currency]
        if len(matching) > 1:
            raise ValueError('Ambiguous provider mapping; select a canonical instrument.')
        existing = matching[0] if matching else None
        if existing_mappings and existing is None:
            raise ValueError('Provider quote currency conflicts with existing mapping.')
        if existing:
            if instrument_id and existing.instrument_id != instrument_id:
                raise ValueError('Provider mapping already belongs to another instrument.')
            for alias in aliases:
                add_alias(session, existing.instrument, alias, alias_source)
            return existing.instrument
    # Explicitly confirmed crypto base symbols are independent of quote pairs.
    if instrument is None and asset_type == 'CRYPTO':
        candidates = list(session.scalars(select(Instrument).where(
            Instrument.symbol == symbol, Instrument.asset_type == 'CRYPTO',
        )))
        if len(candidates) > 1:
            raise ValueError('Ambiguous crypto identity; select a canonical instrument.')
        instrument = candidates[0] if candidates else None
    if instrument is None:
        instrument = Instrument(
            symbol=symbol, name=name.strip(), asset_type=asset_type.upper(),
            exchange=exchange, currency=(currency or quote_currency) if asset_type in ('STOCK', 'ETF') else None,
            status=status.upper(), isin=isin,
        )
        session.add(instrument)
        session.flush()
    elif instrument.asset_type != asset_type:
        raise ValueError('Selected canonical instrument has a different asset type.')
    elif instrument.asset_type in ('STOCK', 'ETF') and instrument.currency and quote_currency and quote_currency != instrument.currency:
        raise ValueError('Provider currency conflicts with native listing currency.')
    add_alias(session, instrument, symbol, alias_source)
    for alias in aliases:
        add_alias(session, instrument, alias, alias_source)
    if provider_symbol:
        session.add(ProviderInstrument(
            instrument_id=instrument.id,
            provider=provider or market_data_provider(),
            provider_symbol=provider_symbol.upper(), quote_currency=quote_currency,
            provider_exchange=provider_exchange, active=True,
        ))
        session.flush()
    return instrument


def search_instruments(session, query, category="ALL"):
    """Return local matches first, followed by non-persisted provider results."""
    normalized = normalize_identifier(query)
    local_query = select(Instrument).where(
        (func.upper(Instrument.symbol).contains(normalized, autoescape=True))
        | (func.upper(Instrument.name).contains(query.strip().upper(), autoescape=True))
        | Instrument.id.in_(select(InstrumentAlias.instrument_id).where(
            InstrumentAlias.normalized_alias.contains(normalized, autoescape=True)
        ))
        | Instrument.id.in_(select(ProviderInstrument.instrument_id).where(
            func.upper(ProviderInstrument.provider_symbol).contains(normalized, autoescape=True)
        ))
    )
    if category != 'ALL':
        local_query = local_query.where(Instrument.asset_type == category)
    local = list(session.scalars(local_query.order_by(Instrument.symbol).limit(20)))
    results = [{
        'instrument_id': item.id, 'symbol': item.symbol, 'name': item.name,
        'asset_type': item.asset_type, 'exchange': item.exchange,
        'currency': item.currency, 'status': item.status, 'provider': None,
        'provider_symbol': None,
        'quote_currencies': sorted({mapping.quote_currency for mapping in item.provider_mappings}),
    } for item in local]
    try:
        provider_results = market_data.search_instruments(query)
    except Exception:
        provider_results = []
    local_ids = {item['instrument_id'] for item in results}
    for item in provider_results:
        mappings = list(session.scalars(select(ProviderInstrument).where(
            ProviderInstrument.provider == item['provider'],
            ProviderInstrument.provider_symbol == item['provider_symbol'],
        )))
        if item.get('quote_currency'):
            mappings = [mapping for mapping in mappings if mapping.quote_currency == item['quote_currency']]
        mapping = mappings[0] if len(mappings) == 1 else None
        if mapping:
            if mapping.instrument_id in local_ids:
                continue
            canonical = mapping.instrument
            results.append(dict(instrument_id=canonical.id, symbol=canonical.symbol,
                name=canonical.name, asset_type=canonical.asset_type, exchange=canonical.exchange,
                currency=canonical.currency, status=canonical.status, provider=None, provider_symbol=None))
            local_ids.add(canonical.id)
        else:
            canonical_id = None
            if item['asset_type'] == 'CRYPTO' and item['symbol']:
                candidates = list(session.scalars(select(Instrument.id).where(
                    Instrument.symbol == item['symbol'], Instrument.asset_type == 'CRYPTO',
                )))
                if len(candidates) == 1:
                    canonical_id = candidates[0]
            results.append(item | {'instrument_id': canonical_id, 'status': 'ACTIVE'})
    return [item for item in results if category == 'ALL' or item['asset_type'] == category][:40]
