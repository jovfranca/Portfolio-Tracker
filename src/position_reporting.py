"""Resolve stored market and FX inputs for the pure position ledger."""
from datetime import date, timedelta
from decimal import Decimal
from bisect import bisect_right

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.corporate_actions import get_stored_actions, missing_action_ranges
from src.domain import ZERO, PositionLedger, decimal, summary_totals, transaction_date
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


def _pending_position(session, portfolio, asset, snapshot, valuation_date):
    from src.domain import saved_position_value
    prices = [price for price in history_for_reporting(session, asset) if price.date <= valuation_date]
    latest = prices[-1] if prices else None

    def project(currency):
        factors = reporting_factors(session, currency, [], [], [latest], valuation_date=valuation_date)
        return saved_position_value(snapshot, latest, currency, factors, day=valuation_date)

    current = project(portfolio.display_currency)
    native_currency = asset.instrument.currency
    native = project(native_currency) if native_currency else None
    return {
        'asset_id': asset.id, 'instrument_id': asset.instrument_id, 'asset': asset.instrument.symbol,
        'native_currency': native_currency, 'quote_currency': latest.currency if latest else None,
        'transaction_currency': None, 'display_currency': portfolio.display_currency,
        'broker': ', '.join(sorted(snapshot.ledger_state['brokers'])), 'allocation_class': '',
        'broker_breakdown': current['broker_breakdown'], 'quantity': snapshot.quantity,
        'average_cost': current['average_cost'], 'acquisition_cost': current['remaining_acquisition_cost'],
        'display_average_cost': current['average_cost'],
        'display_acquisition_cost': current['remaining_acquisition_cost'],
        'native_average_cost': native['average_cost'] if native else None,
        'native_acquisition_cost': native['remaining_acquisition_cost'] if native else None,
        'current_price': native['current_price'] if native else (latest.close if latest else None),
        'total_value': native['market_value'] if native else None,
        'display_price': current['current_price'], 'display_value': current['market_value'],
        'realized_gain': current['realized_gain'], 'unrealized_gain': current['unrealized_gain'],
        'gross_income': current['gross_income'], 'current_total_gain': current['total_gain'],
        'native_gross_income': native['gross_income'] if native else None,
        'current_accumulated_profitability': None, 'return_date': snapshot.date,
        'income_by_currency': current['income_by_currency'], 'corporate_action_count': 0,
        'price_date': current['quote_date'], 'gain_date': valuation_date, 'valuation_date': valuation_date,
        'action_coverage_through': snapshot.date, 'quote_refresh_required': False,
        'history_behind_transactions': False, 'status': 'pending',
    }


def _unbuilt_position(portfolio, asset, valuation_date):
    return {
        'asset_id': asset.id, 'instrument_id': asset.instrument_id, 'asset': asset.instrument.symbol,
        'native_currency': asset.instrument.currency, 'quote_currency': None,
        'transaction_currency': None, 'display_currency': portfolio.display_currency,
        'broker': '', 'allocation_class': '', 'broker_breakdown': [],
        'income_by_currency': {}, 'corporate_action_count': 0,
        'valuation_date': valuation_date, 'action_coverage_through': None,
        'quote_refresh_required': False, 'history_behind_transactions': False,
        'status': 'pending', 'unbuilt': True,
        **{key: None for key in ('quantity', 'average_cost', 'acquisition_cost',
            'display_average_cost', 'display_acquisition_cost', 'native_average_cost',
            'native_acquisition_cost', 'current_price', 'total_value', 'display_price',
            'display_value', 'realized_gain', 'unrealized_gain', 'gross_income',
            'current_total_gain', 'native_gross_income', 'current_accumulated_profitability',
            'return_date', 'price_date', 'gain_date')},
    }


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
        if asset.instrument.asset_type == 'FIXED_INCOME':
            continue
        snapshot = session.scalar(select(PositionSnapshot).where(
            PositionSnapshot.portfolio_id == portfolio_id,
            PositionSnapshot.instrument_id == asset.instrument_id,
            PositionSnapshot.date <= valuation_date,
        ).order_by(PositionSnapshot.date.desc()).limit(1))
        pending_snapshot = snapshot if asset.instrument_id in dirty_instruments else None
        if snapshot is None:
            # Asset/quote metadata survives removal of its last trade. Once the
            # deletion is consolidated there is no holding left to build.
            if not rows and asset.instrument_id not in dirty_instruments:
                continue
            state = _unbuilt_position(portfolio, asset, valuation_date)
            positions.append(state)
            asset_rows.append({'id': asset.id, 'ticker': asset.instrument.symbol,
                'transaction_currency': None, 'quantity': None, 'average_cost': None,
                'current_price': None, 'total_value': None, 'price_date': None,
                'income_by_currency': {}, 'corporate_action_count': 0,
                'acquisition_cost': None, 'display_acquisition_cost': None,
                'display_average_cost': None, 'display_value': None})
            history_states.append('pending')
            continue
        if pending_snapshot is not None:
            state = _pending_position(session, portfolio, asset, pending_snapshot, valuation_date)
            positions.append(state)
            asset_rows.append({
                'id': asset.id, 'ticker': asset.instrument.symbol,
                'transaction_currency': None, 'quantity': state['quantity'],
                'average_cost': state['average_cost'], 'current_price': state['current_price'],
                'total_value': state['total_value'], 'price_date': state['price_date'],
                'income_by_currency': state['income_by_currency'], 'corporate_action_count': 0,
                'acquisition_cost': state['acquisition_cost'],
                'display_acquisition_cost': state['acquisition_cost'],
                'display_average_cost': state['average_cost'], 'display_value': state['display_value'],
            })
            if state['price_date'] is None and pending_snapshot.quantity:
                missing_prices.append(asset.instrument.symbol)
            elif state['display_price'] is None and pending_snapshot.quantity:
                missing_fx.append(asset.instrument.symbol)
            continue
        events = get_stored_actions(session, asset, end=valuation_date)
        action_gaps = missing_action_ranges(session, asset, min((row.trade_date for row in rows), default=snapshot.date), valuation_date)
        if action_gaps:
            missing_actions.append(asset.instrument.symbol)
        prices = [price for price in history_for_reporting(session, asset) if price.date <= valuation_date]
        latest = prices[-1] if prices else None
        rates = reporting_factors(session, portfolio.display_currency, rows, events,
                                  [latest] if latest else [], valuation_date=valuation_date)
        from src.consolidation import position_series
        projected = position_series(session, portfolio_id, asset.instrument_id,
                                    include_state=True, include_current=True)
        current = PositionLedger(portfolio.display_currency, rates,
                                 projected[-1]['ledger_state']).snapshot(
            valuation_date, latest, canonical_quantity=snapshot.quantity,
            actions_complete=not action_gaps)
        quote_valid = latest is not None and current['quote_date'] is not None and not action_gaps
        native_currency = asset.instrument.currency
        native_state = None
        if native_currency:
            if native_currency == portfolio.display_currency:
                native_state = current
            else:
                native_rates = reporting_factors(session, native_currency, rows, events,
                                                 [latest] if latest else [], valuation_date=valuation_date)
                native_projected = position_series(session, portfolio_id, asset.instrument_id,
                    include_state=True, include_current=True, display_currency=native_currency)
                native_state = PositionLedger(native_currency, native_rates,
                    native_projected[-1]['ledger_state']).snapshot(
                        valuation_date, latest, canonical_quantity=snapshot.quantity,
                        actions_complete=not action_gaps)
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
            'asset_id': asset.id, 'instrument_id': asset.instrument_id, 'asset': asset.instrument.symbol,
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
                [transaction_date(row) for row in rows] + [event.effective_date for event in events],
                default=snapshot.date
            )), 'status': ('complete' if current['status'] == 'incomplete_history'
                           else current['status']),
        }
        if snapshot is not None:
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
                                          portfolio.display_currency, portfolio_id=portfolio_id)
    for item in fixed_positions:
        positions.append({
            **item, 'position_type': 'FIXED_INCOME', 'native_currency': item['currency'],
            'quote_currency': None, 'transaction_currency': item['currency'],
            'broker': ', '.join(sorted({row['broker'] for row in item['lots']})),
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
        status == 'complete' for status in history_states) or not history_states and all(
        row['status'] == 'complete' for row in positions) else 'incomplete')
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
            'history_status': ('pending' if portfolio.dirty_from or any(
                               row['status'] == 'pending' for row in positions) else
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
    if fixed_positions:
        result['fixed_income'] = {
            'lot_count': sum(len(position['lots']) for position in fixed_positions),
            'valuation_status': ('pending' if any(row['status'] == 'pending' for row in fixed_positions)
                                 else 'complete' if all(row['status'] == 'complete' for row in fixed_positions)
                                 else 'incomplete'),
            'lots': [value for position in fixed_positions for value in position['lots']],
            'positions': fixed_positions,
        }
        if any(row['status'] not in {'complete', 'pending'} for row in fixed_positions):
            if result['summary']['history_status'] != 'pending':
                result['summary']['history_status'] = 'incomplete'
    else:
        result['fixed_income'] = {'lot_count': 0, 'valuation_status': 'none', 'lots': []}
    return result
