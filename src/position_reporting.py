"""Resolve stored market and FX inputs for the pure position ledger."""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.corporate_actions import get_stored_actions, missing_action_ranges
from src.domain import ZERO, decimal, position_history, position_now, summary_totals, transaction_date
from src.market_prices import history_for_reporting, quote_refresh_required
from src.models import Asset, Portfolio, PortfolioSnapshot, PositionSnapshot, Transaction
from src.fixed_income import list_lots, position_valuations
from src.rates import RateUnavailable, convert_amount


def sources(session, portfolio_id):
    from src.services import get_portfolio
    portfolio = get_portfolio(session, portfolio_id)
    transactions = list(session.scalars(select(Transaction).where(
        Transaction.portfolio_id == portfolio_id).order_by(Transaction.trade_date, Transaction.id)))
    assets = list(session.scalars(select(Asset).where(
        Asset.portfolio_id == portfolio_id).options(joinedload(Asset.instrument))))
    return portfolio, transactions, assets


def reporting_factors(session, display_currency, transactions, events, prices, *, read_only=True,
                      valuation_date=None):
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
        fx_date = valuation_date if valuation_date is not None else quote.date
        key = (quote.currency, fx_date)
        if key not in factors and fx_date <= date.today():
            try:
                factors[key] = convert_amount(session, Decimal('1'), quote.currency,
                                              display_currency, fx_date, fetcher=fetcher)
            except RateUnavailable:
                pass
    return factors


def get_overview(session, portfolio_id):
    portfolio, transactions, assets = sources(session, portfolio_id)
    fixed_income_lots = list_lots(session, portfolio_id)
    valuation_date = date.today()
    positions = []
    asset_rows = []
    missing_prices = []
    missing_fx = []
    missing_cost_fx = []
    missing_actions = []
    for asset in assets:
        rows = [row for row in transactions if row.instrument_id == asset.instrument_id]
        if not rows:
            continue
        events = get_stored_actions(session, asset, end=valuation_date)
        action_gaps = missing_action_ranges(session, asset, min(row.trade_date for row in rows), valuation_date)
        if action_gaps:
            missing_actions.append(asset.instrument.symbol)
        prices = [price for price in history_for_reporting(session, asset) if price.date <= valuation_date]
        latest = prices[-1] if prices else None
        rates = reporting_factors(session, portfolio.display_currency, rows, events,
                                  [latest] if latest else [], valuation_date=valuation_date)
        current = position_now(rows, events, latest, portfolio.display_currency, rates,
                               valuation_date=valuation_date, actions_complete=not action_gaps)
        quote_valid = latest is not None and current['quote_date'] is not None and not action_gaps
        native_currency = asset.instrument.currency
        native_state = None
        if native_currency:
            if native_currency == portfolio.display_currency:
                native_state = current
            else:
                native_rates = reporting_factors(session, native_currency, rows, events,
                                                 [latest] if latest else [], valuation_date=valuation_date)
                native_state = position_now(rows, events, latest, native_currency, native_rates,
                                            valuation_date=valuation_date, actions_complete=not action_gaps)
        native_cost = native_state['remaining_acquisition_cost'] if native_state else None
        native_average = native_state['average_cost'] if native_state else None
        native_income = native_state['gross_income'] if native_state else None
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
            'native_gross_income': native_income,
            'current_accumulated_profitability': None,
            'return_date': None,
            'income_by_currency': current['income_by_currency'],
            'corporate_action_count': len(events), 'price_date': latest.date if latest else None,
            'gain_date': valuation_date, 'valuation_date': valuation_date,
            'action_coverage_through': action_gaps[0][0] - timedelta(days=1) if action_gaps else valuation_date,
            'quote_refresh_required': quote_refresh_required(latest) if current['quantity'] else False,
            'history_behind_transactions': bool(latest and latest.date < max(
                [transaction_date(row) for row in rows] + [event.effective_date for event in events]
            )), 'status': current['status'],
        }
        if portfolio.dirty_from is None and portfolio.history_built_through:
            snapshot = session.scalar(select(PositionSnapshot).where(
                PositionSnapshot.portfolio_id == portfolio_id,
                PositionSnapshot.instrument_id == asset.instrument_id,
                PositionSnapshot.date == portfolio.history_built_through,
                PositionSnapshot.reporting_currency == portfolio.display_currency,
            ))
            if snapshot is not None:
                state['current_accumulated_profitability'] = snapshot.cumulative_return_pct
                state['return_date'] = snapshot.date
                if snapshot.date == valuation_date - timedelta(days=1):
                    today_rows = [row for row in rows if row.trade_date == date.today()]
                    today_events = [event for event in events if event.effective_date == date.today()]
                    current_day = position_history(
                        today_rows, today_events, [latest] if latest else [], portfolio.display_currency,
                        rates, start=date.today(), end=date.today(),
                        initial_state=snapshot.ledger_state,
                        missing_action_ranges=action_gaps,
                    )[0]
                    state['current_accumulated_profitability'] = current_day['cumulative_return_pct']
                    state['return_date'] = date.today()
                if action_gaps:
                    state['current_accumulated_profitability'] = None
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
    fixed_positions = position_valuations(session, fixed_income_lots, valuation_date,
                                          portfolio.display_currency)
    for item in fixed_positions:
        positions.append({
            **item, 'position_type': 'FIXED_INCOME', 'native_currency': item['currency'],
            'quote_currency': None, 'transaction_currency': item['currency'],
            'broker': ', '.join(sorted({row.broker.name for row in fixed_income_lots
                                       if row.asset_id == item['asset_id']
                                       and row.start_date <= valuation_date})),
            'allocation_class': 'Renda fixa', 'quantity': None, 'average_cost': None,
            'current_price': None, 'total_value': None, 'display_price': None,
            'display_average_cost': None, 'display_acquisition_cost': item['acquisition_cost'],
            'native_average_cost': None, 'native_acquisition_cost': None,
            'native_gross_income': None, 'current_accumulated_profitability': None,
            'return_date': None, 'income_by_currency': {}, 'corporate_action_count': 0,
            'price_date': None, 'gain_date': valuation_date,
            'history_behind_transactions': False, 'quote_refresh_required': False,
        })
        asset_rows.append({
            'id': item['asset_id'], 'ticker': item['asset'], 'transaction_currency': item['currency'],
            'quantity': None, 'average_cost': None, 'current_price': None,
            'total_value': None, 'price_date': None, 'income_by_currency': {},
            'corporate_action_count': 0,
        })
    totals = summary_totals(positions)
    latest_snapshot_status = None
    if portfolio.history_built_through is not None:
        latest_snapshot = session.scalar(select(PortfolioSnapshot).where(
            PortfolioSnapshot.portfolio_id == portfolio_id,
            PortfolioSnapshot.date == portfolio.history_built_through,
            PortfolioSnapshot.reporting_currency == portfolio.display_currency,
        ))
        latest_snapshot_status = latest_snapshot.status if latest_snapshot else None
    result = {
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
            'missing_actions': missing_actions,
            'display_currency': portfolio.display_currency,
            'currencies': sorted({row.transaction_currency for row in transactions} |
                                 {lot.currency for lot in fixed_income_lots}),
            'totals_by_currency': {},
            'income_by_currency': ({portfolio.display_currency: totals['gross_income']}
                                   if totals['gross_income'] is not None else {}),
            'gross_income': totals['gross_income'],
            'history_status': ('complete' if not transactions and not fixed_income_lots else
                               'pending' if portfolio.dirty_from or portfolio.history_built_through is None
                               else 'complete' if latest_snapshot_status == 'complete' else 'incomplete'),
            'dirty_from': portfolio.dirty_from,
        },
        'methodology': ('Valores e ganho na moeda de exibição, com FX da data de cada operação, '
                        'evento e avaliação; taxas incluídas. Retorno diário encadeado, com compras '
                        'no capital do dia. Dias sem negociação usam a última cotação disponível; '
                        'sua data é indicada no histórico. Ganho monetário e retorno percentual '
                        'podem ter sinais diferentes após aportes e variações cambiais.'),
    }
    if fixed_income_lots:
        result['fixed_income'] = {
            'lot_count': len(fixed_income_lots),
            'valuation_status': 'complete' if all(row['status'] == 'complete' for row in fixed_positions) else 'incomplete',
            'lots': [value for position in fixed_positions for value in position['lots']],
            'positions': fixed_positions,
        }
        if any(row['status'] != 'complete' for row in fixed_positions):
            result['summary']['history_status'] = 'incomplete' if portfolio.dirty_from is None else 'pending'
    else:
        result['fixed_income'] = {'lot_count': 0, 'valuation_status': 'none', 'lots': []}
    return result
