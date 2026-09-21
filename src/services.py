from datetime import datetime, time
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


def require_instrument(session, identifier, currency, instrument_id=None):
    resolution = resolve_instrument(
        session, identifier, currency=currency, instrument_id=instrument_id,
    )
    if resolution.status == 'ambiguous':
        raise HTTPException(422, f'O identificador {identifier} corresponde a mais de um instrumento.')
    if resolution.status == 'unresolved':
        raise HTTPException(
            422,
            f'O instrumento {identifier} não foi resolvido. Pesquise e selecione um instrumento antes de salvar.',
        )
    if resolution.instrument.asset_type in ('STOCK', 'ETF') and resolution.instrument.currency and resolution.instrument.currency != currency:
        raise HTTPException(
            422,
            f'A moeda nativa desta ação/ETF é {resolution.instrument.currency}; '
            'a moeda da transação deve coincidir.',
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


def ensure_asset_currency(session, portfolio_id, instrument_id, currency):
    query = select(Transaction.asset_currency).where(
        Transaction.portfolio_id == portfolio_id,
        Transaction.instrument_id == instrument_id,
    )
    existing = set(session.scalars(query.distinct()))
    if existing and existing != {currency}:
        raise HTTPException(
            422,
            f'O instrumento já está registrado em {", ".join(sorted(existing))}; não misture moedas na mesma posição.',
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
        SimpleNamespace(
            id=asset.id, instrument_id=asset.instrument_id,
            ticker=asset.instrument.symbol, history=history_for_domain(session, asset),
        )
        for asset in assets
    ]
    return overview(transactions, calculation_assets)
