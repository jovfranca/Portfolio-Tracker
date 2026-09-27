"""Local-first shared benchmark history, independent of portfolio valuation."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from src.api.market_data import fetch_benchmark_history
from src.models import Benchmark, BenchmarkCoverage, BenchmarkObservation, BenchmarkProviderMapping


@dataclass(frozen=True)
class BenchmarkHistory:
    observations: list[BenchmarkObservation]
    missing_ranges: list[tuple[date, date]]

    @property
    def complete(self):
        return not self.missing_ranges


def _period_start(day, frequency):
    return day.replace(day=1) if frequency == 'MONTHLY' else day


def _next_period(day, frequency):
    if frequency == 'MONTHLY':
        return (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    return day + timedelta(days=1)


def _benchmark(session, code):
    benchmark = session.scalar(select(Benchmark).where(Benchmark.code == code.strip().upper()))
    if benchmark is None:
        raise ValueError(f'Unknown canonical benchmark: {code}. Run the benchmark catalog loader.')
    return benchmark


def _primary_mapping(session, benchmark):
    mappings = list(session.scalars(select(BenchmarkProviderMapping).where(
        BenchmarkProviderMapping.benchmark_id == benchmark.id,
        BenchmarkProviderMapping.is_primary.is_(True),
        BenchmarkProviderMapping.active.is_(True))))
    if len(mappings) != 1:
        raise ValueError(f'No unambiguous primary mapping for benchmark {benchmark.code}.')
    return mappings[0]


def _stored(session, benchmark, start, end):
    rows = session.scalars(select(BenchmarkObservation).where(
        BenchmarkObservation.benchmark_id == benchmark.id,
        BenchmarkObservation.reference_date >= start,
        BenchmarkObservation.reference_date <= end,
    ).order_by(BenchmarkObservation.reference_date, BenchmarkObservation.retrieved_at,
               BenchmarkObservation.id))
    latest = {}
    for row in rows:
        latest[row.reference_date] = row
    return latest


def _missing_periods(start, end, frequency, cached, coverage):
    missing = []
    cursor = start
    gap_start = gap_end = None
    while cursor <= end:
        covered = cursor in cached or any(row.start_date <= cursor <= row.end_date for row in coverage)
        if not covered:
            gap_start = cursor if gap_start is None else gap_start
            gap_end = cursor
        elif gap_start is not None:
            missing.append((gap_start, gap_end))
            gap_start = gap_end = None
        cursor = _next_period(cursor, frequency)
    if gap_start is not None:
        missing.append((gap_start, gap_end))
    return missing


def store_observations(session, mapping, rows):
    """Append revisions; identical fetched values do not create duplicate history."""
    inserted = 0
    with session.begin_nested():
        for row in rows:
            day = row['reference_date']
            if not isinstance(day, date) or isinstance(day, datetime):
                raise ValueError('Invalid benchmark reference date.')
            if day != _period_start(day, mapping.benchmark.frequency):
                raise ValueError('Benchmark date does not match its frequency.')
            try:
                value = Decimal(str(row['value']))
            except (InvalidOperation, TypeError):
                raise ValueError('Invalid benchmark value.') from None
            if not value.is_finite():
                raise ValueError('Invalid benchmark value.')
            source = row['source']
            stamp = row['retrieved_at']
            if source != mapping.provider or not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise ValueError('Invalid benchmark source or retrieval timestamp.')
            previous = session.scalar(select(BenchmarkObservation).where(
                BenchmarkObservation.provider_mapping_id == mapping.id,
                BenchmarkObservation.reference_date == day,
            ).order_by(BenchmarkObservation.retrieved_at.desc(), BenchmarkObservation.id.desc()))
            if previous is not None and previous.value == value:
                continue
            session.add(BenchmarkObservation(
                benchmark_id=mapping.benchmark_id, provider_mapping_id=mapping.id,
                reference_date=day, value=value, source=source, retrieved_at=stamp))
            session.flush()
            inserted += 1
    return inserted


def get_history(session, code, start, end, fetcher=None):
    benchmark = _benchmark(session, code)
    if benchmark.frequency not in {'DAILY', 'MONTHLY'}:
        raise ValueError(f'Range retrieval is not implemented for {benchmark.frequency}.')
    if start > end:
        raise ValueError('End date precedes start date.')
    if end >= (date.today() if benchmark.frequency == 'DAILY' else date.today().replace(day=1)):
        raise ValueError('Only completed benchmark periods can be retrieved.')
    start = _period_start(start, benchmark.frequency)
    end = _period_start(end, benchmark.frequency)
    cached = _stored(session, benchmark, start, end)
    try:
        mapping = _primary_mapping(session, benchmark) if benchmark.status == 'ACTIVE' else None
    except ValueError:
        mapping = None
    coverage = [] if mapping is None else list(session.scalars(select(BenchmarkCoverage).where(
        BenchmarkCoverage.provider_mapping_id == mapping.id,
        BenchmarkCoverage.end_date >= start, BenchmarkCoverage.start_date <= end)))
    missing = _missing_periods(start, end, benchmark.frequency, cached, coverage)

    if mapping is None:
        return BenchmarkHistory(list(cached.values()), missing)
    fetcher = fetcher or fetch_benchmark_history
    # Recent unpublished periods may later appear. Successful requests for
    # those periods are not final coverage unless an observation was returned.
    final_through = date.today() - timedelta(days=7 if benchmark.frequency == 'DAILY' else 60)
    final_through = _period_start(final_through, benchmark.frequency)
    for gap_start, gap_end in missing:
        try:
            rows = fetcher(mapping, gap_start, gap_end)
            if rows is None:
                raise ValueError('Provider returned no result.')
            for row in rows:
                if not gap_start <= row['reference_date'] <= gap_end:
                    raise ValueError('Provider returned a date outside the requested range.')
            with session.begin_nested():
                store_observations(session, mapping, rows)
                if gap_start <= final_through:
                    session.add(BenchmarkCoverage(
                        provider_mapping_id=mapping.id, start_date=gap_start,
                        end_date=min(gap_end, final_through),
                        retrieved_at=datetime.now(timezone.utc)))
                session.flush()
        except (OSError, ValueError):
            continue
    observations = _stored(session, benchmark, start, end)
    coverage = list(session.scalars(select(BenchmarkCoverage).where(
        BenchmarkCoverage.provider_mapping_id == mapping.id,
        BenchmarkCoverage.end_date >= start, BenchmarkCoverage.start_date <= end)))
    remaining = _missing_periods(start, end, benchmark.frequency, observations, coverage)
    return BenchmarkHistory(list(observations.values()), remaining)


def get_observation(session, code, reference_date, fetcher=None):
    benchmark = _benchmark(session, code)
    day = _period_start(reference_date, benchmark.frequency)
    cached = _stored(session, benchmark, day, day)
    if day in cached:
        return cached[day]
    result = get_history(session, code, day, day, fetcher)
    return result.observations[0] if result.observations else None
