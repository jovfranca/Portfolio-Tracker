from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from src.models import Portfolio, Asset, Transaction
from src.domain import overview


def get_portfolio(session, portfolio_id, lock=False):
    query = select(Portfolio).where(Portfolio.id == portfolio_id)
    if lock:
        query = query.with_for_update()
    portfolio = session.scalar(query)
    if portfolio is None:
        raise HTTPException(404, 'Carteira não encontrada.')
    return portfolio


def get_asset(session, portfolio_id, asset_id):
    get_portfolio(session, portfolio_id)
    asset = session.scalar(select(Asset).where(Asset.id == asset_id, Asset.portfolio_id == portfolio_id))
    if asset is None:
        raise HTTPException(404, 'Ativo não encontrado nesta carteira.')
    return asset


def ensure_asset(session, portfolio_id, ticker):
    asset = session.scalar(select(Asset).where(Asset.portfolio_id == portfolio_id, Asset.ticker == ticker))
    if asset is None:
        asset = Asset(portfolio_id=portfolio_id, ticker=ticker)
        session.add(asset)
        session.flush()
    return asset


def get_overview(session, portfolio_id):
    get_portfolio(session, portfolio_id)
    transactions = list(session.scalars(select(Transaction).where(Transaction.portfolio_id == portfolio_id)
                                       .order_by(Transaction.date_time, Transaction.id)))
    assets = list(session.scalars(select(Asset).where(Asset.portfolio_id == portfolio_id)
                                 .options(selectinload(Asset.history))))
    return overview(transactions, assets)
