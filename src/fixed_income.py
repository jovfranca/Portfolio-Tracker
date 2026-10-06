"""Persist fixed-income contracts and resolve read-only lot valuations."""
from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select

from src.models import Asset, Benchmark, Broker, FixedIncomeLot, FixedIncomeMovement, FixedIncomeProduct, Instrument
from src.services import ensure_asset, get_portfolio


def value_lot(session, lot, valuation_date, display_currency=None):
    from src.fixed_income_history import saved_lot_value
    return saved_lot_value(session, lot, valuation_date, display_currency or lot.currency)


def _lot_valuation(session, lot, movements, valuation_date):
    from src.benchmarks import stored_observations
    from src.domain import fixed_income_valuation

    with session.no_autoflush:
        observations = []
        if lot.benchmark is not None and valuation_date >= lot.start_date:
            first = lot.start_date
            if lot.yield_structure == 'BENCHMARK_SPREAD':
                month = first.year * 12 + first.month - 2 - lot.benchmark_lag_months
                first = date(month // 12, month % 12 + 1, 1)
            last = (valuation_date - timedelta(days=1)
                    if lot.yield_structure == 'BENCHMARK_MULTIPLE' else valuation_date)
            if first <= last:
                observations = stored_observations(session, lot.benchmark, first, last)
        return fixed_income_valuation(lot, movements, valuation_date, observations)


def position_valuations(session, lots, valuation_date, display_currency, *, portfolio_id=None):
    from src.fixed_income_history import saved_position_valuations
    if portfolio_id is None:
        portfolio_id = lots[0].asset.portfolio_id if lots else None
    return saved_position_valuations(session, portfolio_id, lots, valuation_date, display_currency)


def get_lot(session, portfolio_id, lot_id):
    get_portfolio(session, portfolio_id)
    lot = session.scalar(select(FixedIncomeLot).join(Asset).where(
        FixedIncomeLot.id == lot_id, Asset.portfolio_id == portfolio_id))
    if lot is None:
        raise HTTPException(404, 'Fixed-income lot not found in this portfolio.')
    return lot


def list_lots(session, portfolio_id):
    get_portfolio(session, portfolio_id)
    return list(session.scalars(select(FixedIncomeLot).join(Asset).where(
        Asset.portfolio_id == portfolio_id).order_by(FixedIncomeLot.id)))


def create_lot(session, portfolio_id, payload):
    get_portfolio(session, portfolio_id, lock=True)
    instrument = session.get(Instrument, payload.instrument_id)
    if instrument is None or instrument.asset_type != 'FIXED_INCOME':
        raise HTTPException(422, 'Select a canonical fixed-income instrument.')
    if instrument.origin == 'CUSTOM' and instrument.portfolio_id != portfolio_id:
        raise HTTPException(422, 'Private fixed-income instrument belongs to another portfolio.')
    product = session.get(FixedIncomeProduct, instrument.id)
    if product is not None and payload.product_type != instrument.symbol:
        raise HTTPException(422, 'Product type must match the canonical instrument.')
    values = payload.model_dump(exclude={'broker', 'opening_amount', 'instrument_id'})
    for field in ('currency', 'day_count_basis', 'compounding',
                  'business_day_calendar', 'benchmark_lag_months'):
        if values[field] is None and product is not None:
            values[field] = getattr(product, 'default_currency' if field == 'currency' else field)
        if values[field] is None:
            raise HTTPException(422, f'{field} is required for this instrument.')
    if instrument.currency and instrument.currency != values['currency']:
        raise HTTPException(422, 'Lot currency must match the instrument currency.')
    if payload.benchmark_id is not None:
        benchmark = session.get(Benchmark, payload.benchmark_id)
        if benchmark is None or benchmark.status != 'ACTIVE':
            raise HTTPException(422, 'Select an active canonical benchmark.')
    broker = session.scalar(select(Broker).where(Broker.name == payload.broker))
    if broker is None:
        broker = Broker(name=payload.broker)
        session.add(broker)
        session.flush()
    asset = ensure_asset(session, portfolio_id, instrument)
    lot = FixedIncomeLot(asset_id=asset.id, broker_id=broker.id, **values)
    session.add(lot)
    session.flush()
    session.add(FixedIncomeMovement(
        lot_id=lot.id, movement_type='INITIAL_INVESTMENT', effective_date=payload.start_date,
        amount=payload.opening_amount, currency=values['currency']))
    session.flush()
    from src.consolidation import mark_dirty
    mark_dirty(session, portfolio_id, payload.start_date, asset.instrument_id, 'fixed_income')
    return lot


def add_movement(session, portfolio_id, lot_id, payload):
    get_portfolio(session, portfolio_id, lock=True)
    lot = get_lot(session, portfolio_id, lot_id)
    if payload.movement_type == 'INITIAL_INVESTMENT':
        raise HTTPException(422, 'Initial investment is created with the lot.')
    movement = FixedIncomeMovement(lot_id=lot.id, **payload.model_dump())
    _validate_movements(session, lot, list(lot.movements) + [movement], fill_full=movement)
    session.add(movement)
    session.flush()
    from src.consolidation import mark_dirty
    mark_dirty(session, portfolio_id, payload.effective_date, lot.asset.instrument_id, 'fixed_income')
    return movement


def _validate_movements(session, lot, movements, fill_full=None):
    ordered = sorted(movements, key=lambda row: (
        row.effective_date, row.id if row.id is not None else float('inf')))
    if not ordered or ordered[0].movement_type != 'INITIAL_INVESTMENT':
        raise HTTPException(422, 'A fixed-income lot requires an initial investment.')
    if ordered[0].effective_date != lot.start_date:
        raise HTTPException(422, 'Initial investment date must match lot start date.')
    for index, row in enumerate(ordered):
        if row.currency != lot.currency or row.effective_date < lot.start_date:
            raise HTTPException(422, f'Movement {row.id} conflicts with lot currency or start date.')
        if lot.maturity_date and row.effective_date > lot.maturity_date:
            raise HTTPException(422, f'Movement {row.id} occurs after lot maturity.')
        if index == 0:
            if row.amount is None or row.amount <= 0:
                raise HTTPException(422, 'Initial investment amount must be positive.')
            continue
        if row.movement_type == 'INITIAL_INVESTMENT':
            raise HTTPException(422, f'Movement {row.id} duplicates the initial investment.')
        if row is fill_full and row.movement_type == 'FULL_REDEMPTION' and row.amount is None:
            before = _lot_valuation(session, lot, ordered[:index], row.effective_date)
            if before['status'] != 'complete' or before['gross_accrued_value'] <= 0:
                raise HTTPException(422, f'Movement {row.id} cannot be valued: {before["status"]}.')
            row.amount = before['gross_accrued_value']
        valued = _lot_valuation(session, lot, ordered[:index + 1], row.effective_date)
        if row.movement_type == 'ADDITIONAL_INVESTMENT' and valued['status'] == 'missing_benchmark':
            continue
        if valued['status'] != 'complete':
            raise HTTPException(422, f'Movement {row.id} invalidates this lot: {valued["status"]}.')


def edit_movement(session, portfolio_id, lot_id, movement_id, payload):
    get_portfolio(session, portfolio_id, lock=True)
    lot = get_lot(session, portfolio_id, lot_id)
    row = next((item for item in lot.movements if item.id == movement_id), None)
    if row is None:
        raise HTTPException(404, 'Fixed-income movement not found in this lot.')
    if (row.movement_type == 'INITIAL_INVESTMENT') != (payload.movement_type == 'INITIAL_INVESTMENT'):
        raise HTTPException(422, 'Initial investment cannot be changed to another movement type.')
    old_day = row.effective_date
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    if row.movement_type == 'INITIAL_INVESTMENT':
        if lot.maturity_date and row.effective_date > lot.maturity_date:
            raise HTTPException(422, 'Initial investment would follow maturity.')
        lot.start_date = row.effective_date
    _validate_movements(session, lot, list(lot.movements), fill_full=row)
    session.flush()
    from src.consolidation import mark_dirty
    mark_dirty(session, portfolio_id, min(old_day, row.effective_date),
               lot.asset.instrument_id, 'fixed_income')
    return row


def delete_movement(session, portfolio_id, lot_id, movement_id):
    get_portfolio(session, portfolio_id, lock=True)
    lot = get_lot(session, portfolio_id, lot_id)
    instrument_id = lot.asset.instrument_id
    row = next((item for item in lot.movements if item.id == movement_id), None)
    if row is None:
        raise HTTPException(404, 'Fixed-income movement not found in this lot.')
    later = [item for item in lot.movements if item.id != row.id]
    if row.movement_type == 'INITIAL_INVESTMENT':
        if later:
            raise HTTPException(422, 'Delete later lot movements before deleting the initial investment.')
        session.delete(row)
        session.flush()
        session.delete(lot)
    else:
        _validate_movements(session, lot, later)
        session.delete(row)
    session.flush()
    if row.movement_type != 'INITIAL_INVESTMENT':
        session.expire(lot, ['movements'])
    from src.consolidation import mark_dirty
    mark_dirty(session, portfolio_id, row.effective_date, instrument_id, 'fixed_income')


def movement_data(movement):
    return {'id': movement.id, 'lot_id': movement.lot_id,
            'movement_type': movement.movement_type, 'effective_date': movement.effective_date,
            'amount': str(movement.amount), 'currency': movement.currency, 'notes': movement.notes}


def lot_data(lot, valuation=None):
    opening = next((row for row in lot.movements if row.movement_type == 'INITIAL_INVESTMENT'), None)
    return {
        'id': lot.id, 'asset_id': lot.asset_id, 'instrument_id': lot.asset.instrument_id,
        'instrument_symbol': lot.asset.instrument.symbol,
        'instrument_name': lot.asset.instrument.name,
        'product_type': lot.product_type, 'issuer': lot.issuer, 'broker': lot.broker.name,
        'currency': lot.currency, 'start_date': lot.start_date, 'maturity_date': lot.maturity_date,
        'yield_structure': lot.yield_structure,
        'fixed_rate': str(lot.fixed_rate) if lot.fixed_rate is not None else None,
        'benchmark_id': lot.benchmark_id,
        'benchmark_code': lot.benchmark.code if lot.benchmark is not None else None,
        'benchmark_multiplier': str(lot.benchmark_multiplier) if lot.benchmark_multiplier is not None else None,
        'benchmark_spread': str(lot.benchmark_spread) if lot.benchmark_spread is not None else None,
        'day_count_basis': lot.day_count_basis,
        'compounding': lot.compounding, 'business_day_calendar': lot.business_day_calendar,
        'benchmark_lag_months': lot.benchmark_lag_months,
        'opening_amount': str(opening.amount) if opening is not None else None,
        'notes': lot.notes, 'status': lot.status,
        'current_value': str(valuation['gross_accrued_value']) if valuation and valuation['gross_accrued_value'] is not None else None,
        'profitability': None, 'valuation_status': valuation['status'] if valuation else 'pending',
        'valuation': valuation,
        'movements': [movement_data(row) for row in lot.movements],
    }
