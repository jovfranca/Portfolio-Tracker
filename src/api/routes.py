"""HTTP routes for portfolios, transactions and market data."""
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database import Base, get_session
from src.domain import historical_profitability
from src.models import Portfolio, Transaction, TransactionImport
from src.instruments import (
    add_alias, catalog_instruments, create_instrument, resolve_instrument, search_instruments,
)
from src.market_prices import get_history, get_latest, get_quote_history, get_stored_history, save_user_price
from src.rates import RateUnavailable, backfill_rates, get_rates
from src.schemas import (
    CustomInstrumentInput, PortfolioInput, QuoteInput, RateBackfillInput,
    TransactionImportConfirm, TransactionSelectionInput, TransactionOutput,
)
from src.services import (
    ensure_asset, ensure_asset_currency, get_asset, get_overview, get_portfolio,
    require_instrument, transaction_values,
)
from src.transaction_import import MAX_IMPORT_BYTES, preview_import
from src.import_template import transaction_template


router = APIRouter(prefix='/api')
DB = Annotated[Session, Depends(get_session)]


@router.get('/health')
def health(session: DB):
    # Verify mapped columns as well as connectivity, without reading user data.
    for table in Base.metadata.sorted_tables:
        session.execute(select(table).limit(0))
    return {'status': 'ok', 'database': 'postgresql'}


@router.get('/portfolios')
def portfolios(session: DB):
    return [
        {'id': portfolio.id, 'name': portfolio.name}
        for portfolio in session.scalars(select(Portfolio).order_by(Portfolio.id))
    ]


@router.post('/portfolios', status_code=201)
def create_portfolio(payload: PortfolioInput, session: DB):
    portfolio = Portfolio(**payload.model_dump())
    session.add(portfolio)
    session.commit()
    return {'id': portfolio.id, 'name': portfolio.name}


@router.put('/portfolios/{portfolio_id}')
def rename_portfolio(portfolio_id: int, payload: PortfolioInput, session: DB):
    portfolio = get_portfolio(session, portfolio_id, lock=True)
    portfolio.name = payload.name
    session.commit()
    return {'id': portfolio.id, 'name': portfolio.name}


@router.get('/instruments/search')
def instrument_search(q: str, session: DB, category: str = 'ALL'):
    if not q.strip():
        raise HTTPException(422, 'Informe um símbolo ou nome para pesquisar.')
    if category not in {'ALL', 'LISTED', 'STOCK', 'ETF', 'CRYPTO'}:
        raise HTTPException(422, 'Unknown instrument category.')
    return search_instruments(session, q, category=category)


@router.get('/instruments/catalog')
def instrument_catalog(session: DB):
    return catalog_instruments(session)


@router.post('/instruments/custom', status_code=201)
def create_custom_instrument(payload: CustomInstrumentInput, session: DB):
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
    )
    session.commit()
    return {
        'id': instrument.id, 'symbol': instrument.symbol, 'name': instrument.name,
        'currency': instrument.currency, 'asset_type': instrument.asset_type,
        'exchange': instrument.exchange, 'status': instrument.status,
    }


@router.post('/instruments', status_code=201)
def select_instrument():
    raise HTTPException(410, 'Select a catalog instrument or use /instruments/custom; provider mappings are catalog-managed.')


@router.get('/portfolios/{portfolio_id}/overview')
def portfolio_overview(portfolio_id: int, session: DB):
    return get_overview(session, portfolio_id)


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
    instrument = require_instrument(
        session, payload.asset, payload.asset_currency, payload.instrument_id,
    )
    add_alias(session, instrument, payload.asset, 'manual-entry')
    ensure_asset_currency(session, portfolio_id, instrument.id, payload.asset_currency)
    ensure_asset(session, portfolio_id, instrument)
    values = transaction_values(session, payload)
    values['instrument_id'] = instrument.id
    transaction = Transaction(
        portfolio_id=portfolio_id, **values
    )
    session.add(transaction)
    session.flush()
    get_overview(session, portfolio_id)
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
    instrument = require_instrument(
        session, payload.asset, payload.asset_currency, payload.instrument_id,
    )
    add_alias(session, instrument, payload.asset, 'manual-entry')
    ensure_asset_currency(
        session, portfolio_id, instrument.id, payload.asset_currency
    )
    ensure_asset(session, portfolio_id, instrument)
    values = transaction_values(session, payload)
    values['instrument_id'] = instrument.id
    if transaction.trade_date == payload.trade_date:
        values['date_time'] = transaction.date_time
    for key, value in values.items():
        setattr(transaction, key, value)
    session.flush()
    get_overview(session, portfolio_id)
    session.commit()
    return transaction


@router.delete('/portfolios/{portfolio_id}/transactions/{transaction_id}', status_code=204)
def delete_transaction(portfolio_id: int, transaction_id: int, session: DB):
    get_portfolio(session, portfolio_id, lock=True)
    session.delete(find_transaction(session, portfolio_id, transaction_id))
    session.flush()
    get_overview(session, portfolio_id)
    session.commit()


@router.get('/transactions/import-template.xlsx')
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
    instrument = require_instrument(session, payload.asset, payload.asset_currency, payload.instrument_id)
    ensure_asset_currency(session, portfolio_id, instrument.id, payload.asset_currency)
    values = transaction_values(session, payload)
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
    for row in payload.rows:
        instrument = require_instrument(
            session, row.asset, row.asset_currency, row.instrument_id,
        )
        ensure_asset_currency(session, portfolio_id, instrument.id, row.asset_currency)
        ensure_asset(session, portfolio_id, instrument)
        add_alias(session, instrument, row.asset, 'import')
        values = transaction_values(session, row)
        values['instrument_id'] = instrument.id
        session.add(Transaction(
            portfolio_id=portfolio_id, **values
        ))
    session.flush()
    get_overview(session, portfolio_id)
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
            payload.dividends, payload.stock_splits,
        )
    except ValueError as error:
        raise HTTPException(422, str(error))
    session.commit()
    return {'saved': 1}


@router.get('/portfolios/{portfolio_id}/assets/{asset_id}/quote')
def latest_quote(portfolio_id: int, asset_id: int, session: DB):
    asset = get_asset(session, portfolio_id, asset_id)
    result = get_latest(session, asset)
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
    latest = get_latest(session, asset)
    session.commit()
    if (result is not None and not result.complete) or not latest.available or latest.stale:
        raise HTTPException(
            502,
            'Não foi possível obter cotações. Verifique o ticker ou registre uma '
            'cotação manual; os dados anteriores foram mantidos.',
        )
    return {
        'received': len(result.prices) if result is not None else 0,
        'latest_available': latest.available,
        'message': 'Histórico atualizado. Cotações manuais foram preservadas.',
    }


@router.get('/portfolios/{portfolio_id}/performance')
def performance(
    portfolio_id: int,
    session: DB,
    asset_id: int,
    broker: str,
    allocation_class: str,
):
    asset = get_asset(session, portfolio_id, asset_id)
    transactions = list(session.scalars(select(Transaction).where(
        Transaction.portfolio_id == portfolio_id,
        Transaction.instrument_id == asset.instrument_id,
        Transaction.broker == broker,
        Transaction.allocation_class == allocation_class,
    )))
    return historical_profitability(transactions, get_stored_history(session, asset))


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
