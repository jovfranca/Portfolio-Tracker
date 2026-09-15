"""HTTP routes for portfolios, transactions and market data."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.api.market_data import fetch_history
from src.database import get_session
from src.domain import historical_profitability
from src.models import AssetHistory, Portfolio, Transaction
from src.schemas import PortfolioInput, QuoteInput, TransactionInput, TransactionOutput
from src.services import ensure_asset, get_asset, get_overview, get_portfolio


router = APIRouter(prefix='/api')
DB = Annotated[Session, Depends(get_session)]


@router.get('/health')
def health(session: DB):
    session.execute(text('SELECT 1'))
    session.execute(select(Portfolio.id).limit(1))
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


@router.get('/portfolios/{portfolio_id}/overview')
def portfolio_overview(portfolio_id: int, session: DB):
    return get_overview(session, portfolio_id)


@router.get('/portfolios/{portfolio_id}/transactions', response_model=list[TransactionOutput])
def transactions(portfolio_id: int, session: DB):
    get_portfolio(session, portfolio_id)
    return list(session.scalars(
        select(Transaction)
        .where(Transaction.portfolio_id == portfolio_id)
        .order_by(Transaction.date_time.desc(), Transaction.id.desc())
    ))


@router.post(
    '/portfolios/{portfolio_id}/transactions',
    response_model=TransactionOutput,
    status_code=201,
)
def add_transaction(portfolio_id: int, payload: TransactionInput, session: DB):
    get_portfolio(session, portfolio_id, lock=True)
    ensure_asset(session, portfolio_id, payload.asset)
    transaction = Transaction(portfolio_id=portfolio_id, **payload.model_dump())
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
    payload: TransactionInput,
    session: DB,
):
    get_portfolio(session, portfolio_id, lock=True)
    transaction = find_transaction(session, portfolio_id, transaction_id)
    ensure_asset(session, portfolio_id, payload.asset)
    for key, value in payload.model_dump().items():
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
        }
        for history in asset.history
    ]


@router.put('/portfolios/{portfolio_id}/assets/{asset_id}/quote')
def save_quote(portfolio_id: int, asset_id: int, payload: QuoteInput, session: DB):
    get_portfolio(session, portfolio_id, lock=True)
    get_asset(session, portfolio_id, asset_id)
    values = payload.model_dump() | {'asset_id': asset_id, 'source': 'manual'}
    query = insert(AssetHistory).values(**values)
    session.execute(query.on_conflict_do_update(
        index_elements=['asset_id', 'date'],
        set_=values,
    ))
    session.commit()
    return {'saved': 1}


@router.post('/portfolios/{portfolio_id}/assets/{asset_id}/refresh')
def refresh_quotes(portfolio_id: int, asset_id: int, session: DB):
    asset = get_asset(session, portfolio_id, asset_id)
    transactions = list(session.scalars(select(Transaction).where(
        Transaction.portfolio_id == portfolio_id,
        Transaction.asset == asset.ticker,
    )))
    if not transactions:
        raise HTTPException(422, 'Cadastre uma transação antes de atualizar.')

    ticker = asset.ticker
    start = min(transaction.date_time.date() for transaction in transactions)
    session.rollback()
    try:
        rows = fetch_history(ticker, start)
    except Exception:
        raise HTTPException(
            502,
            'Não foi possível obter cotações. Verifique o ticker ou registre uma '
            'cotação manual; os dados anteriores foram mantidos.',
        )

    get_portfolio(session, portfolio_id, lock=True)
    get_asset(session, portfolio_id, asset_id)
    for row in rows:
        query = insert(AssetHistory).values(asset_id=asset_id, **row)
        session.execute(query.on_conflict_do_update(
            index_elements=['asset_id', 'date'],
            set_=row,
            where=AssetHistory.source != 'manual',
        ))
    session.commit()
    return {
        'received': len(rows),
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
        Transaction.asset == asset.ticker,
        Transaction.broker == broker,
        Transaction.allocation_class == allocation_class,
    )))
    return historical_profitability(transactions, asset.history)
