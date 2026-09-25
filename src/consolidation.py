"""Materialize daily reporting views from source transactions, events and prices."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import delete, event, inspect, select
from sqlalchemy.orm import Session

from src.corporate_actions import get_stored_actions
from src.domain import ZERO, portfolio_day, position_history, position_now
from src.market_prices import get_latest, history_for_reporting
from src.models import (
    Asset, CorporateAction, ExchangeRate, MarketPrice, Portfolio,
    PortfolioSnapshot, PositionSnapshot, ProviderInstrument, Transaction,
    UserCorporateEvent, UserDefinedPrice,
)
from src.position_reporting import reporting_factors, sources
from src.rates import RateUnavailable, convert_amount


POSITION_FIELDS = (
    'quantity', 'remaining_acquisition_cost', 'average_cost', 'market_value',
    'realized_gain', 'unrealized_gain', 'gross_income', 'total_gain',
    'net_flow', 'purchases', 'daily_income', 'daily_return_pct', 'cumulative_return_pct',
)
PORTFOLIO_FIELDS = (
    'remaining_acquisition_cost', 'market_value', 'realized_gain',
    'unrealized_gain', 'gross_income', 'total_gain',
)


def mark_dirty(session, portfolio_id, day):
    """Keep the earliest affected date across an edit batch."""
    portfolio = session.get(Portfolio, portfolio_id)
    if portfolio is not None:
        portfolio.dirty_from = min(portfolio.dirty_from, day) if portfolio.dirty_from else day


@event.listens_for(Session, 'before_flush')
def invalidate_changed_inputs(session, flush_context, instances):
    """Catch API, import and provider writes in one place, including old edit dates."""
    affected = {}

    def add(portfolio_id, day):
        if portfolio_id is not None and day is not None:
            affected[portfolio_id] = min(affected[portfolio_id], day) if portfolio_id in affected else day

    def old_day(obj, field):
        history = inspect(obj).attrs[field].history
        return min([getattr(obj, field)] + list(history.deleted))

    for obj in set(session.new) | set(session.dirty) | set(session.deleted):
        if isinstance(obj, Transaction):
            add(obj.portfolio_id, old_day(obj, 'trade_date'))
        elif isinstance(obj, (UserCorporateEvent, UserDefinedPrice)):
            asset = session.get(Asset, obj.asset_id)
            if asset is not None:
                add(asset.portfolio_id, old_day(obj, 'effective_date' if isinstance(obj, UserCorporateEvent)
                                                     else 'reference_date'))
        elif isinstance(obj, (CorporateAction, MarketPrice)):
            if isinstance(obj, CorporateAction):
                instrument_id, day = obj.instrument_id, old_day(obj, 'effective_date')
            else:
                mapping = session.get(ProviderInstrument, obj.provider_instrument_id)
                instrument_id = mapping.instrument_id if mapping else None
                day = obj.reference_at.date() if obj.reference_at else None
            if instrument_id is not None:
                for portfolio_id in session.scalars(select(Asset.portfolio_id).where(
                    Asset.instrument_id == instrument_id).distinct()):
                    add(portfolio_id, day)
        elif isinstance(obj, ExchangeRate):
            connection = session.connection()
            translated_schema = connection.get_execution_options().get('schema_translate_map', {}).get(None)
            if obj.rate_type == 'FX' and inspect(connection).has_table('portfolios', schema=translated_schema):
                affected_portfolios = set(session.scalars(select(Portfolio.id).where(
                    Portfolio.display_currency == obj.currency)))
                affected_portfolios.update(session.scalars(select(Transaction.portfolio_id).where(
                    Transaction.transaction_currency == obj.currency).distinct()))
                affected_portfolios.update(session.scalars(select(Asset.portfolio_id).join(
                    ProviderInstrument, ProviderInstrument.instrument_id == Asset.instrument_id,
                ).where(ProviderInstrument.quote_currency == obj.currency).distinct()))
                affected_portfolios.update(session.scalars(select(Asset.portfolio_id).join(
                    CorporateAction, CorporateAction.instrument_id == Asset.instrument_id,
                ).where(CorporateAction.currency == obj.currency).distinct()))
                for model in (UserCorporateEvent, UserDefinedPrice):
                    affected_portfolios.update(session.scalars(select(Asset.portfolio_id).join(
                        model, model.asset_id == Asset.id,
                    ).where(model.currency == obj.currency).distinct()))
                for portfolio_id in affected_portfolios:
                    add(portfolio_id, old_day(obj, 'reference_date'))
                # Settlement FX is applied when the trade enters the ledger.
                # Replaying only from settlement would retain its old cost basis.
                for portfolio_id, trade_day in session.execute(select(
                    Transaction.portfolio_id, Transaction.trade_date,
                ).join(Portfolio, Portfolio.id == Transaction.portfolio_id).where(
                    Portfolio.display_currency == obj.currency,
                    Transaction.transaction_currency != Portfolio.display_currency,
                    Transaction.trade_date < old_day(obj, 'reference_date'),
                    Transaction.settlement_date >= old_day(obj, 'reference_date'),
                )):
                    add(portfolio_id, trade_day)
        elif isinstance(obj, Portfolio) and inspect(obj).attrs.display_currency.history.has_changes():
            earliest = session.scalar(select(Transaction.trade_date).where(
                Transaction.portfolio_id == obj.id).order_by(Transaction.trade_date).limit(1))
            add(obj.id, earliest)
    for portfolio_id, day in affected.items():
        mark_dirty(session, portfolio_id, day)


def _position_values(snapshot):
    return {
        'date': snapshot.date, 'reporting_currency': snapshot.reporting_currency,
        'status': snapshot.status,
        **{field: getattr(snapshot, field) for field in POSITION_FIELDS},
    }


def position_series(session, portfolio_id, instrument_id):
    from src.services import get_portfolio
    portfolio = get_portfolio(session, portfolio_id)
    rows = session.scalars(select(PositionSnapshot).where(
        PositionSnapshot.portfolio_id == portfolio_id,
        PositionSnapshot.instrument_id == instrument_id,
        PositionSnapshot.reporting_currency == portfolio.display_currency,
    ).order_by(PositionSnapshot.date))
    return [_position_values(row) for row in rows]


def portfolio_series(session, portfolio_id):
    from src.services import get_portfolio
    portfolio = get_portfolio(session, portfolio_id)
    rows = session.scalars(select(PortfolioSnapshot).where(
        PortfolioSnapshot.portfolio_id == portfolio_id,
        PortfolioSnapshot.reporting_currency == portfolio.display_currency,
    ).order_by(PortfolioSnapshot.date))
    return [{
        'date': row.date, 'reporting_currency': row.reporting_currency,
        'status': row.status,
        # Summing share counts or averaging unit costs across instruments would
        # invent a portfolio-wide unit; expose these as inapplicable instead.
        'quantity': None, 'average_cost': None,
        **{field: getattr(row, field) for field in PORTFOLIO_FIELDS},
        'daily_return_pct': row.daily_return_pct,
        'cumulative_return_pct': row.cumulative_return_pct,
    } for row in rows]


def consolidate(session, portfolio_id):
    from src.services import get_portfolio
    portfolio = get_portfolio(session, portfolio_id, lock=True)
    _, transactions, assets = sources(session, portfolio_id)
    if not transactions:
        session.execute(delete(PositionSnapshot).where(PositionSnapshot.portfolio_id == portfolio_id))
        session.execute(delete(PortfolioSnapshot).where(PortfolioSnapshot.portfolio_id == portfolio_id))
        portfolio.dirty_from = None
        portfolio.history_built_through = None
        session.flush()
        return {'complete': True, 'history_status': 'complete', 'recalculated_from': None,
                'incomplete_assets': [], 'snapshot_days': 0}

    first_day = min(row.trade_date for row in transactions)
    # Removing or moving the earliest trade advances the history boundary.
    # Rows before the new boundary cannot be derived from the remaining source.
    session.execute(delete(PositionSnapshot).where(
        PositionSnapshot.portfolio_id == portfolio_id,
        PositionSnapshot.date < first_day,
    ))
    session.execute(delete(PortfolioSnapshot).where(
        PortfolioSnapshot.portfolio_id == portfolio_id,
        PortfolioSnapshot.date < first_day,
    ))
    through = date.today() - timedelta(days=1)
    dirty = portfolio.dirty_from
    start = max(first_day, dirty or (portfolio.history_built_through + timedelta(days=1)
                                     if portfolio.history_built_through else first_day))
    if portfolio.history_built_through is None:
        start = first_day
    if start > through:
        start = through + timedelta(days=1)
    incomplete = []
    history_incomplete = []
    by_instrument = defaultdict(list)
    for row in transactions:
        by_instrument[row.instrument_id].append(row)
    for asset in assets:
        rows = by_instrument.get(asset.instrument_id, [])
        if not rows:
            session.execute(delete(PositionSnapshot).where(
                PositionSnapshot.portfolio_id == portfolio_id,
                PositionSnapshot.instrument_id == asset.instrument_id))
            continue
        events = get_stored_actions(session, asset)
        if position_now(rows, events, None, portfolio.display_currency, {})['quantity'] > 0:
            try:
                # The shared quote service handles TTL and provider errors. One
                # failed asset never prevents the remaining portfolio from updating.
                latest = get_latest(session, asset)
                if latest.price is None or latest.stale:
                    incomplete.append(asset.instrument.symbol)
            except (ValueError, RuntimeError, OSError):
                incomplete.append(asset.instrument.symbol)
        prices = history_for_reporting(session, asset)
        if prices and prices[-1].currency != portfolio.display_currency:
            try:
                convert_amount(session, Decimal('1'), prices[-1].currency,
                               portfolio.display_currency, prices[-1].date)
            except RateUnavailable:
                if asset.instrument.symbol not in incomplete:
                    incomplete.append(asset.instrument.symbol)
        if start > through:
            continue
        previous = session.scalar(select(PositionSnapshot).where(
            PositionSnapshot.portfolio_id == portfolio_id,
            PositionSnapshot.instrument_id == asset.instrument_id,
            PositionSnapshot.date == start - timedelta(days=1),
            PositionSnapshot.reporting_currency == portfolio.display_currency,
        ))
        asset_start = start if previous else min(row.trade_date for row in rows)
        activity_rows = [row for row in rows if row.trade_date >= asset_start]
        activity_events = [event for event in events if event.effective_date >= asset_start]
        active_prices = [price for price in prices if price.date <= through]
        factors = reporting_factors(session, portfolio.display_currency,
                                    activity_rows, activity_events, active_prices)
        # Weekend carry-forward uses the prior close with the relevant day's FX.
        currencies = {price.currency for price in active_prices}
        day = asset_start
        while day <= through:
            if day.weekday() >= 5:
                for currency in currencies:
                    key = (currency, day)
                    if key not in factors:
                        try:
                            factors[key] = convert_amount(session, Decimal('1'), currency,
                                                          portfolio.display_currency, day,
                                                          fetcher=lambda *_: [])
                        except RateUnavailable:
                            pass
            day += timedelta(days=1)
        series = position_history(
            activity_rows, activity_events, active_prices, portfolio.display_currency,
            factors, start=asset_start, end=through,
            initial_state=previous.ledger_state if previous else None,
        )
        session.execute(delete(PositionSnapshot).where(
            PositionSnapshot.portfolio_id == portfolio_id,
            PositionSnapshot.instrument_id == asset.instrument_id,
            PositionSnapshot.date >= min(start, asset_start),
        ))
        for item in series:
            session.add(PositionSnapshot(
                portfolio_id=portfolio_id, instrument_id=asset.instrument_id,
                date=item['date'], reporting_currency=portfolio.display_currency,
                status=item['status'], ledger_state=item['ledger_state'],
                **{field: item[field] for field in POSITION_FIELDS},
            ))
        if any(item['status'] != 'complete' for item in series):
            history_incomplete.append(asset.instrument.symbol)
            if asset.instrument.symbol not in incomplete:
                incomplete.append(asset.instrument.symbol)
    session.flush()
    if start <= through:
        previous_portfolio = session.scalar(select(PortfolioSnapshot).where(
            PortfolioSnapshot.portfolio_id == portfolio_id,
            PortfolioSnapshot.date == start - timedelta(days=1),
            PortfolioSnapshot.reporting_currency == portfolio.display_currency,
        ))
        previous_value = previous_portfolio.market_value if previous_portfolio else ZERO
        factor = previous_portfolio.return_factor if previous_portfolio else Decimal('1')
        session.execute(delete(PortfolioSnapshot).where(
            PortfolioSnapshot.portfolio_id == portfolio_id,
            PortfolioSnapshot.date >= start,
        ))
        day = start
        while day <= through:
            daily_rows = list(session.scalars(select(PositionSnapshot).where(
                PositionSnapshot.portfolio_id == portfolio_id,
                PositionSnapshot.date == day,
            )))
            values = portfolio_day(daily_rows, previous_value, factor)
            session.add(PortfolioSnapshot(
                portfolio_id=portfolio_id, date=day,
                reporting_currency=portfolio.display_currency,
                **values,
            ))
            previous_value = values['market_value']
            factor = values['return_factor']
            day += timedelta(days=1)
        portfolio.history_built_through = through
    portfolio.dirty_from = None if not history_incomplete else dirty or start
    session.flush()
    return {
        'complete': not incomplete,
        'history_status': 'complete' if not history_incomplete else 'incomplete',
        'recalculated_from': start if start <= through else None,
        'incomplete_assets': sorted(set(incomplete)),
        'snapshot_days': (through - start).days + 1 if start <= through else 0,
        'message': ('Consolidação parcial: ' + ', '.join(sorted(set(incomplete)))
                    if incomplete else 'Carteira consolidada.'),
    }
