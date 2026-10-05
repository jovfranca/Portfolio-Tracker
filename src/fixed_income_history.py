"""Explicit canonical lot consolidation and read-only currency projection."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import delete, select

from src.domain import ZERO, fixed_income_valuation, portfolio_day
from src.models import FixedIncomeInvalidation, FixedIncomeSnapshot, PositionInvalidation
from src.rates import RateUnavailable, convert_amount


def mark_lot_dirty(session, lot, day):
    from src.consolidation import mark_dirty
    portfolio_id = lot.asset.portfolio_id
    instrument_id = lot.asset.instrument_id
    row = next((row for row in session.new if isinstance(row, FixedIncomeInvalidation)
                and row.portfolio_id == portfolio_id and row.lot_id == lot.id), None)
    if row is None:
        row = session.scalar(select(FixedIncomeInvalidation).where(
            FixedIncomeInvalidation.portfolio_id == portfolio_id,
            FixedIncomeInvalidation.lot_id == lot.id))
    if row is None:
        session.add(FixedIncomeInvalidation(portfolio_id=portfolio_id,
            instrument_id=instrument_id, lot_id=lot.id, dirty_from=day))
    else:
        row.dirty_from = min(row.dirty_from, day)
    mark_dirty(session, portfolio_id, day, instrument_id, 'fixed_income')


def consolidate_lots(session, portfolio_id, lots, through):
    """Replay only dirty/extended lots, resuming from a valid preceding checkpoint."""
    from src.benchmarks import get_history, stored_observations
    dirty = {row.lot_id: row for row in session.scalars(select(FixedIncomeInvalidation).where(
        FixedIncomeInvalidation.portfolio_id == portfolio_id))}
    live_ids = {lot.id for lot in lots}
    for lot_id in dirty.keys() - live_ids:
        session.execute(delete(FixedIncomeSnapshot).where(
            FixedIncomeSnapshot.portfolio_id == portfolio_id,
            FixedIncomeSnapshot.lot_id == lot_id))
        session.delete(dirty[lot_id])
    for lot in lots:
        latest = session.scalar(select(FixedIncomeSnapshot).where(
            FixedIncomeSnapshot.portfolio_id == portfolio_id,
            FixedIncomeSnapshot.lot_id == lot.id).order_by(FixedIncomeSnapshot.date.desc()).limit(1))
        gap = session.scalar(select(FixedIncomeSnapshot.date).where(
            FixedIncomeSnapshot.portfolio_id == portfolio_id,
            FixedIncomeSnapshot.lot_id == lot.id,
            FixedIncomeSnapshot.status != 'complete').order_by(FixedIncomeSnapshot.date).limit(1))
        start = latest.date + timedelta(days=1) if latest else lot.start_date
        if lot.id in dirty:
            start = min(start, dirty[lot.id].dirty_from)
        if gap:
            start = min(start, gap)
        if start > through:
            continue
        replace_from = start
        previous = session.scalar(select(FixedIncomeSnapshot).where(
            FixedIncomeSnapshot.portfolio_id == portfolio_id,
            FixedIncomeSnapshot.lot_id == lot.id,
            FixedIncomeSnapshot.date < start,
            FixedIncomeSnapshot.status == 'complete',
            FixedIncomeSnapshot.accounting_currency == lot.currency,
        ).order_by(FixedIncomeSnapshot.date.desc()).limit(1))
        if previous:
            start = previous.date + timedelta(days=1)
        else:
            start = lot.start_date
        observations = []
        if lot.benchmark is not None:
            if lot.yield_structure == 'BENCHMARK_SPREAD':
                first_month = start.year * 12 + start.month - 2 - lot.benchmark_lag_months
                last_month = through.year * 12 + through.month - 2 - lot.benchmark_lag_months
                first = date(first_month // 12, first_month % 12 + 1, 1)
                last = date(last_month // 12, last_month % 12 + 1, 1)
            else:
                first, last = max(lot.start_date, start - timedelta(days=1)), through - timedelta(days=1)
            if first <= last:
                get_history(session, lot.benchmark.code, first, last)
                session.flush()
                # Newly fetched observations invalidate themselves; this replay
                # already includes the requested suffix.
                observations = stored_observations(session, lot.benchmark, first, last)
        session.execute(delete(FixedIncomeSnapshot).where(
            FixedIncomeSnapshot.portfolio_id == portfolio_id,
            FixedIncomeSnapshot.lot_id == lot.id,
            FixedIncomeSnapshot.date >= min(replace_from, start)))
        metadata = {'id': lot.id, 'asset_id': lot.asset_id,
                    'instrument_id': lot.asset.instrument_id, 'asset': lot.asset.instrument.symbol,
                    'broker': lot.broker.name, 'issuer': lot.issuer,
                    'start_date': lot.start_date.isoformat()}
        state = previous.ledger_state if previous else None
        movements = list(lot.movements)
        day = start
        while day <= through:
            valued = fixed_income_valuation(lot, movements, day, observations, initial_state=state)
            flow = purchases = ZERO
            for row in movements:
                if row.effective_date == day:
                    if row.movement_type in {'INITIAL_INVESTMENT', 'ADDITIONAL_INVESTMENT'}:
                        flow += row.amount
                        purchases += row.amount
                    else:
                        flow -= row.amount
            next_state = valued.pop('ledger_state', None)
            if next_state is not None:
                state = next_state
            session.add(FixedIncomeSnapshot(portfolio_id=portfolio_id,
                instrument_id=lot.asset.instrument_id, lot_id=lot.id, date=day,
                accounting_currency=lot.currency, status=valued['status'],
                valuation={key: value.isoformat() if isinstance(value, date) else
                           str(value) if isinstance(value, Decimal) else value
                           for key, value in valued.items()},
                ledger_state=next_state, lot_metadata=metadata, net_flow=flow, purchases=purchases))
            day += timedelta(days=1)
        if lot.id in dirty:
            session.delete(dirty[lot.id])
        else:
            # Fetching a new benchmark period can create an invalidation during
            # this replay. Consume it when the rebuilt suffix covers its boundary.
            fetched_dirty = session.scalar(select(FixedIncomeInvalidation).where(
                FixedIncomeInvalidation.portfolio_id == portfolio_id,
                FixedIncomeInvalidation.lot_id == lot.id))
            if fetched_dirty is not None and start <= fetched_dirty.dirty_from <= through:
                session.delete(fetched_dirty)
    session.flush()


def snapshot_value(session, snapshot, display_currency, valuation_date, *, pending=False,
                   factors=None):
    value = dict(snapshot.valuation)
    for key in ('original_invested_amount', 'outstanding_principal', 'gross_accrued_value',
                'accrued_gain', 'realized_gain'):
        value[key] = Decimal(value[key]) if value[key] is not None else None
    value.update(display_currency=display_currency, pending=pending, unbuilt=False,
                 consolidated_through=snapshot.date)
    for source, target in (('gross_accrued_value', 'display_value'),
                           ('outstanding_principal', 'display_principal'),
                           ('accrued_gain', 'display_accrued_gain'),
                           ('realized_gain', 'display_realized_gain')):
        value[target] = None
        if value[source] is not None:
            if factors is not None:
                factor = factors.get((snapshot.accounting_currency, valuation_date))
                if factor is None:
                    value['status'] = 'missing_fx'
                else:
                    value[target] = value[source] * factor
            else:
                try:
                    value[target] = convert_amount(session, value[source], snapshot.accounting_currency,
                        display_currency, valuation_date, fetcher=lambda *_: [])
                except (RateUnavailable, ValueError):
                    value['status'] = 'missing_fx'
    return value


def unbuilt_value(lot, display_currency, valuation_date):
    return {'currency': lot.currency, 'valuation_date': valuation_date,
            'maturity_date': lot.maturity_date,
            'status': 'before_start' if valuation_date < lot.start_date else 'pending', 'pending': True,
            'unbuilt': True, 'consolidated_through': None,
            'display_currency': display_currency,
            **{key: None for key in ('original_invested_amount', 'outstanding_principal',
                'gross_accrued_value', 'accrued_gain', 'realized_gain', 'benchmark_start',
                'benchmark_end', 'display_value', 'display_principal', 'display_accrued_gain',
                'display_realized_gain')}}


def saved_lot_value(session, lot, valuation_date, display_currency):
    snapshot = session.scalar(select(FixedIncomeSnapshot).where(
        FixedIncomeSnapshot.portfolio_id == lot.asset.portfolio_id,
        FixedIncomeSnapshot.lot_id == lot.id,
        FixedIncomeSnapshot.date <= valuation_date).order_by(FixedIncomeSnapshot.date.desc()).limit(1))
    if snapshot is None:
        return unbuilt_value(lot, display_currency, valuation_date)
    dirty = session.scalar(select(FixedIncomeInvalidation.dirty_from).where(
        FixedIncomeInvalidation.portfolio_id == lot.asset.portfolio_id,
        FixedIncomeInvalidation.lot_id == lot.id))
    return snapshot_value(session, snapshot, display_currency, valuation_date,
                          pending=dirty is not None or snapshot.date < valuation_date)


def saved_position_valuations(session, portfolio_id, lots, valuation_date, display_currency):
    snapshots = list(session.scalars(select(FixedIncomeSnapshot).where(
        FixedIncomeSnapshot.portfolio_id == portfolio_id,
        FixedIncomeSnapshot.date <= valuation_date).order_by(FixedIncomeSnapshot.date)))
    latest = {row.lot_id: row for row in snapshots}
    dirty_ids = set(session.scalars(select(FixedIncomeInvalidation.lot_id).where(
        FixedIncomeInvalidation.portfolio_id == portfolio_id)))
    grouped = defaultdict(list)
    for row in latest.values():
        value = snapshot_value(session, row, display_currency, valuation_date,
                               pending=row.lot_id in dirty_ids or row.date < valuation_date)
        grouped[row.instrument_id].append({**row.lot_metadata, **value})
    for lot in lots:
        if lot.id not in latest and lot.start_date <= valuation_date:
            grouped[lot.asset.instrument_id].append({
                'id': lot.id, 'asset_id': lot.asset_id, 'instrument_id': lot.asset.instrument_id,
                'asset': lot.asset.instrument.symbol, 'broker': lot.broker.name,
                **unbuilt_value(lot, display_currency, valuation_date)})
    positions = []
    for entries in grouped.values():
        complete = all(value['status'] == 'complete' for value in entries)
        pending = any(value['pending'] for value in entries)
        currencies = {value['currency'] for value in entries}
        def total(field):
            return sum((value[field] for value in entries), ZERO) if complete else None
        positions.append({
            'asset_id': entries[0]['asset_id'], 'instrument_id': entries[0]['instrument_id'],
            'asset': entries[0]['asset'], 'currency': next(iter(currencies)) if len(currencies) == 1 else None,
            'display_currency': display_currency, 'valuation_date': valuation_date,
            'status': 'pending' if pending else 'complete' if complete else 'incomplete',
            'valuation_status': 'complete' if complete else 'incomplete', 'lots': entries,
            'acquisition_cost': total('display_principal'), 'display_value': total('display_value'),
            'realized_gain': total('display_realized_gain'), 'unrealized_gain': total('display_accrued_gain'),
            'gross_income': ZERO if complete else None,
            'current_total_gain': total('display_realized_gain') + total('display_accrued_gain') if complete else None,
            'broker_breakdown': [{'broker': value['broker'], 'lot_id': value['id'],
                'acquisition_cost': value['display_principal'], 'display_value': value['display_value'],
                'valuation_status': value['status']} for value in entries],
        })
    return positions


def saved_position_series(session, portfolio_id, instrument_id, display_currency, through):
    from src.fixed_income import list_lots
    from src.position_reporting import historical_valuation_factors
    rows = list(session.scalars(select(FixedIncomeSnapshot).where(
        FixedIncomeSnapshot.portfolio_id == portfolio_id,
        FixedIncomeSnapshot.instrument_id == instrument_id,
        FixedIncomeSnapshot.date <= through).order_by(FixedIncomeSnapshot.date))) if through else []
    dirty = session.scalar(select(PositionInvalidation.dirty_from).where(
        PositionInvalidation.portfolio_id == portfolio_id,
        PositionInvalidation.instrument_id == instrument_id))
    factors = historical_valuation_factors(session, {row.accounting_currency for row in rows},
                                           display_currency, [row.date for row in rows])
    by_day = defaultdict(list)
    saved_ids = {row.lot_id for row in rows}
    unbuilt_lots = [lot for lot in list_lots(session, portfolio_id)
                    if lot.asset.instrument_id == instrument_id and lot.id not in saved_ids]
    for lot in unbuilt_lots:
        day = lot.start_date
        while through is not None and day <= through:
            by_day[day].append(SimpleNamespace(status='pending',
                **{field: None for field in ('remaining_acquisition_cost', 'market_value',
                    'realized_gain', 'unrealized_gain', 'gross_income', 'total_gain',
                    'net_flow', 'purchases', 'daily_income')}))
            day += timedelta(days=1)
    for row in rows:
        value = snapshot_value(session, row, display_currency, row.date, factors=factors)
        factor = factors.get((row.accounting_currency, row.date))
        flow = row.net_flow * factor if factor is not None else None
        purchases = row.purchases * factor if factor is not None else None
        if factor is None:
            value['status'] = 'missing_fx'
        by_day[row.date].append(SimpleNamespace(
            status=value['status'], remaining_acquisition_cost=value['display_principal'],
            market_value=value['display_value'], realized_gain=value['display_realized_gain'],
            unrealized_gain=value['display_accrued_gain'],
            gross_income=ZERO if value['status'] == 'complete' else None,
            total_gain=(value['display_realized_gain'] + value['display_accrued_gain']
                        if value['display_realized_gain'] is not None and value['display_accrued_gain'] is not None else None),
            net_flow=flow if value['status'] == 'complete' else None,
            purchases=purchases if value['status'] == 'complete' else None,
            daily_income=ZERO if value['status'] == 'complete' else None))
    result = []
    previous_value, factor = ZERO, Decimal('1')
    for day, entries in sorted(by_day.items()):
        values = portfolio_day(entries, previous_value, factor)
        previous_value, factor = values['market_value'], values.pop('return_factor')
        if any(row.status == 'pending' for row in entries) or dirty is not None and day >= dirty:
            values['status'] = 'pending'
        elif values['status'] == 'complete' and values['cumulative_return_pct'] is None:
            values['status'] = 'incomplete_history'
        result.append({'date': day, 'reporting_currency': display_currency,
                       'quote_date': None, 'quantity': None, 'average_cost': None, **values,
                       'net_flow': sum((row.net_flow for row in entries), ZERO) if all(row.net_flow is not None for row in entries) else None,
                       'purchases': sum((row.purchases for row in entries), ZERO) if all(row.purchases is not None for row in entries) else None,
                       'daily_income': ZERO})
    return result
