"""Resolve stored market and FX inputs for the pure position ledger."""
from datetime import date, timedelta
from decimal import Decimal
from bisect import bisect_right

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.corporate_actions import get_stored_actions, missing_action_ranges
from src.domain import ZERO, decimal, position_history, position_now, summary_totals, transaction_date
from src.market_prices import history_for_reporting, quote_refresh_required
from src.models import Asset, ExchangeRate, PositionInvalidation, PositionSnapshot, Transaction
from src.config import rate_fallback_days
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


def historical_valuation_factors(session, quote_currencies, display_currency, days):
    """Read stored FX once and resolve each valuation day's carried rate."""
    if not days:
        return {}
    currencies = (set(quote_currencies) | {display_currency}) - {'BRL'}
    rows = list(session.scalars(select(ExchangeRate).where(
        ExchangeRate.rate_type == 'FX', ExchangeRate.rate_side == 'MARKET',
        ExchangeRate.currency.in_(currencies),
        ExchangeRate.reference_date >= min(days) - timedelta(days=rate_fallback_days()),
        ExchangeRate.reference_date <= max(days),
    ).order_by(ExchangeRate.currency, ExchangeRate.reference_date))) if currencies else []
    dates_by_currency = {}
    values_by_currency = {}
    for row in rows:
        dates_by_currency.setdefault(row.currency, []).append(row.reference_date)
        values_by_currency.setdefault(row.currency, []).append(row.rate)

    def brl_value(currency, day):
        if currency == 'BRL':
            return Decimal('1')
        dates = dates_by_currency.get(currency, ())
        index = bisect_right(dates, day) - 1
        if index < 0 or (day - dates[index]).days > rate_fallback_days():
            return None
        return values_by_currency[currency][index]

    factors = {}
    for day in days:
        target = brl_value(display_currency, day)
        for currency in quote_currencies:
            source = brl_value(currency, day)
            if currency == display_currency:
                factors[(currency, day)] = Decimal('1')
            elif source is not None and target is not None:
                factors[(currency, day)] = source / target
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
    history_states = []
    dirty_instruments = set(session.scalars(select(PositionInvalidation.instrument_id).where(
        PositionInvalidation.portfolio_id == portfolio_id)))
    for asset in assets:
        rows = [row for row in transactions if row.instrument_id == asset.instrument_id]
        if not rows:
            if asset.instrument_id not in dirty_instruments or portfolio.history_built_through is None:
                continue
            snapshot = session.scalar(select(PositionSnapshot).where(
                PositionSnapshot.portfolio_id == portfolio_id,
                PositionSnapshot.instrument_id == asset.instrument_id,
                PositionSnapshot.date == portfolio.history_built_through,
                PositionSnapshot.reporting_currency == 'BRL',
            ))
            if snapshot is None:
                continue
            prices = [price for price in history_for_reporting(session, asset)
                      if price.date <= valuation_date]
            latest = prices[-1] if prices else None
            display_price = None
            native_price = None
            if latest is not None:
                try:
                    display_price = convert_amount(session, latest.close, latest.currency,
                                                   portfolio.display_currency, valuation_date,
                                                   fetcher=lambda *_: [])
                except RateUnavailable:
                    pass
                try:
                    native_price = convert_amount(session, latest.close, latest.currency,
                                                  asset.instrument.currency or latest.currency,
                                                  valuation_date, fetcher=lambda *_: [])
                except RateUnavailable:
                    pass
            value = (snapshot.quantity * display_price if display_price is not None else
                     ZERO if snapshot.quantity == 0 else None)
            cost = snapshot.remaining_acquisition_cost if portfolio.display_currency == 'BRL' else None
            realized = snapshot.realized_gain if portfolio.display_currency == 'BRL' else None
            income = snapshot.gross_income if portfolio.display_currency == 'BRL' else None
            unrealized = value - cost if value is not None and cost is not None else None
            gain = (realized + unrealized + income if all(
                item is not None for item in (realized, unrealized, income)) else None)
            brokers = snapshot.ledger_state.get('brokers', {})
            position = {
                'asset_id': asset.id, 'asset': asset.instrument.symbol,
                'native_currency': asset.instrument.currency,
                'quote_currency': latest.currency if latest else None,
                'transaction_currency': None, 'display_currency': portfolio.display_currency,
                'broker': ', '.join(sorted(brokers)), 'allocation_class': '',
                'broker_breakdown': [], 'quantity': snapshot.quantity,
                'average_cost': snapshot.average_cost if cost is not None else None,
                'acquisition_cost': cost, 'display_average_cost': snapshot.average_cost if cost is not None else None,
                'display_acquisition_cost': cost, 'native_average_cost': None,
                'native_acquisition_cost': None, 'current_price': native_price,
                'total_value': snapshot.quantity * native_price if native_price is not None else None,
                'display_price': display_price, 'display_value': value,
                'realized_gain': realized, 'unrealized_gain': unrealized,
                'gross_income': income, 'current_total_gain': gain,
                'native_gross_income': None, 'current_accumulated_profitability': None,
                'return_date': snapshot.date,
                'income_by_currency': {key: decimal(amount) for key, amount in
                                       snapshot.ledger_state.get('income_by_currency', {}).items()},
                'corporate_action_count': 0, 'price_date': latest.date if latest else None,
                'gain_date': valuation_date, 'valuation_date': valuation_date,
                'action_coverage_through': snapshot.date,
                'quote_refresh_required': False, 'history_behind_transactions': False,
                'status': 'pending',
            }
            if latest is None and snapshot.quantity:
                missing_prices.append(asset.instrument.symbol)
            elif display_price is None and snapshot.quantity:
                missing_fx.append(asset.instrument.symbol)
            positions.append(position)
            asset_rows.append({
                'id': asset.id, 'ticker': asset.instrument.symbol,
                'transaction_currency': None, 'quantity': snapshot.quantity,
                'average_cost': position['average_cost'], 'current_price': native_price,
                'total_value': position['total_value'], 'price_date': position['price_date'],
                'income_by_currency': position['income_by_currency'],
                'corporate_action_count': 0, 'acquisition_cost': cost,
                'display_acquisition_cost': cost, 'display_average_cost': position['display_average_cost'],
                'display_value': value,
            })
            continue
        events = get_stored_actions(session, asset, end=valuation_date)
        action_gaps = missing_action_ranges(session, asset, min(row.trade_date for row in rows), valuation_date)
        if action_gaps:
            missing_actions.append(asset.instrument.symbol)
        prices = [price for price in history_for_reporting(session, asset) if price.date <= valuation_date]
        latest = prices[-1] if prices else None
        rates = reporting_factors(session, portfolio.display_currency, rows, events,
                                  [latest] if latest else [], valuation_date=valuation_date)
        snapshot = None
        projected = []
        if portfolio.history_built_through is not None:
            snapshot = session.scalar(select(PositionSnapshot).where(
                PositionSnapshot.portfolio_id == portfolio_id,
                PositionSnapshot.instrument_id == asset.instrument_id,
                PositionSnapshot.date == portfolio.history_built_through,
                PositionSnapshot.reporting_currency == 'BRL',
            ))
            if snapshot is not None and asset.instrument_id not in dirty_instruments:
                from src.consolidation import position_series
                projected = position_series(session, portfolio_id, asset.instrument_id,
                                            include_state=True)
        if projected and snapshot.date == valuation_date - timedelta(days=1):
            today_rows = [row for row in rows if row.trade_date == valuation_date]
            today_events = [event for event in events if event.effective_date == valuation_date]
            current = position_history(
                today_rows, today_events, [latest] if latest else [], portfolio.display_currency,
                rates, start=valuation_date, end=valuation_date,
                initial_state=projected[-1]['ledger_state'],
                missing_action_ranges=action_gaps,
            )[0]
        else:
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
        if snapshot is not None:
            if asset.instrument_id in dirty_instruments:
                state['quantity'] = snapshot.quantity
                brokers = snapshot.ledger_state.get('brokers', {})
                state['broker_breakdown'] = [{
                    'broker': broker,
                    'quantity': decimal(holding['quantity']),
                    'acquisition_cost': (decimal(holding['cost'])
                                         if holding['cost'] is not None and portfolio.display_currency == 'BRL'
                                         else None),
                    'average_cost': (decimal(holding['cost']) / decimal(holding['quantity'])
                                     if holding['cost'] is not None and decimal(holding['quantity'])
                                     and portfolio.display_currency == 'BRL' else None),
                } for broker, holding in sorted(brokers.items())]
                state['income_by_currency'] = {
                    currency: decimal(value)
                    for currency, value in snapshot.ledger_state.get('income_by_currency', {}).items()
                }
                state['display_value'] = (snapshot.quantity * state['display_price']
                                          if state['display_price'] is not None else
                                          ZERO if snapshot.quantity == 0 else None)
                state['total_value'] = (snapshot.quantity * state['current_price']
                                        if state['current_price'] is not None else
                                        ZERO if snapshot.quantity == 0 else None)
                state['acquisition_cost'] = state['display_acquisition_cost'] = (
                    snapshot.remaining_acquisition_cost
                    if portfolio.display_currency == 'BRL' else None)
                state['average_cost'] = state['display_average_cost'] = (
                    snapshot.average_cost if portfolio.display_currency == 'BRL' else None)
                for name in ('realized_gain', 'gross_income'):
                    state[name] = getattr(snapshot, name) if portfolio.display_currency == 'BRL' else None
                state['native_acquisition_cost'] = (
                    snapshot.remaining_acquisition_cost if native_currency == 'BRL' else None)
                state['native_average_cost'] = (
                    snapshot.average_cost if native_currency == 'BRL' else None)
                state['native_gross_income'] = (
                    snapshot.gross_income if native_currency == 'BRL' else None)
                cost = state['acquisition_cost']
                value = state['display_value']
                state['unrealized_gain'] = value - cost if value is not None and cost is not None else None
                state['current_total_gain'] = (
                    state['realized_gain'] + state['unrealized_gain'] + state['gross_income']
                    if all(state[name] is not None for name in
                           ('realized_gain', 'unrealized_gain', 'gross_income')) else None)
                state['status'] = 'pending'
            else:
                if projected:
                    history_states.append(projected[-1]['status'])
                state['current_accumulated_profitability'] = (
                    projected[-1]['cumulative_return_pct'] if projected else None)
                if projected and snapshot.date == valuation_date - timedelta(days=1):
                    state['current_accumulated_profitability'] = current['cumulative_return_pct']
                    state['return_date'] = valuation_date
            if state['return_date'] is None:
                state['return_date'] = snapshot.date
            if action_gaps:
                state['current_accumulated_profitability'] = None
        positions.append(state)
        asset_rows.append({
            'id': asset.id, 'ticker': asset.instrument.symbol,
            'transaction_currency': position_currency,
            'quantity': state['quantity'], 'average_cost': state['average_cost'],
            'current_price': native_price, 'total_value': state['total_value'],
            'price_date': state['price_date'], 'income_by_currency': state['income_by_currency'],
            'corporate_action_count': len(events), 'acquisition_cost': state['acquisition_cost'],
            'display_acquisition_cost': state['display_acquisition_cost'], 'display_average_cost': state['display_average_cost'],
            'display_value': state['display_value'],
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
    if portfolio.history_built_through is not None and fixed_income_lots:
        from src.consolidation import position_series
        for instrument_id in {lot.asset.instrument_id for lot in fixed_income_lots}:
            projected = position_series(session, portfolio_id, instrument_id)
            if projected:
                history_states.append(projected[-1]['status'])
    latest_snapshot_status = ('complete' if history_states and all(
        status == 'complete' for status in history_states) else 'incomplete')
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
            'history_status': ('pending' if portfolio.dirty_from else
                               'complete' if not transactions and not fixed_income_lots else
                               'pending' if portfolio.history_built_through is None or
                               portfolio.history_built_through < valuation_date - timedelta(days=1)
                               else 'complete' if latest_snapshot_status == 'complete' else 'incomplete'),
            'dirty_from': portfolio.dirty_from,
            'history_built_through': portfolio.history_built_through,
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
