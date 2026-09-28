from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.benchmark_catalog import read_catalog, seed_catalog
from src.benchmarks import get_observation, get_history
from src.models import Benchmark, BenchmarkObservation, BenchmarkProviderMapping


@pytest.fixture
def session():
    engine = create_engine('sqlite://')
    for table in (Benchmark.__table__, BenchmarkProviderMapping.__table__,
                  BenchmarkObservation.__table__):
        table.create(engine)
    from src.models.benchmark import BenchmarkCoverage
    BenchmarkCoverage.__table__.create(engine)
    with Session(engine) as value:
        yield value


def test_observation_mapping_must_belong_to_its_benchmark():
    engine = create_engine('sqlite://')
    @event.listens_for(engine, 'connect')
    def enable_foreign_keys(dbapi_connection, _):
        dbapi_connection.execute('PRAGMA foreign_keys=ON')

    for table in (Benchmark.__table__, BenchmarkProviderMapping.__table__,
                  BenchmarkObservation.__table__):
        table.create(engine)
    with Session(engine) as session:
        first = Benchmark(code='FIRST', name='First', kind='INTEREST_RATE',
                          frequency='DAILY', value_type='RATE', unit='PERCENT_PER_DAY',
                          status='ACTIVE')
        second = Benchmark(code='SECOND', name='Second', kind='INTEREST_RATE',
                           frequency='DAILY', value_type='RATE', unit='PERCENT_PER_DAY',
                           status='ACTIVE')
        session.add_all([first, second])
        session.flush()
        mapping = BenchmarkProviderMapping(benchmark_id=first.id, provider='test',
                                           series_id='1', active=True, is_primary=True)
        session.add(mapping)
        session.flush()
        session.add(BenchmarkObservation(
            benchmark_id=second.id, provider_mapping_id=mapping.id,
            reference_date=date(2024, 1, 2), value=Decimal('1'), source='test',
            retrieved_at=datetime(2024, 1, 3, tzinfo=timezone.utc)))
        with pytest.raises(IntegrityError):
            session.flush()
    engine.dispose()


def test_catalog_is_idempotent_and_separates_identity_from_mapping(session):
    assert {row.code for row in read_catalog()} == {'CDI', 'IPCA'}
    seed_catalog(session)
    seed_catalog(session)
    assert session.scalar(select(func.count()).select_from(Benchmark)) == 2
    assert session.scalar(select(func.count()).select_from(BenchmarkProviderMapping)) == 2
    cdi = session.scalar(select(Benchmark).where(Benchmark.code == 'CDI'))
    assert cdi.reference_currency == 'BRL'
    assert cdi.provider_mappings[0].series_id == '12'


def test_catalog_retires_removed_mapping_without_deleting_observations(monkeypatch, session):
    from io import StringIO
    from pathlib import Path
    seed_catalog(session)
    cdi = session.scalar(select(Benchmark).where(Benchmark.code == 'CDI'))
    old = cdi.provider_mappings[0]
    session.add(BenchmarkObservation(
        benchmark_id=cdi.id, provider_mapping_id=old.id, reference_date=date(2024, 1, 2),
        value=Decimal('0.04'), source='bcb_sgs',
        retrieved_at=datetime(2024, 1, 3, tzinfo=timezone.utc)))
    session.flush()
    content = ('code,name,kind,frequency,value_type,unit,reference_currency,jurisdiction,status,provider,series_id,is_primary\n'
               'CDI,Taxa de juros - CDI,INTEREST_RATE,DAILY,RATE,PERCENT_PER_DAY,BRL,BR,ACTIVE,bcb_sgs,999,true\n')
    monkeypatch.setattr(Path, 'open', lambda *_args, **_kwargs: StringIO(content))
    seed_catalog(session)
    assert not old.active and not old.is_primary
    assert session.scalar(select(func.count()).select_from(BenchmarkObservation)) == 1
    assert get_observation(session, 'CDI', date(2024, 1, 2),
                           lambda *_: pytest.fail('historical observation fetched')).value == Decimal('0.04')


def test_catalog_retires_removed_benchmark_without_deleting_history(monkeypatch, session):
    from io import StringIO
    from pathlib import Path

    seed_catalog(session)
    cdi = session.scalar(select(Benchmark).where(Benchmark.code == 'CDI'))
    mapping = cdi.provider_mappings[0]
    session.add(BenchmarkObservation(
        benchmark_id=cdi.id, provider_mapping_id=mapping.id,
        reference_date=date(2024, 1, 2), value=Decimal('0.04'),
        source='bcb_sgs', retrieved_at=datetime(2024, 1, 3, tzinfo=timezone.utc)))
    session.flush()
    content = ('code,name,kind,frequency,value_type,unit,reference_currency,jurisdiction,status,provider,series_id,is_primary\n'
               'IPCA,IPCA,INFLATION,MONTHLY,CHANGE,PERCENT_PER_MONTH,BRL,BR,ACTIVE,bcb_sgs,433,true\n')
    monkeypatch.setattr(Path, 'open', lambda *_args, **_kwargs: StringIO(content))

    seed_catalog(session)

    assert cdi.status == 'INACTIVE'
    assert not mapping.active and not mapping.is_primary
    assert get_observation(session, 'CDI', date(2024, 1, 2),
                           lambda *_: pytest.fail('retired benchmark fetched')).value == Decimal('0.04')
    assert get_history(session, 'CDI', date(2024, 1, 3), date(2024, 1, 3),
                       lambda *_: pytest.fail('retired benchmark fetched')).missing_ranges == [
                           (date(2024, 1, 3), date(2024, 1, 3))]


def test_catalog_rejects_conflicting_or_duplicate_mapping(monkeypatch, session):
    from io import StringIO
    from pathlib import Path
    content = ('code,name,kind,frequency,value_type,unit,reference_currency,jurisdiction,status,provider,series_id,is_primary\n'
               'CDI,CDI,INTEREST_RATE,DAILY,RATE,PERCENT_PER_DAY,BRL,BR,ACTIVE,bcb_sgs,12,true\n'
               'OTHER,Other,OTHER,DAILY,RATE,PERCENT_PER_DAY,,,ACTIVE,bcb_sgs,12,true\n')
    monkeypatch.setattr(Path, 'open', lambda *_args, **_kwargs: StringIO(content))
    with pytest.raises(ValueError, match='mapping'):
        seed_catalog(session)
    assert session.scalar(select(func.count()).select_from(Benchmark)) == 0


def test_catalog_rejects_reinterpretation_of_stored_observations(monkeypatch, session):
    from io import StringIO
    from pathlib import Path

    seed_catalog(session)
    cdi = session.scalar(select(Benchmark).where(Benchmark.code == 'CDI'))
    session.add(BenchmarkObservation(
        benchmark_id=cdi.id, provider_mapping_id=cdi.provider_mappings[0].id,
        reference_date=date(2024, 1, 2), value=Decimal('0.04'),
        source='bcb_sgs', retrieved_at=datetime(2024, 1, 3, tzinfo=timezone.utc)))
    session.flush()
    content = ('code,name,kind,frequency,value_type,unit,reference_currency,jurisdiction,status,provider,series_id,is_primary\n'
               'CDI,CDI,INTEREST_RATE,DAILY,RATE,PERCENT_PER_MONTH,BRL,BR,ACTIVE,bcb_sgs,12,true\n')
    monkeypatch.setattr(Path, 'open', lambda *_args, **_kwargs: StringIO(content))

    with pytest.raises(ValueError, match='historical observations'):
        seed_catalog(session)
    assert cdi.unit == 'PERCENT_PER_DAY'


def test_local_first_backfills_only_uncovered_ranges(session):
    seed_catalog(session)
    calls = []
    stamp = datetime(2024, 1, 10, tzinfo=timezone.utc)

    def fetch(mapping, start, end):
        calls.append((mapping.series_id, start, end))
        return [{'reference_date': day, 'value': Decimal('0.04'),
                 'source': 'bcb_sgs', 'retrieved_at': stamp}
                for day in (date(2024, 1, 2), date(2024, 1, 3)) if start <= day <= end]

    first = get_history(session, 'CDI', date(2024, 1, 2), date(2024, 1, 2), fetch)
    second = get_history(session, 'CDI', date(2024, 1, 2), date(2024, 1, 3), fetch)
    assert [row.value for row in second.observations] == [Decimal('0.04')] * 2
    assert first.complete and second.complete
    assert calls == [('12', date(2024, 1, 2), date(2024, 1, 2)),
                     ('12', date(2024, 1, 3), date(2024, 1, 3))]
    assert get_observation(session, 'CDI', date(2024, 1, 2),
                           lambda *_: pytest.fail('cached date fetched')).value == Decimal('0.04')


def test_revised_observation_preserves_original(session):
    seed_catalog(session)
    from src.benchmarks import store_observations
    mapping = session.scalar(select(BenchmarkProviderMapping).where(
        BenchmarkProviderMapping.series_id == '433'))
    day = date(2024, 1, 1)
    earlier = datetime(2024, 2, 1, tzinfo=timezone.utc)
    later = datetime(2024, 3, 1, tzinfo=timezone.utc)
    store_observations(session, mapping, [dict(reference_date=day, value=Decimal('0.4'),
                                              source='bcb_sgs', retrieved_at=earlier)])
    store_observations(session, mapping, [dict(reference_date=day, value=Decimal('0.5'),
                                              source='bcb_sgs', retrieved_at=later)])
    assert session.scalar(select(func.count()).select_from(BenchmarkObservation)) == 2
    assert get_observation(session, 'IPCA', day,
                           lambda *_: pytest.fail('cached date fetched')).value == Decimal('0.5')


def test_monthly_lookup_uses_period_key_and_cached_value(session):
    seed_catalog(session)
    calls = []

    def fetch(mapping, start, end):
        calls.append((start, end))
        return [dict(reference_date=date(2024, 1, 1), value=Decimal('-0.08'),
                     source='bcb_sgs', retrieved_at=datetime(2024, 2, 10, tzinfo=timezone.utc))]

    assert get_observation(session, 'IPCA', date(2024, 1, 20), fetch).value == Decimal('-0.08')
    assert get_observation(session, 'IPCA', date(2024, 1, 31),
                           lambda *_: pytest.fail('monthly period fetched twice')).value == Decimal('-0.08')
    assert calls == [(date(2024, 1, 1), date(2024, 1, 1))]


def test_provider_failure_keeps_range_missing_and_does_not_store_coverage(session):
    seed_catalog(session)
    from src.models.benchmark import BenchmarkCoverage
    result = get_history(session, 'CDI', date(2024, 1, 2), date(2024, 1, 3),
                         lambda *_: (_ for _ in ()).throw(OSError('offline')))
    assert result.missing_ranges == [(date(2024, 1, 2), date(2024, 1, 3))]
    assert session.scalar(select(func.count()).select_from(BenchmarkCoverage)) == 0


def test_recent_unpublished_period_is_retried(session):
    seed_catalog(session)
    day = date.today() - timedelta(days=1)
    calls = []
    empty = lambda *_: calls.append(1) or []
    assert not get_history(session, 'CDI', day, day, empty).complete
    assert not get_history(session, 'CDI', day, day, empty).complete
    assert len(calls) == 2


def test_unknown_benchmark_cannot_be_created_by_lookup(session):
    with pytest.raises(ValueError, match='Unknown canonical benchmark'):
        get_observation(session, 'SOFR', date(2024, 1, 2))
    assert session.scalar(select(func.count()).select_from(Benchmark)) == 0


def test_bcb_adapter_parses_decimal_and_encoded_dates(monkeypatch, session):
    from io import BytesIO
    from src.api import market_data
    seed_catalog(session)
    mapping = session.scalar(select(BenchmarkProviderMapping).where(
        BenchmarkProviderMapping.series_id == '12'))
    requests = []

    def fake_open(request, timeout):
        requests.append((request.full_url, timeout))
        return BytesIO(b'[{"data":"02/01/2024","valor":"0.039123"}]')

    monkeypatch.setattr(market_data, 'urlopen', fake_open)
    result = market_data.fetch_benchmark_history(mapping, date(2024, 1, 2), date(2024, 1, 2))
    assert result[0]['value'] == Decimal('0.039123')
    assert result[0]['reference_date'] == date(2024, 1, 2)
    assert 'bcdata.sgs.12' in requests[0][0]
    assert 'dataInicial=02%2F01%2F2024' in requests[0][0]


def test_bcb_adapter_splits_long_backfill_windows(monkeypatch, session):
    from io import BytesIO
    from src.api import market_data
    seed_catalog(session)
    mapping = session.scalar(select(BenchmarkProviderMapping).where(
        BenchmarkProviderMapping.series_id == '12'))
    calls = []

    def fake_open(request, timeout):
        calls.append(request.full_url)
        return BytesIO(b'[]')

    monkeypatch.setattr(market_data, 'urlopen', fake_open)
    assert market_data.fetch_benchmark_history(mapping, date(2010, 1, 1), date(2024, 1, 1)) == []
    assert len(calls) == 2
