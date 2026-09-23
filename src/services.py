from datetime import datetime, time
from decimal import Decimal
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from src.models import Portfolio, Asset, Instrument, Transaction
from src.domain import overview
from src.instruments import resolve_instrument
from src.market_prices import history_for_domain
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


def require_instrument(session, identifier, instrument_id=None):
    resolution = resolve_instrument(session, identifier, instrument_id=instrument_id)
    if resolution.status == 'ambiguous':
        raise HTTPException(422, f'O identificador {identifier} corresponde a mais de um instrumento.')
    if resolution.status == 'unresolved':
        raise HTTPException(
            422,
            f'O instrumento {identifier} não foi resolvido. Pesquise e selecione um instrumento antes de salvar.',
        )
    return resolution.instrument


def ensure_asset(session, portfolio_id, instrument):
    if not isinstance(instrument, Instrument):
        raise TypeError('ensure_asset requires a canonical Instrument.')
    asset = session.scalar(select(Asset).where(
        Asset.portfolio_id == portfolio_id, Asset.instrument_id == instrument.id,
    ))
    if asset is None:
        asset = Asset(
            portfolio_id=portfolio_id, ticker=instrument.symbol,
            instrument_id=instrument.id,
        )
        session.add(asset)
        session.flush()
    return asset


def transaction_currency_for(instrument, supplied_currency):
    """Resolve a transaction currency without changing canonical identity."""
    if instrument.asset_type in ('STOCK', 'ETF'):
        if not instrument.currency:
            raise HTTPException(422, 'O instrumento listado não tem moeda nativa configurada.')
        if supplied_currency and supplied_currency != instrument.currency:
            raise HTTPException(422, f'A moeda nativa desta ação/ETF é {instrument.currency}.')
        return instrument.currency
    if not supplied_currency:
        raise HTTPException(422, 'Informe a moeda da transação.')
    return supplied_currency


def transaction_values(session, payload, transaction_currency=None):
    """Resolve and freeze values that every saved transaction must carry."""
    values = payload.model_dump()
    values['transaction_currency'] = transaction_currency or values['transaction_currency']
    if not values['transaction_currency']:
        raise ValueError('Informe a moeda da transação.')
    if values['transaction_currency'] == 'BRL':
        values['fx_rate'] = Decimal('1')
    elif values['fx_rate'] is None:
        rates = get_rates(session, values['transaction_currency'], 'FX', values['settlement_date'])
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
        SimpleNamespace(
            id=asset.id, instrument_id=asset.instrument_id,
            ticker=asset.instrument.symbol, transaction_currency=currency,
            history=history_for_domain(session, asset, currency=currency),
        )
        for asset in assets
        for currency in sorted({
            transaction.transaction_currency
            for transaction in transactions
            if transaction.instrument_id == asset.instrument_id
        })
    ]
    return overview(transactions, calculation_assets)
