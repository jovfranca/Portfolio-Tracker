from datetime import datetime, time
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from src.models import Portfolio, Asset, Transaction
from src.domain import overview
from src.market_prices import ensure_instrument, history_for_domain
from src.rates import get_rates


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


def ensure_asset(session, portfolio_id, ticker, currency='BRL'):
    asset = session.scalar(select(Asset).where(Asset.portfolio_id == portfolio_id, Asset.ticker == ticker))
    if asset is None:
        instrument = ensure_instrument(session, ticker, currency)
        asset = Asset(portfolio_id=portfolio_id, ticker=ticker, instrument_id=instrument.id)
        session.add(asset)
        session.flush()
    elif asset.instrument.currency != currency:
        raise HTTPException(422, f'O ativo {ticker} já está registrado em {asset.instrument.currency}.')
    return asset


def ensure_asset_currency(session, portfolio_id, ticker, currency, exclude_id=None):
    query = select(Transaction.asset_currency).where(
        Transaction.portfolio_id == portfolio_id,
        Transaction.asset == ticker,
    )
    if exclude_id is not None:
        query = query.where(Transaction.id != exclude_id)
    existing = session.scalar(query.limit(1))
    if existing is not None and existing != currency:
        raise HTTPException(
            422,
            f'O ativo {ticker} já está registrado em {existing}; não misture moedas no mesmo ticker.',
        )


def transaction_values(session, payload):
    """Resolve and freeze values that every saved transaction must carry."""
    values = payload.model_dump()
    if values['fx_rate'] is None:
        rates = get_rates(session, values['asset_currency'], 'FX', values['settlement_date'])
        values['fx_rate'] = next(rate.rate for rate in rates if rate.rate_side == 'MARKET')
    values['date_time'] = datetime.combine(values['trade_date'], time.min)
    return values


def get_overview(session, portfolio_id):
    get_portfolio(session, portfolio_id)
    transactions = list(session.scalars(select(Transaction).where(Transaction.portfolio_id == portfolio_id)
                                       .order_by(Transaction.trade_date, Transaction.id)))
    assets = list(session.scalars(select(Asset).where(Asset.portfolio_id == portfolio_id)
                                 .options(joinedload(Asset.instrument))))
    calculation_assets = [
        SimpleNamespace(id=asset.id, ticker=asset.ticker, history=history_for_domain(session, asset))
        for asset in assets
    ]
    return overview(transactions, calculation_assets)
