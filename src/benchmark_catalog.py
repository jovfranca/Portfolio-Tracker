"""Validated, version-controlled benchmark catalog loader."""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from src.config import ROOT
from src.database import SessionLocal
from src.models import Benchmark, BenchmarkObservation, BenchmarkProviderMapping


CATALOG_PATH = ROOT / 'data' / 'benchmarks.csv'
COLUMNS = {'code', 'name', 'kind', 'frequency', 'value_type', 'unit',
           'reference_currency', 'jurisdiction', 'status', 'provider', 'series_id', 'is_primary'}


@dataclass(frozen=True)
class CatalogRow:
    code: str
    name: str
    kind: str
    frequency: str
    value_type: str
    unit: str
    reference_currency: str | None
    jurisdiction: str | None
    status: str
    provider: str
    series_id: str
    is_primary: bool

    @property
    def metadata(self):
        return (self.name, self.kind, self.frequency, self.value_type, self.unit,
                self.reference_currency, self.jurisdiction, self.status)


def read_catalog(path=CATALOG_PATH):
    rows = []
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if set(reader.fieldnames or ()) != COLUMNS:
            raise ValueError('Benchmark catalog columns do not match the required schema.')
        for line, raw in enumerate(reader, 2):
            try:
                row = CatalogRow(
                    code=raw['code'].strip().upper(), name=raw['name'].strip(),
                    kind=raw['kind'].strip().upper(), frequency=raw['frequency'].strip().upper(),
                    value_type=raw['value_type'].strip().upper(), unit=raw['unit'].strip().upper(),
                    reference_currency=raw['reference_currency'].strip().upper() or None,
                    jurisdiction=raw['jurisdiction'].strip().upper() or None,
                    status=raw['status'].strip().upper(), provider=raw['provider'].strip().lower(),
                    series_id=raw['series_id'].strip(),
                    is_primary={'true': True, 'false': False}[raw['is_primary'].strip().lower()],
                )
                if not all((row.code, row.name, row.unit, row.provider, row.series_id)):
                    raise ValueError('required metadata is empty')
                if row.kind not in {'INTEREST_RATE', 'INFLATION', 'OTHER'}:
                    raise ValueError('invalid kind')
                if row.frequency not in {'DAILY', 'MONTHLY', 'QUARTERLY', 'ANNUAL'}:
                    raise ValueError('invalid frequency')
                if row.value_type not in {'RATE', 'CHANGE', 'INDEX_LEVEL', 'VALUE'}:
                    raise ValueError('invalid value type')
                if row.status not in {'ACTIVE', 'INACTIVE'}:
                    raise ValueError('invalid status')
                if row.reference_currency and (len(row.reference_currency) != 3 or
                                               not row.reference_currency.isalpha()):
                    raise ValueError('invalid reference currency')
            except (AttributeError, KeyError, ValueError) as error:
                raise ValueError(f'Invalid benchmark catalog row {line}: {error}') from error
            rows.append(row)
    if not rows:
        raise ValueError('Benchmark catalog is empty.')
    metadata = {}
    owners = {}
    primary = {}
    for row in rows:
        if row.code in metadata and metadata[row.code] != row.metadata:
            raise ValueError(f'Conflicting metadata for benchmark {row.code}.')
        metadata[row.code] = row.metadata
        key = (row.provider, row.series_id)
        if key in owners:
            raise ValueError(f'Duplicate or conflicting provider mapping {key}.')
        owners[key] = row.code
        primary[row.code] = primary.get(row.code, 0) + row.is_primary
    if any(count != 1 for count in primary.values()):
        raise ValueError('Each benchmark requires exactly one primary provider mapping.')
    return rows


def seed_catalog(session, path=CATALOG_PATH):
    rows = read_catalog(path)
    with session.begin_nested():
        benchmarks = {}
        catalog_codes = {row.code for row in rows}
        for retired in session.scalars(select(Benchmark)):
            if retired.code not in catalog_codes:
                retired.status = 'INACTIVE'
                for mapping in retired.provider_mappings:
                    mapping.active = False
                    mapping.is_primary = False
        session.flush()
        for row in rows:
            benchmark = benchmarks.get(row.code)
            if benchmark is None:
                benchmark = session.scalar(select(Benchmark).where(Benchmark.code == row.code))
                if benchmark is None:
                    benchmark = Benchmark(code=row.code)
                    session.add(benchmark)
                elif ((benchmark.kind, benchmark.frequency, benchmark.value_type, benchmark.unit) !=
                      (row.kind, row.frequency, row.value_type, row.unit) and
                      session.scalar(select(BenchmarkObservation.id).where(
                          BenchmarkObservation.benchmark_id == benchmark.id).limit(1)) is not None):
                    raise ValueError(
                        f'Cannot change value semantics for {row.code} with historical observations.')
                (benchmark.name, benchmark.kind, benchmark.frequency, benchmark.value_type,
                 benchmark.unit, benchmark.reference_currency, benchmark.jurisdiction,
                 benchmark.status) = row.metadata
                session.flush()
                benchmarks[row.code] = benchmark
                for mapping in benchmark.provider_mappings:
                    mapping.active = False
                    mapping.is_primary = False
                session.flush()
            existing = session.scalar(select(BenchmarkProviderMapping).where(
                BenchmarkProviderMapping.provider == row.provider,
                BenchmarkProviderMapping.series_id == row.series_id))
            if existing is not None and existing.benchmark_id != benchmark.id:
                raise ValueError(f'Provider mapping {row.provider}:{row.series_id} belongs to another benchmark.')
            mapping = existing or BenchmarkProviderMapping(
                benchmark_id=benchmark.id, provider=row.provider, series_id=row.series_id)
            if existing is None:
                session.add(mapping)
            mapping.active = True
            mapping.is_primary = row.is_primary
        session.flush()
    return {'benchmarks': len(benchmarks), 'mappings': len(rows)}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Seed the benchmark catalog.')
    parser.add_argument('--catalog', type=Path, default=CATALOG_PATH)
    args = parser.parse_args(argv)
    with SessionLocal() as session:
        result = seed_catalog(session, args.catalog)
        session.commit()
    print(f"Catalog seeded: {result['benchmarks']} benchmarks, {result['mappings']} mappings.")


if __name__ == '__main__':
    main()
