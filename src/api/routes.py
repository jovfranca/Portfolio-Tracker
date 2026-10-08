"""HTTP routes for portfolios, transactions and market data."""
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.database import Base, get_session
from src.domain import (corporate_event_effects, position_now, period_summary,
                        annualized_period_return, period_return_series, cdi_return_series)
from src.models import Asset, Benchmark, FixedIncomeLot, Instrument, Portfolio, Transaction, TransactionImport, UserCorporateEvent
from src.corporate_actions import SPLIT_TYPES, get_actions, get_stored_actions
from src.instruments import (
    add_alias, catalog_instruments, create_instrument, resolve_instrument, search_instruments,
    visible_instrument_details,
)
from src.market_prices import get_history, get_latest, get_quote_history, get_stored_history, save_user_price
from src.rates import RateUnavailable, backfill_rates, get_rates
from src.schemas import (
    CorporateEventInput, CorporateEventOutput, CustomInstrumentInput, PortfolioInput, QuoteInput, RateBackfillInput,
    TransactionImportConfirm, TransactionSelectionInput, TransactionOutput,
    FixedIncomeLotInput, FixedIncomeMovementInput,
)
from src.fixed_income import (
    add_movement, create_lot, delete_movement, edit_movement, get_lot, list_lots,
    lot_data, movement_data, value_lot,
)
from src.services import (
    ensure_asset, get_asset, get_overview, get_portfolio, require_instrument,
    transaction_currency_for, transaction_values,
)
from src.transaction_import import MAX_IMPORT_BYTES, preview_import
from src.import_template import transaction_template
from src.consolidation import consolidate, portfolio_series, position_series
from src.auth.dependencies import financial_access


router = APIRouter(prefix='/api', dependencies=[Depends(financial_access)])
public_router = APIRouter(prefix='/api')
DB = Annotated[Session, Depends(get_session)]


@public_router.get('/health')
def health(session: DB):
    # Verify mapped columns as well as connectivity, without reading user data.
    for table in Base.metadata.sorted_tables:
        session.execute(select(table).limit(0))
    return {'status': 'ok', 'database': 'postgresql'}


@router.get('/portfolios')
def portfolios(session: DB):
    query = select(Portfolio).where(Portfolio.household_id.in_(session.info['household_ids']))
    if 'household_id' in session.info:
        query = query.where(Portfolio.household_id == session.info['household_id'])
    return [
        {'id': portfolio.id, 'household_id': portfolio.household_id, 'name': portfolio.name, 'display_currency': portfolio.display_currency,
         'dirty_from': portfolio.dirty_from, 'history_built_through': portfolio.history_built_through}
        for portfolio in session.scalars(query.order_by(Portfolio.id))
    ]


@router.post('/portfolios', status_code=201)
def create_portfolio(payload: PortfolioInput, session: DB):
    portfolio = Portfolio(household_id=session.info['household_id'], **payload.model_dump())
    session.add(portfolio)
    session.commit()
    return {'id': portfolio.id, 'household_id': portfolio.household_id, 'name': portfolio.name, 'display_currency': portfolio.display_currency,
            'dirty_from': portfolio.dirty_from, 'history_built_through': portfolio.history_built_through}


@router.put('/portfolios/{portfolio_id}')
def rename_portfolio(portfolio_id: int, payload: PortfolioInput, session: DB):
    portfolio = get_portfolio(session, portfolio_id, lock=True)
    portfolio.name = payload.name
    if 'display_currency' in payload.model_fields_set:
        portfolio.display_currency = payload.display_currency
    session.commit()
    return {'id': portfolio.id, 'household_id': portfolio.household_id, 'name': portfolio.name, 'display_currency': portfolio.display_currency,
            'dirty_from': portfolio.dirty_from, 'history_built_through': portfolio.history_built_through}


@router.get('/instruments/search')
def instrument_search(q: str, session: DB, category: str = 'ALL', portfolio_id: int | None = None):
    if not q.strip():
        raise HTTPException(422, 'Informe um símbolo ou nome para pesquisar.')
    if category not in {'ALL', 'LISTED', 'STOCK', 'ETF', 'CRYPTO', 'FIXED_INCOME'}:
        raise HTTPException(422, 'Unknown instrument category.')
    if portfolio_id is not None:
        get_portfolio(session, portfolio_id)
    return search_instruments(session, q, category=category, portfolio_id=portfolio_id)


@router.get('/benchmarks')
def active_benchmarks(session: DB):
    rows = session.scalars(select(Benchmark).where(Benchmark.status == 'ACTIVE').order_by(Benchmark.code))
    return [{'id': row.id, 'code': row.code, 'name': row.name} for row in rows]


@router.get('/benchmarks/{code}/observations')
def benchmark_observations(code: str, session: DB):
    from src.benchmarks import stored_observations

    benchmark = session.scalar(select(Benchmark).where(Benchmark.code == code.upper()))
    if benchmark is None:
        raise HTTPException(404, 'Canonical benchmark not found.')
    rows = stored_observations(session, benchmark, date.min, date.max)
    return {
        'code': benchmark.code, 'name': benchmark.name, 'unit': benchmark.unit,
        'frequency': benchmark.frequency, 'count': len(rows),
        'earliest': rows[0].reference_date if rows else None,
        'latest': rows[-1].reference_date if rows else None,
        'observations': [
            {'reference_date': row.reference_date, 'value': str(row.value),
             'unit': benchmark.unit, 'source': row.source}
            for row in rows
        ],
    }


@router.get('/fixed-income/products')
def fixed_income_products(session: DB):
    from src.models import FixedIncomeProduct
    rows = session.scalars(select(FixedIncomeProduct).join(FixedIncomeProduct.instrument).where(
        Instrument.status == 'ACTIVE', Instrument.origin == 'CATALOG').order_by(Instrument.symbol))
    return [{
        'instrument_id': row.instrument_id, 'symbol': row.instrument.symbol,
        'name': row.instrument.name, 'default_currency': row.default_currency,
        'day_count_basis': row.day_count_basis, 'compounding': row.compounding,
        'business_day_calendar': row.business_day_calendar,
        'benchmark_lag_months': row.benchmark_lag_months,
    } for row in rows]


@router.get('/instruments/catalog')
def instrument_catalog(session: DB):
    return catalog_instruments(session)


@router.post('/instruments/custom', status_code=201)
def create_custom_instrument(payload: CustomInstrumentInput, session: DB):
    if payload.asset_type == 'FIXED_INCOME':
        raise HTTPException(422, 'Create private fixed-income instruments within a portfolio.')
    existing = resolve_instrument(session, payload.symbol)
    if existing.status == 'resolved' and existing.instrument.origin == 'CUSTOM':
        instrument = existing.instrument
        if (instrument.name == payload.name and instrument.asset_type == payload.asset_type
                and instrument.currency == (None if payload.asset_type == 'CRYPTO' else payload.currency)):
            return {
                'id': instrument.id, 'symbol': instrument.symbol, 'name': instrument.name,
                'currency': instrument.currency, 'asset_type': instrument.asset_type,
                'exchange': instrument.exchange, 'status': instrument.status,
            }
    if existing.status != 'unresolved':
        raise HTTPException(409, 'Identifier already exists; select the existing instrument.')
    instrument = create_instrument(
        session, **payload.model_dump(), aliases=[payload.symbol],
        alias_source='custom', origin='CUSTOM',
        household_id=session.info['household_id'],
    )
    session.commit()
    return {
        'id': instrument.id, 'symbol': instrument.symbol, 'name': instrument.name,
        'currency': instrument.currency, 'asset_type': instrument.asset_type,
        'exchange': instrument.exchange, 'status': instrument.status,
    }


@router.post('/portfolios/{portfolio_id}/fixed-income/instruments/custom', status_code=201)
def create_private_fixed_income_instrument(portfolio_id: int, payload: CustomInstrumentInput, session: DB):
    get_portfolio(session, portfolio_id)
    if payload.asset_type != 'FIXED_INCOME':
        raise HTTPException(422, 'This endpoint accepts fixed-income instruments only.')
    canonical = session.scalar(select(Instrument).where(
        Instrument.origin == 'CATALOG', Instrument.symbol == payload.symbol))
    if canonical is not None:
        raise HTTPException(409, 'Select the canonical product instead.')
    existing = session.scalar(select(Instrument).where(
        Instrument.origin == 'CUSTOM', Instrument.portfolio_id == portfolio_id,
        Instrument.asset_type == 'FIXED_INCOME', Instrument.symbol == payload.symbol))
    if existing is not None:
        if existing.name != payload.name or existing.currency != payload.currency:
            raise HTTPException(409, 'Private instrument already exists with different metadata.')
        instrument = existing
    else:
        instrument = create_instrument(
            session, **payload.model_dump(), aliases=[payload.symbol],
            alias_source='custom', origin='CUSTOM', portfolio_id=portfolio_id,
            household_id=session.info['household_id'])
        session.commit()
    return {'id': instrument.id, 'symbol': instrument.symbol, 'name': instrument.name,
            'currency': instrument.currency, 'asset_type': instrument.asset_type,
            'exchange': instrument.exchange, 'status': instrument.status}


@router.get('/instruments')
def instruments_page(session: DB):
    return visible_instrument_details(session)


@router.get('/instruments/{instrument_id}')
def instrument_detail(instrument_id: int, session: DB):
    rows = visible_instrument_details(session, instrument_id)
    if not rows:
        raise HTTPException(404, 'Instrument not found.')
    return rows[0]


@router.post('/instruments', status_code=201)
def select_instrument():
    raise HTTPException(410, 'Select a catalog instrument or use /instruments/custom; provider mappings are catalog-managed.')


@router.get('/portfolios/{portfolio_id}/overview')
def portfolio_overview(portfolio_id: int, session: DB):
    return get_overview(session, portfolio_id)


@router.get('/portfolios/{portfolio_id}/fx-coverage')
def fx_coverage(portfolio_id: int, session: DB):
    from src.fx_reporting import portfolio_fx_coverage
    return portfolio_fx_coverage(session, portfolio_id)


@router.post('/portfolios/{portfolio_id}/fixed-income/lots', status_code=201)
def create_fixed_income_lot(portfolio_id: int, payload: FixedIncomeLotInput, session: DB):
    lot = create_lot(session, portfolio_id, payload)
    result = lot_data(lot)
    session.commit()
    return result


@router.get('/portfolios/{portfolio_id}/fixed-income/lots')
def fixed_income_lots(portfolio_id: int, session: DB, as_of: date | None = None):
    valuation_date = as_of or date.today()
    if valuation_date > date.today():
        raise HTTPException(422, 'Valuation date cannot be in the future.')
    portfolio = get_portfolio(session, portfolio_id)
    return [lot_data(lot, value_lot(session, lot, valuation_date, portfolio.display_currency))
            for lot in list_lots(session, portfolio_id)]


@router.get('/portfolios/{portfolio_id}/fixed-income/lots/{lot_id}')
def fixed_income_lot(portfolio_id: int, lot_id: int, session: DB, as_of: date | None = None):
    valuation_date = as_of or date.today()
    if valuation_date > date.today():
        raise HTTPException(422, 'Valuation date cannot be in the future.')
    lot = get_lot(session, portfolio_id, lot_id)
    portfolio = get_portfolio(session, portfolio_id)
    return lot_data(lot, value_lot(session, lot, valuation_date, portfolio.display_currency))


@router.post('/portfolios/{portfolio_id}/fixed-income/lots/{lot_id}/movements', status_code=201)
def create_fixed_income_movement(portfolio_id: int, lot_id: int,
                                 payload: FixedIncomeMovementInput, session: DB):
    movement = add_movement(session, portfolio_id, lot_id, payload)
    result = movement_data(movement)
    session.commit()
    return result


@router.get('/portfolios/{portfolio_id}/fixed-income/lots/{lot_id}/movements')
def fixed_income_movements(portfolio_id: int, lot_id: int, session: DB):
    return [movement_data(row) for row in get_lot(session, portfolio_id, lot_id).movements]


@router.put('/portfolios/{portfolio_id}/fixed-income/lots/{lot_id}/movements/{movement_id}')
def update_fixed_income_movement(portfolio_id: int, lot_id: int, movement_id: int,
                                 payload: FixedIncomeMovementInput, session: DB):
    movement = edit_movement(session, portfolio_id, lot_id, movement_id, payload)
    result = movement_data(movement)
    session.commit()
    return result


@router.delete('/portfolios/{portfolio_id}/fixed-income/lots/{lot_id}/movements/{movement_id}', status_code=204)
def remove_fixed_income_movement(portfolio_id: int, lot_id: int, movement_id: int, session: DB):
    delete_movement(session, portfolio_id, lot_id, movement_id)
    session.commit()
    return Response(status_code=204)


@router.post('/portfolios/{portfolio_id}/consolidate')
def consolidate_portfolio(portfolio_id: int, session: DB):
    result = consolidate(session, portfolio_id)
    session.commit()
    return result


@router.get('/portfolios/{portfolio_id}/history')
def portfolio_performance(portfolio_id: int, session: DB):
    return portfolio_series(session, portfolio_id)


@router.get('/portfolios/{portfolio_id}/analytics')
def portfolio_period_analytics(portfolio_id: int, session: DB,
                               start_date: date | None = None, end_date: date | None = None,
                               include_series: bool = False, benchmark_codes: str = ''):
    if start_date and end_date and end_date < start_date:
        raise HTTPException(422, 'A data final deve ser igual ou posterior à inicial.')
    if (start_date and start_date > date.today()) or (end_date and end_date > date.today()):
        raise HTTPException(422, 'O período não pode estar no futuro.')
    # History contains closed days only; today's current quote is a separate projection.
    closed_end = min(end_date or date.today(), date.today() - timedelta(days=1))
    if start_date and start_date > closed_end:
        closed_end = end_date or date.today()  # no closed days, but keep a valid selected range
    portfolio = get_portfolio(session, portfolio_id)
    rows = portfolio_series(session, portfolio_id)
    activity_starts = [session.scalar(select(func.min(Transaction.trade_date)).where(
        Transaction.portfolio_id == portfolio_id)), session.scalar(select(func.min(FixedIncomeLot.start_date)).
        join(Asset, FixedIncomeLot.asset_id == Asset.id).where(Asset.portfolio_id == portfolio_id))]
    # Sources can precede the first available snapshot. Never assume a truncated series opened at zero.
    starts = [day for day in activity_starts if day is not None]
    if rows:
        starts.append(rows[0]['date'])
    inception = min(starts, default=None)
    result = period_summary(rows, start_date, closed_end, inception_date=inception)
    response = {**result, 'reporting_currency': portfolio.display_currency,
                'requested_start_date': start_date, 'requested_end_date': end_date}
    if include_series:
        from src.benchmarks import stored_observations

        series = period_return_series(rows, start_date, closed_end)
        response['annualized_return_pct'] = annualized_period_return(result)
        response['return_series'] = series
        comparisons = []
        for code in dict.fromkeys(c.strip().upper() for c in benchmark_codes.split(',') if c.strip()):
            comparison = {'code': code, 'status': 'unsupported', 'return_pct': None,
                          'annualized_return_pct': None, 'series': []}
            benchmark = session.scalar(select(Benchmark).where(Benchmark.code == code, Benchmark.status == 'ACTIVE')) if code == 'CDI' else None
            if (code == 'CDI' and portfolio.display_currency == 'BRL' and benchmark is not None
                    and benchmark.frequency == 'DAILY' and benchmark.unit == 'PERCENT_PER_DAY'
                    and benchmark.reference_currency == 'BRL' and benchmark.jurisdiction == 'BR'):
                dates = [r['date'] for r in series]
                observations = stored_observations(session, benchmark, dates[0], dates[-1]) if dates else []
                comparison['series'] = cdi_return_series(dates, {r.reference_date: r.value for r in observations})
                complete = result['status'] == 'complete' and bool(dates) and all(
                    r['return_pct'] is not None for r in comparison['series'])
                comparison['status'] = 'complete' if complete else 'incomplete'
                if complete:
                    comparison['return_pct'] = comparison['series'][-1]['return_pct']
                    comparison['annualized_return_pct'] = annualized_period_return({
                        **result, 'return_pct': comparison['return_pct']})
            comparisons.append(comparison)
        response['benchmarks'] = comparisons
    return response


@router.get('/portfolios/{portfolio_id}/transactions', response_model=list[TransactionOutput])
def transactions(portfolio_id: int, session: DB):
    get_portfolio(session, portfolio_id)
    return list(session.scalars(
        select(Transaction)
        .where(Transaction.portfolio_id == portfolio_id)
        .order_by(Transaction.trade_date.desc(), Transaction.id.desc())
    ))


@router.post(
    '/portfolios/{portfolio_id}/transactions',
    response_model=TransactionOutput,
    status_code=201,
)
def add_transaction(portfolio_id: int, payload: TransactionSelectionInput, session: DB):
    get_portfolio(session, portfolio_id, lock=True)
    instrument = require_instrument(session, payload.asset, payload.instrument_id)
    add_alias(session, instrument, payload.asset, 'manual-entry')
    ensure_asset(session, portfolio_id, instrument)
    values = transaction_values(session, payload, transaction_currency_for(
        instrument, payload.transaction_currency,
    ))
    values['instrument_id'] = instrument.id
    transaction = Transaction(
        portfolio_id=portfolio_id, **values
    )
    session.add(transaction)
    session.flush()
    _validate_position_activity(session, portfolio_id, {instrument.id})
    session.commit()
    return transaction


def find_transaction(session, portfolio_id, transaction_id):
    transaction = session.scalar(select(Transaction).where(
        Transaction.id == transaction_id,
        Transaction.portfolio_id == portfolio_id,
    ))
    if transaction is None:
        raise HTTPException(404, 'Transação não encontrada nesta carteira.')
    return transaction


def _validate_position_activity(session, portfolio_id, instrument_ids):
    """Keep oversell validation on writes without constructing the overview."""
    for instrument_id in instrument_ids:
        rows = list(session.scalars(select(Transaction).where(
            Transaction.portfolio_id == portfolio_id,
            Transaction.instrument_id == instrument_id,
        )))
        if not rows:
            continue
        asset = session.scalar(select(Asset).where(
            Asset.portfolio_id == portfolio_id, Asset.instrument_id == instrument_id,
        ))
        events = get_stored_actions(session, asset) if asset else []
        try:
            position_now(rows, events, None, 'BRL', {}, valuation_date=date.today())
        except ValueError as error:
            raise HTTPException(422, str(error)) from error


@router.put(
    '/portfolios/{portfolio_id}/transactions/{transaction_id}',
    response_model=TransactionOutput,
)
def edit_transaction(
    portfolio_id: int,
    transaction_id: int,
    payload: TransactionSelectionInput,
    session: DB,
):
    get_portfolio(session, portfolio_id, lock=True)
    transaction = find_transaction(session, portfolio_id, transaction_id)
    old_instrument_id = transaction.instrument_id
    instrument = require_instrument(session, payload.asset, payload.instrument_id)
    add_alias(session, instrument, payload.asset, 'manual-entry')
    ensure_asset(session, portfolio_id, instrument)
    values = transaction_values(session, payload, transaction_currency_for(
        instrument, payload.transaction_currency,
    ))
    values['instrument_id'] = instrument.id
    if transaction.trade_date == payload.trade_date:
        values['date_time'] = transaction.date_time
    for key, value in values.items():
        setattr(transaction, key, value)
    session.flush()
    _validate_position_activity(session, portfolio_id, {old_instrument_id, instrument.id})
    session.commit()
    return transaction


@router.delete('/portfolios/{portfolio_id}/transactions/{transaction_id}', status_code=204)
def delete_transaction(portfolio_id: int, transaction_id: int, session: DB):
    get_portfolio(session, portfolio_id, lock=True)
    transaction = find_transaction(session, portfolio_id, transaction_id)
    instrument_id = transaction.instrument_id
    session.delete(transaction)
    session.flush()
    _validate_position_activity(session, portfolio_id, {instrument_id})
    session.commit()


@public_router.get('/transactions/import-template.xlsx')
def download_transaction_template():
    return Response(
        transaction_template(),
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': 'attachment; filename="modelo-transacoes.xlsx"'},
    )


@router.post('/portfolios/{portfolio_id}/transactions/import-preview')
async def import_preview(portfolio_id: int, filename: str, request: Request, session: DB):
    get_portfolio(session, portfolio_id)
    if len(filename) > 255:
        raise HTTPException(422, 'O nome do arquivo excede 255 caracteres.')
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_IMPORT_BYTES:
            raise HTTPException(413, 'O arquivo excede o limite de 5 MB.')
        content.extend(chunk)
    content = bytes(content)
    result = preview_import(session, filename, content, portfolio_id)
    previous = session.scalar(select(TransactionImport.id).where(
        TransactionImport.portfolio_id == portfolio_id,
        TransactionImport.digest == result['digest'],
    ))
    result['already_imported'] = previous is not None
    return result


@router.post('/portfolios/{portfolio_id}/transactions/import-resolve')
def resolve_import_row(portfolio_id: int, payload: TransactionSelectionInput, session: DB):
    get_portfolio(session, portfolio_id)
    instrument = require_instrument(session, payload.asset, payload.instrument_id)
    values = transaction_values(session, payload, transaction_currency_for(
        instrument, payload.transaction_currency,
    ))
    values.pop('date_time')
    values['instrument_id'] = instrument.id
    return TransactionSelectionInput.model_validate(values)


@router.post('/portfolios/{portfolio_id}/transactions/import', status_code=201)
def import_transactions(
    portfolio_id: int,
    payload: TransactionImportConfirm,
    session: DB,
):
    get_portfolio(session, portfolio_id, lock=True)
    previous = session.scalar(select(TransactionImport.id).where(
        TransactionImport.portfolio_id == portfolio_id,
        TransactionImport.digest == payload.digest,
    ))
    if previous is not None:
        raise HTTPException(409, 'Este arquivo já foi importado para esta carteira.')
    changed_instruments = set()
    for row in payload.rows:
        instrument = require_instrument(session, row.asset, row.instrument_id)
        ensure_asset(session, portfolio_id, instrument)
        add_alias(session, instrument, row.asset, 'import')
        values = transaction_values(session, row, transaction_currency_for(
            instrument, row.transaction_currency,
        ))
        values['instrument_id'] = instrument.id
        changed_instruments.add(instrument.id)
        session.add(Transaction(
            portfolio_id=portfolio_id, **values
        ))
    session.flush()
    _validate_position_activity(session, portfolio_id, changed_instruments)
    session.add(TransactionImport(
        portfolio_id=portfolio_id,
        digest=payload.digest,
        filename=payload.filename,
        records=len(payload.rows),
    ))
    session.commit()
    return {'imported': len(payload.rows)}


@router.get('/portfolios/{portfolio_id}/assets/{asset_id}/history')
def asset_history(portfolio_id: int, asset_id: int, session: DB):
    asset = get_asset(session, portfolio_id, asset_id)
    return [
        {
            'date': history.date,
            'close': history.close,
            'dividends': history.dividends,
            'stock_splits': history.stock_splits,
            'source': history.source,
            'origin': history.origin,
            'currency': history.currency,
            'retrieved_at': history.retrieved_at,
        }
        for history in get_quote_history(session, asset)
    ]


@router.put('/portfolios/{portfolio_id}/assets/{asset_id}/quote')
def save_quote(portfolio_id: int, asset_id: int, payload: QuoteInput, session: DB):
    get_portfolio(session, portfolio_id, lock=True)
    asset = get_asset(session, portfolio_id, asset_id)
    try:
        save_user_price(
            session, asset, payload.date, payload.close, payload.currency,
            payload.dividends if 'dividends' in payload.model_fields_set else None,
            payload.stock_splits if 'stock_splits' in payload.model_fields_set else None,
        )
    except ValueError as error:
        raise HTTPException(422, str(error))
    session.commit()
    return {'saved': 1}


def _event_payload(event):
    return {
        'id': event.id,
        'event_type': event.event_type,
        'effective_date': event.effective_date,
        'payment_date': event.payment_date,
        'amount_per_unit': event.amount_per_unit,
        'conversion_factor': event.conversion_factor,
        'currency': event.currency,
        'source': event.source,
        'origin': event.origin,
        'retrieved_at': event.retrieved_at,
        'notes': event.notes,
    }


@router.get('/portfolios/{portfolio_id}/assets/{asset_id}/corporate-events')
def corporate_events(portfolio_id: int, asset_id: int, session: DB):
    asset = get_asset(session, portfolio_id, asset_id)
    transactions = list(session.scalars(select(Transaction).where(
        Transaction.portfolio_id == portfolio_id,
        Transaction.instrument_id == asset.instrument_id,
    )))
    events = get_stored_actions(session, asset)
    effects = corporate_event_effects(transactions, events)
    return [
        _event_payload(effect['event']) | {
            key: value for key, value in effect.items() if key != 'event'
        }
        for effect in effects
    ]


@router.post(
    '/portfolios/{portfolio_id}/assets/{asset_id}/corporate-events',
    response_model=CorporateEventOutput,
    status_code=201,
)
def add_corporate_event(
    portfolio_id: int, asset_id: int, payload: CorporateEventInput, session: DB,
):
    get_portfolio(session, portfolio_id, lock=True)
    asset = get_asset(session, portfolio_id, asset_id)
    event_types = SPLIT_TYPES if payload.event_type in SPLIT_TYPES else {payload.event_type}
    duplicate = session.scalar(select(UserCorporateEvent.id).where(
        UserCorporateEvent.asset_id == asset.id,
        UserCorporateEvent.event_type.in_(event_types),
        UserCorporateEvent.effective_date == payload.effective_date,
    ))
    if duplicate is not None:
        raise HTTPException(409, 'Já existe um evento manual equivalente nesta data.')
    event = UserCorporateEvent(
        asset_id=asset.id, source='manual', **payload.model_dump(),
    )
    session.add(event)
    session.flush()
    _validate_position_activity(session, portfolio_id, {asset.instrument_id})
    session.commit()
    return event


def _manual_event(session, portfolio_id, asset_id, event_id):
    get_asset(session, portfolio_id, asset_id)
    event = session.scalar(select(UserCorporateEvent).where(
        UserCorporateEvent.id == event_id,
        UserCorporateEvent.asset_id == asset_id,
    ))
    if event is None:
        raise HTTPException(404, 'Evento manual não encontrado neste ativo.')
    return event


@router.put(
    '/portfolios/{portfolio_id}/assets/{asset_id}/corporate-events/{event_id}',
    response_model=CorporateEventOutput,
)
def edit_corporate_event(
    portfolio_id: int, asset_id: int, event_id: int,
    payload: CorporateEventInput, session: DB,
):
    get_portfolio(session, portfolio_id, lock=True)
    event = _manual_event(session, portfolio_id, asset_id, event_id)
    event_types = SPLIT_TYPES if payload.event_type in SPLIT_TYPES else {payload.event_type}
    duplicate = session.scalar(select(UserCorporateEvent.id).where(
        UserCorporateEvent.asset_id == asset_id,
        UserCorporateEvent.event_type.in_(event_types),
        UserCorporateEvent.effective_date == payload.effective_date,
        UserCorporateEvent.id != event.id,
    ))
    if duplicate is not None:
        raise HTTPException(409, 'Já existe um evento manual equivalente nesta data.')
    for key, value in payload.model_dump().items():
        setattr(event, key, value)
    event.updated_at = datetime.now(timezone.utc)
    session.flush()
    asset = get_asset(session, portfolio_id, asset_id)
    _validate_position_activity(session, portfolio_id, {asset.instrument_id})
    session.commit()
    return event


@router.delete(
    '/portfolios/{portfolio_id}/assets/{asset_id}/corporate-events/{event_id}',
    status_code=204,
)
def delete_corporate_event(
    portfolio_id: int, asset_id: int, event_id: int, session: DB,
):
    get_portfolio(session, portfolio_id, lock=True)
    event = _manual_event(session, portfolio_id, asset_id, event_id)
    session.delete(event)
    session.flush()
    asset = get_asset(session, portfolio_id, asset_id)
    _validate_position_activity(session, portfolio_id, {asset.instrument_id})
    session.commit()


@router.get('/portfolios/{portfolio_id}/assets/{asset_id}/activity')
def asset_activity(portfolio_id: int, asset_id: int, session: DB):
    asset = get_asset(session, portfolio_id, asset_id)
    transactions = list(session.scalars(select(Transaction).where(
        Transaction.portfolio_id == portfolio_id,
        Transaction.instrument_id == asset.instrument_id,
    )))
    effects = corporate_event_effects(transactions, get_stored_actions(session, asset))
    rows = [{
        'kind': 'TRANSACTION', 'id': row.id, 'date': row.trade_date,
        'type': row.type, 'quantity': row.quantity, 'price': row.price,
        'currency': row.transaction_currency, 'broker': row.broker,
        'allocation_class': row.allocation_class,
    } for row in transactions]
    rows.extend({
        'kind': 'CORPORATE_ACTION', 'date': effect['event'].effective_date,
        **_event_payload(effect['event']),
        **{key: value for key, value in effect.items() if key != 'event'},
    } for effect in effects)
    return sorted(rows, key=lambda row: (
        row['date'],
        (0 if row['event_type'] in {'STOCK_SPLIT', 'REVERSE_SPLIT'} else 1)
        if row['kind'] == 'CORPORATE_ACTION' else 2,
        row['id'],
    ))


@router.get('/portfolios/{portfolio_id}/assets/{asset_id}/quote')
def latest_quote(portfolio_id: int, asset_id: int, session: DB):
    asset = get_asset(session, portfolio_id, asset_id)
    result = get_latest(session, asset)
    first = session.scalar(select(Transaction.trade_date).where(
        Transaction.portfolio_id == portfolio_id,
        Transaction.instrument_id == asset.instrument_id,
    ).order_by(Transaction.trade_date).limit(1))
    if first is not None:
        get_actions(session, asset, first, date.today())
    session.commit()
    if not result.available:
        raise HTTPException(404, 'Não há cotação disponível para este ativo.')
    return {
        'date': result.price.date,
        'price': result.price.close,
        'currency': result.price.currency,
        'source': result.price.source,
        'origin': result.price.origin,
        'market_at': result.price.market_at,
        'retrieved_at': result.price.retrieved_at,
        'stale': result.stale,
    }


@router.post('/portfolios/{portfolio_id}/assets/{asset_id}/refresh')
def refresh_quotes(portfolio_id: int, asset_id: int, session: DB):
    asset = get_asset(session, portfolio_id, asset_id)
    transactions = list(session.scalars(select(Transaction).where(
        Transaction.portfolio_id == portfolio_id,
        Transaction.instrument_id == asset.instrument_id,
    )))
    if not transactions:
        raise HTTPException(422, 'Cadastre uma transação antes de atualizar.')

    start = min(transaction.trade_date for transaction in transactions)
    history_end = date.today() - timedelta(days=1)
    result = get_history(session, asset, start, history_end) if start <= history_end else None
    action_result = get_actions(session, asset, start, date.today())
    latest = get_latest(session, asset)
    session.commit()
    if not latest.available or latest.stale:
        raise HTTPException(
            502,
            'Não foi possível obter cotações. Verifique o ticker ou registre uma '
            'cotação manual; os dados anteriores foram mantidos.',
        )
    complete = ((result is None or result.complete)
                and (action_result is None or action_result.complete))
    return {
        'received': len(result.prices) if result is not None else 0,
        'latest_available': latest.available,
        'complete': complete,
        'missing_ranges': result.missing_ranges if result is not None else [],
        'missing_action_ranges': action_result.missing_ranges if action_result is not None else [],
        'message': (
            'Histórico atualizado. Cotações manuais foram preservadas.' if complete else
            'Histórico parcial. Alguns fechamentos ou eventos não foram retornados pelo Yahoo '
            'Finance. Tente novamente mais tarde; cotações anteriores e preços manuais preservados.'
        ),
    }


@router.get('/portfolios/{portfolio_id}/performance')
def performance(
    portfolio_id: int,
    session: DB,
    asset_id: int,
):
    asset = get_asset(session, portfolio_id, asset_id)
    return position_series(session, portfolio_id, asset.instrument_id)


@router.get('/rates/{rate_type}/{currency}/{reference_date}')
def historical_rate(rate_type: str, currency: str, reference_date: date, session: DB):
    try:
        rates = get_rates(session, currency, rate_type, reference_date)
        session.commit()
    except ValueError as error:
        session.rollback()
        status = 404 if isinstance(error, RateUnavailable) else 422
        raise HTTPException(status, str(error))
    resolved_date = rates[0].reference_date
    return {
        'currency': rates[0].currency,
        'rate_type': rates[0].rate_type,
        'requested_date': reference_date,
        'reference_date': resolved_date,
        'rates': [
            {
                'side': rate.rate_side,
                'rate': str(rate.rate),
                'source': rate.source,
                'retrieved_at': rate.retrieved_at,
            }
            for rate in rates
        ],
        'fallback_used': resolved_date != reference_date,
    }


@router.post('/rates/backfill')
def backfill_historical_rates(payload: RateBackfillInput, session: DB):
    try:
        result = backfill_rates(
            session,
            payload.currencies,
            payload.rate_types,
            payload.start_date,
            payload.end_date,
        )
        session.commit()
    except Exception as error:
        session.rollback()
        raise HTTPException(502, f'Não foi possível completar o backfill: {error}')
    return result
