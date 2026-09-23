"""Deterministic loader for the version-controlled MVP instrument catalog."""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select

from src.config import ROOT
from src.database import SessionLocal
from src.instruments import add_alias, normalize_identifier
from src.models import Instrument, ProviderInstrument


CATALOG_PATH = ROOT / 'data' / 'instruments.csv'
ASSET_TYPES = {'STOCK', 'ETF', 'CRYPTO'}
STATUSES = {'ACTIVE', 'INACTIVE', 'DELISTED'}


@dataclass(frozen=True)
class CatalogRow:
    symbol: str
    name: str
    asset_type: str
    exchange: str | None
    currency: str | None
    status: str
    provider: str
    provider_symbol: str
    quote_currency: str
    is_primary: bool
    aliases: tuple[str, ...]

    @property
    def identity(self):
        return self.symbol, self.asset_type, self.exchange


def _optional(value):
    value = value.strip()
    return value or None


def read_catalog(path=CATALOG_PATH):
    rows = []
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        required = {
            'canonical_symbol', 'name', 'asset_type', 'exchange', 'native_currency',
            'status', 'provider', 'provider_symbol', 'quote_currency', 'is_primary', 'aliases',
        }
        if set(reader.fieldnames or ()) != required:
            raise ValueError('Catalog columns do not match the required schema.')
        for line, raw in enumerate(reader, 2):
            try:
                primary_text = raw['is_primary'].strip().lower()
                if primary_text not in {'true', 'false'}:
                    raise ValueError('is_primary must be true or false')
                row = CatalogRow(
                    symbol=normalize_identifier(raw['canonical_symbol']),
                    name=raw['name'].strip(),
                    asset_type=raw['asset_type'].strip().upper(),
                    exchange=_optional(raw['exchange']),
                    currency=_optional(raw['native_currency'].upper()),
                    status=raw['status'].strip().upper(),
                    provider=raw['provider'].strip().lower(),
                    provider_symbol=normalize_identifier(raw['provider_symbol']),
                    quote_currency=raw['quote_currency'].strip().upper(),
                    is_primary=primary_text == 'true',
                    aliases=tuple(
                        alias.strip() for alias in raw['aliases'].split('|') if alias.strip()
                    ),
                )
                if not row.symbol or not row.name or row.asset_type not in ASSET_TYPES:
                    raise ValueError('invalid canonical metadata')
                if row.status not in STATUSES or not row.provider or not row.provider_symbol:
                    raise ValueError('invalid status or provider mapping')
                if len(row.quote_currency) != 3 or not row.quote_currency.isalpha():
                    raise ValueError('invalid quote currency')
                if row.currency and (len(row.currency) != 3 or not row.currency.isalpha()):
                    raise ValueError('invalid native currency')
                if row.asset_type in {'STOCK', 'ETF'} and not row.currency:
                    raise ValueError('listed instruments require native_currency')
                if row.asset_type == 'CRYPTO' and row.currency:
                    raise ValueError('crypto canonical identity must not have native_currency')
            except (AttributeError, ValueError) as error:
                raise ValueError(f'Invalid catalog row {line}: {error}') from error
            rows.append(row)
    _validate(rows)
    return rows


def _validate(rows):
    metadata = {}
    mapping_owners = {}
    primary_counts = {}
    provider_scopes = set()
    for row in rows:
        canonical = (row.name, row.asset_type, row.exchange, row.currency, row.status)
        if row.identity in metadata and metadata[row.identity] != canonical:
            raise ValueError(f'Conflicting canonical metadata for {row.identity}.')
        metadata[row.identity] = canonical
        mapping_key = (row.provider, row.provider_symbol)
        owner = mapping_owners.setdefault(mapping_key, (row.identity, row.quote_currency))
        if owner != (row.identity, row.quote_currency):
            raise ValueError(f'Provider mapping {mapping_key} has conflicting owners.')
        scope = (row.identity, row.provider)
        provider_scopes.add(scope)
        primary_counts[scope] = primary_counts.get(scope, 0) + int(row.is_primary)
    invalid = [scope for scope in provider_scopes if primary_counts.get(scope) != 1]
    if invalid:
        raise ValueError(f'Each catalog instrument/provider requires exactly one primary mapping: {invalid}.')


def _instrument_for_row(session, row):
    catalog = list(session.scalars(select(Instrument).where(
        Instrument.origin == 'CATALOG',
        func.upper(Instrument.symbol) == row.symbol,
        Instrument.asset_type == row.asset_type,
        Instrument.exchange == row.exchange,
    )))
    if len(catalog) > 1:
        raise ValueError(f'Ambiguous catalog identity for {row.symbol}.')
    if catalog:
        return catalog[0]

    legacy = list(session.scalars(select(Instrument).where(
        Instrument.origin == 'MIGRATED',
        func.upper(Instrument.symbol) == row.symbol,
    )))
    if len(legacy) > 1:
        # Before canonical identities, the same ticker could be duplicated by
        # transaction currency. Adopt only the unique row matching the trusted
        # native/listing currency; keep every other history-bearing row intact.
        native_currency_matches = [
            instrument for instrument in legacy if instrument.currency == row.currency
        ]
        if len(native_currency_matches) != 1:
            raise ValueError(f'Ambiguous migrated identity for {row.symbol}.')
        legacy = native_currency_matches
    if legacy:
        instrument = legacy[0]
        # Before 0008, Instrument.currency was copied from transaction currency.
        # Only untouched migration placeholders lack authoritative listing data.
        placeholder = (
            instrument.asset_type == 'OTHER' and not instrument.name
            and not instrument.exchange
            and {alias.source for alias in instrument.aliases} == {'migration'}
        )
        # Crypto base identity is not a listing on the provider's market (e.g.
        # Yahoo's CCC). Keep that label on the matching provider mapping only.
        provider_market_label = (
            instrument.asset_type == row.asset_type == 'CRYPTO'
            and row.exchange is None
            and any(
                mapping.provider == row.provider
                and mapping.provider_symbol == row.provider_symbol
                and mapping.quote_currency == row.quote_currency
                and mapping.provider_exchange == instrument.exchange
                for mapping in instrument.provider_mappings
            )
        )
        if (
            instrument.asset_type not in {'OTHER', row.asset_type}
            or (instrument.exchange and instrument.exchange != row.exchange and not provider_market_label)
            or (instrument.currency and row.currency and instrument.currency != row.currency and not placeholder)
        ):
            raise ValueError(f'Conflicting migrated identity for {row.symbol}; review it explicitly.')
        return instrument

    instrument = Instrument(symbol=row.symbol, origin='CATALOG')
    session.add(instrument)
    session.flush()
    return instrument


def seed_catalog(session, path=CATALOG_PATH):
    """Upsert trusted catalog rows atomically; ownership conflicts raise."""
    rows = read_catalog(path)
    with session.begin_nested():
        return _seed_rows(session, rows)


def _seed_rows(session, rows):
    instruments = {}
    for row in rows:
        instrument = instruments.get(row.identity)
        if instrument is None:
            instrument = _instrument_for_row(session, row)
            instruments[row.identity] = instrument
            instrument.symbol = row.symbol
            instrument.name = row.name
            instrument.asset_type = row.asset_type
            instrument.exchange = row.exchange
            instrument.currency = row.currency
            instrument.status = row.status
            instrument.origin = 'CATALOG'
            add_alias(session, instrument, row.symbol, 'catalog')
        for alias in row.aliases:
            add_alias(session, instrument, alias, 'catalog')

    # The CSV is authoritative for primary selection in each listed scope.
    for row in rows:
        instrument = instruments[row.identity]
        for mapping in session.scalars(select(ProviderInstrument).where(
            ProviderInstrument.instrument_id == instrument.id,
            ProviderInstrument.provider == row.provider,
        )):
            mapping.is_primary = False
            mapping.active = False
    session.flush()

    for row in rows:
        instrument = instruments[row.identity]
        mappings = list(session.scalars(select(ProviderInstrument).where(
            ProviderInstrument.provider == row.provider,
            ProviderInstrument.provider_symbol == row.provider_symbol,
        )))
        for existing in mappings:
            if existing.instrument_id != instrument.id:
                raise ValueError(
                    f'{row.provider}:{row.provider_symbol} already belongs '
                    f'to instrument {existing.instrument_id}; catalog requires {instrument.id}.'
                )
            if existing.quote_currency != row.quote_currency:
                raise ValueError(f'Conflicting quote currency for {row.provider}:{row.provider_symbol}.')
        mapping = mappings[0] if mappings else None
        if mapping is None:
            mapping = ProviderInstrument(
                instrument_id=instrument.id,
                provider=row.provider,
                provider_symbol=row.provider_symbol,
                quote_currency=row.quote_currency,
            )
            session.add(mapping)
        mapping.active = True
        mapping.is_primary = row.is_primary
    session.flush()
    return {'instruments': len(instruments), 'mappings': len(rows)}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Seed the trusted MVP instrument catalog.')
    parser.add_argument('--catalog', type=Path, default=CATALOG_PATH)
    args = parser.parse_args(argv)
    with SessionLocal() as session:
        result = seed_catalog(session, args.catalog)
        session.commit()
    print(f"Catalog seeded: {result['instruments']} instruments, {result['mappings']} mappings.")


if __name__ == '__main__':
    main()
