"""Resolve stored market and FX inputs for the pure position ledger."""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.corporate_actions import get_stored_actions
from src.domain import ZERO, decimal, position_history, position_now, summary_totals, transaction_date
from src.market_prices import history_for_reporting
from src.models import Asset, Portfolio, PositionSnapshot, Transaction
from src.rates import RateUnavailable, convert_amount


def sources(session, portfolio_id):
    from src.services import get_portfolio
    portfolio = get_portfolio(session, portfolio_id)
    transactions = list(session.scalars(select(Transaction).where(
        Transaction.portfolio_id == portfolio_id).order_by(Transaction.trade_date, Transaction.id)))
    assets = list(session.scalars(select(Asset).where(
        Asset.portfolio_id == portfolio_id).options(joinedload(Asset.instrument))))
    return portfolio, transactions, assets


def reporting_factors(session, display_currency, transactions, events, prices, *, read_only=True):
    """Return dated conversion factors, leaving unavailable rates absent."""
    factors = {}
    fetcher = (lambda *_: []) if read_only else None
    for row in transactions:
        key = (row.transaction_currency, row.settlement_date)
        if row.transaction_currency == display_currency:
            factors[key] = Decimal('1')
        elif display_currency == 'BRL' and row.fx_rate is not None:
            factors[('transaction', row.id)] = decimal(row.fx_rate)
        elif row.settlement_date <= date.today():
            try:
                factors[('transaction', row.id)] = convert_amount(
                    session, row.fx_rate, 'BRL', display_currency,
                    row.settlement_date, fetcher=fetcher)
            except RateUnavailable:
                pass
    for event in events:
        if event.event_type not in {'DIVIDEND', 'JCP', 'AMORTIZATION'} or not event.currency:
            continue
        key = (event.currency, event.effective_date)
        if key not in factors and event.effective_date <= date.today():
            try:
                factors[key] = convert_amount(session, Decimal('1'), event.currency,
                                              display_currency, event.effective_date, fetcher=fetcher)
            except RateUnavailable:
                pass
    for quote in prices:
        if quote is None:
            continue
        key = (quote.currency, quote.date)
        if key not in factors and quote.date <= date.today():
            try:
                factors[key] = convert_amount(session, Decimal('1'), quote.currency,
                                              display_currency, quote.date, fetcher=fetcher)
            except RateUnavailable:
                pass
    return factors


def get_overview(session, portfolio_id):
    portfolio, transactions, assets = sources(session, portfolio_id)
    positions = []
    asset_rows = []
    missing_prices = []
    missing_fx = []
    missing_cost_fx = []
    for asset in assets:
        rows = [row for row in transactions if row.instrument_id == asset.instrument_id]
        if not rows:
            continue
        events = get_stored_actions(session, asset)
        prices = history_for_reporting(session, asset)
        latest = prices[-1] if prices else None
        rates = reporting_factors(session, portfolio.display_currency, rows, events,
                                  [latest] if latest else [])
        current = position_now(rows, events, latest, portfolio.display_currency, rates)
        quote_valid = latest is not None and current['date'] is not None
        native_currency = asset.instrument.currency
        native_state = None
        if native_currency:
            if native_currency == portfolio.display_currency:
                native_state = current
            else:
                native_rates = reporting_factors(session, native_currency, rows, events,
                                                 [latest] if latest else [])
                native_state = position_now(rows, events, latest, native_currency, native_rates)
        native_cost = native_state['remaining_acquisition_cost'] if native_state else None
        native_average = native_state['average_cost'] if native_state else None
        quote_currency = latest.currency if latest else None
        native_value = (native_state['market_value'] if native_state else
                        current['quantity'] * decimal(latest.close)
                        if quote_valid and current['quantity'] else
                        ZERO if current['quantity'] == 0 else None)
        native_price = (native_state['current_price'] if native_state else
                        decimal(latest.close) if quote_valid else None)
        currencies = {row.transaction_currency for row in rows}
        position_currency = next(iter(currencies)) if len(currencies) == 1 else None
        acquisition = current['remaining_acquisition_cost']
        market = current['market_value']
        if 'missing_price' in current['status']:
            missing_prices.append(asset.instrument.symbol)
        if 'missing_fx' in current['status']:
            missing_fx.append(asset.instrument.symbol)
        if acquisition is None:
            missing_cost_fx.append(asset.instrument.symbol)
        allocations = {row.allocation_class for row in rows}
        state = {
            'asset_id': asset.id, 'asset': asset.instrument.symbol,
            'native_currency': native_currency, 'quote_currency': quote_currency,
            'transaction_currency': position_currency,
            'display_currency': portfolio.display_currency,
            'broker': ', '.join(sorted({row.broker for row in rows})),
            'allocation_class': next(iter(allocations)) if len(allocations) == 1 else 'Múltiplas classes',
            'broker_breakdown': current['broker_breakdown'],
            'quantity': current['quantity'], 'average_cost': current['average_cost'],
            'acquisition_cost': acquisition, 'display_average_cost': current['average_cost'],
            'display_acquisition_cost': acquisition,
            'native_acquisition_cost': native_cost, 'native_average_cost': native_average,
            'current_price': native_price, 'total_value': native_value,
            'display_price': current['current_price'], 'display_value': market,
            'realized_gain': current['realized_gain'], 'unrealized_gain': current['unrealized_gain'],
            'gross_income': current['gross_income'], 'current_total_gain': current['total_gain'],
            'current_accumulated_profitability': None,
            'income_by_currency': current['income_by_currency'],
            'corporate_action_count': len(events), 'price_date': latest.date if latest else None,
            'gain_date': latest.date if latest else None,
            'history_behind_transactions': bool(latest and latest.date < max(
                [transaction_date(row) for row in rows] + [event.effective_date for event in events]
            )), 'status': current['status'],
        }
        if portfolio.dirty_from is None and portfolio.history_built_through:
            snapshot = session.scalar(select(PositionSnapshot).where(
                PositionSnapshot.portfolio_id == portfolio_id,
                PositionSnapshot.instrument_id == asset.instrument_id,
                PositionSnapshot.date == portfolio.history_built_through,
            ))
            if snapshot is not None:
                state['current_accumulated_profitability'] = snapshot.cumulative_return_pct
                if latest is not None and latest.date == date.today() and snapshot.date == date.today() - timedelta(days=1):
                    today_rows = [row for row in rows if row.trade_date == date.today()]
                    today_events = [event for event in events if event.effective_date == date.today()]
                    current_day = position_history(
                        today_rows, today_events, [latest], portfolio.display_currency,
                        rates, start=date.today(), end=date.today(),
                        initial_state=snapshot.ledger_state,
                    )[0]
                    state['current_accumulated_profitability'] = current_day['cumulative_return_pct']
        positions.append(state)
        asset_rows.append({
            'id': asset.id, 'ticker': asset.instrument.symbol,
            'transaction_currency': position_currency,
            'quantity': state['quantity'], 'average_cost': state['average_cost'],
            'current_price': native_price, 'total_value': native_value,
            'price_date': state['price_date'], 'income_by_currency': current['income_by_currency'],
            'corporate_action_count': len(events), 'acquisition_cost': acquisition,
            'display_acquisition_cost': acquisition, 'display_average_cost': state['display_average_cost'],
            'display_value': market,
        })
    totals = summary_totals(positions)
    return {
        'positions': positions, 'assets': asset_rows,
        'summary': {
            'transactions': len(transactions), 'positions': len(positions), 'assets': len(asset_rows),
            'priced_value': totals['priced_value'],
            'total_value': totals['market_value'],
            'acquisition_cost': totals['acquisition_cost'],
            'realized_gain': totals['realized_gain'],
            'unrealized_gain': totals['unrealized_gain'],
            'total_gain': totals['total_gain'],
            'missing_prices': missing_prices, 'missing_fx': missing_fx,
            'missing_cost_fx': missing_cost_fx,
            'display_currency': portfolio.display_currency,
            'currencies': sorted({row.transaction_currency for row in transactions}),
            'totals_by_currency': {},
            'income_by_currency': ({portfolio.display_currency: totals['gross_income']}
                                   if totals['gross_income'] is not None else {}),
            'gross_income': totals['gross_income'],
            'history_status': 'pending' if portfolio.dirty_from or portfolio.history_built_through is None else 'complete',
            'dirty_from': portfolio.dirty_from,
        },
        'methodology': ('Valores e ganho na moeda de exibição, com FX da data de cada operação, '
                        'evento e cotação; taxas incluídas; retorno histórico ponderado no tempo.'),
    }
