"""Persist fixed-income contracts and source cash movements without valuation."""
from fastapi import HTTPException
from sqlalchemy import select

from src.models import Asset, Benchmark, Broker, FixedIncomeLot, FixedIncomeMovement, FixedIncomeProduct, Instrument
from src.services import ensure_asset, get_portfolio


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
    return lot


def add_movement(session, portfolio_id, lot_id, payload):
    lot = get_lot(session, portfolio_id, lot_id)
    if payload.currency != lot.currency:
        raise HTTPException(422, 'Movement currency must match lot currency.')
    if payload.effective_date < lot.start_date:
        raise HTTPException(422, 'Movement date precedes lot start date.')
    movement = FixedIncomeMovement(lot_id=lot.id, **payload.model_dump())
    session.add(movement)
    session.flush()
    return movement


def movement_data(movement):
    return {'id': movement.id, 'lot_id': movement.lot_id,
            'movement_type': movement.movement_type, 'effective_date': movement.effective_date,
            'amount': str(movement.amount), 'currency': movement.currency, 'notes': movement.notes}


def lot_data(lot):
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
        'current_value': None, 'profitability': None, 'valuation_status': 'pending',
        'movements': [movement_data(row) for row in lot.movements],
    }
