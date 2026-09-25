"""Pure portfolio calculations for trades and resolved corporate events."""
from collections import defaultdict
from datetime import time
from decimal import Decimal


ZERO = Decimal('0')
SPLIT_TYPES = {'STOCK_SPLIT', 'REVERSE_SPLIT'}
INCOME_TYPES = {'DIVIDEND', 'JCP', 'AMORTIZATION'}


def decimal(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


def transaction_fees(transaction):
    return sum((decimal(getattr(transaction, name, ZERO) or ZERO)
                for name in ('brokerage_fee', 'other_fees')), ZERO)


def transaction_date(transaction):
    return getattr(transaction, 'trade_date', None) or transaction.date_time.date()


def ordered(transactions):
    return sorted(transactions, key=lambda transaction: (
        transaction_date(transaction),
        transaction.date_time.time() if getattr(transaction, 'date_time', None) else time.min,
        transaction.id or 0,
    ))


def ordered_activity(transactions, corporate_events=()):
    """Order opening-position events before trades on the effective date."""
    items = [
        (transaction_date(row), 2,
         row.date_time.time() if getattr(row, 'date_time', None) else time.min,
         row.id or 0, 'transaction', row)
        for row in transactions
    ]
    items.extend(
        (row.effective_date, 0 if row.event_type in SPLIT_TYPES else 1,
         time.min, row.id or 0, 'event', row)
        for row in corporate_events
    )
    return sorted(items, key=lambda item: item[:4])


def _apply_split(average, cost_quantity, quantity, event):
    factor = decimal(event.conversion_factor)
    if factor <= 0:
        raise ValueError('O fator de conversão do desdobramento deve ser positivo.')
    if quantity > 0:
        quantity *= factor
    if cost_quantity > 0:
        cost_quantity *= factor
        average /= factor
    return average, cost_quantity, quantity


def _price_matches_split_state(latest, corporate_events):
    return latest is not None and not any(
        event.event_type in SPLIT_TYPES and event.effective_date > latest.date
        for event in corporate_events
    )


def _position_state(transactions, corporate_events=(), price_factors=None):
    average = cost_quantity = quantity = ZERO
    realized = invested = ZERO
    income = defaultdict(lambda: ZERO)
    for _, _, _, _, kind, item in ordered_activity(transactions, corporate_events):
        if kind == 'event':
            if item.event_type in SPLIT_TYPES:
                average, cost_quantity, quantity = _apply_split(
                    average, cost_quantity, quantity, item,
                )
            elif item.event_type in INCOME_TYPES and quantity > 0:
                income[item.currency] += quantity * decimal(item.amount_per_unit or ZERO)
            continue
        transaction_quantity = decimal(item.quantity)
        factor = (
            decimal(price_factors[item.id]) if price_factors is not None and item.type == 'Buy'
            else Decimal('1')
        )
        transaction_price = decimal(item.price) * factor
        fees = transaction_fees(item) * factor
        if item.type == 'Buy':
            denominator = cost_quantity + transaction_quantity
            if denominator == 0:
                raise ValueError('Histórico produz divisão por zero no preço médio legado. Revise vendas e compras.')
            average = (
                average * cost_quantity + transaction_price * transaction_quantity + fees
            ) / denominator
            invested += transaction_price * transaction_quantity + fees
            cost_quantity += transaction_quantity
            quantity += transaction_quantity
        else:
            realized += (transaction_price - average) * transaction_quantity - fees
            if cost_quantity > 0:
                cost_quantity -= transaction_quantity
            quantity = max(quantity - transaction_quantity, ZERO)
    return average if cost_quantity > 0 else ZERO, quantity, dict(income), realized, invested


def cost_and_quantity(transactions, corporate_events=()):
    average, quantity, _, _, _ = _position_state(transactions, corporate_events)
    return average, quantity


def historical_profitability(transactions, history, corporate_events=()):
    """Apply legacy gain formulas; event income stays outside investment gain."""
    quantity = average = realized = invested = ZERO
    income = defaultdict(lambda: ZERO)
    previous_gain = None
    cursor = 0
    result = []
    activity = ordered_activity(transactions, corporate_events)
    for quote in sorted(history, key=lambda item: item.date):
        while cursor < len(activity) and activity[cursor][0] <= quote.date:
            _, _, _, _, kind, item = activity[cursor]
            if kind == 'event':
                if item.event_type in SPLIT_TYPES:
                    average, _, quantity = _apply_split(average, quantity, quantity, item)
                elif item.event_type in INCOME_TYPES and quantity > 0:
                    income[item.currency] += quantity * decimal(item.amount_per_unit or ZERO)
                cursor += 1
                continue
            transaction_quantity = decimal(item.quantity)
            transaction_price = decimal(item.price)
            fees = transaction_fees(item)
            if item.type == 'Buy':
                denominator = quantity + transaction_quantity
                if denominator == 0:
                    raise ValueError('Histórico inválido para cálculo de ganho.')
                average = (
                    average * quantity + transaction_price * transaction_quantity + fees
                ) / denominator
                quantity += transaction_quantity
                invested += transaction_quantity * transaction_price + fees
            else:
                realized += (transaction_price - average) * transaction_quantity - fees
                quantity -= transaction_quantity
            cursor += 1
        unrealized = (decimal(quote.close) - average) * quantity
        gain = unrealized + realized
        row = {
            'date': quote.date,
            'unrealized_gain': unrealized,
            'realized_gain': realized,
            'total_gain': gain,
            'accumulated_profitability_pct': gain / invested * 100 if invested > 0 else None,
            'daily_profitability_pct': (
                (gain - previous_gain) / previous_gain * 100 if previous_gain else ZERO
            ),
        }
        if corporate_events:
            row['income_by_currency'] = dict(income)
        result.append(row)
        previous_gain = gain
    return result


def consolidated_profitability(transactions, history, corporate_events=()):
    """Aggregate broker histories so gains use the same cost bases as positions."""
    groups = defaultdict(list)
    for transaction in transactions:
        groups[transaction.broker].append(transaction)
    broker_series = [historical_profitability(rows, history, corporate_events)
                     for rows in groups.values()]
    purchases = sorted((transaction_date(row), decimal(row.quantity) * decimal(row.price) + transaction_fees(row))
                       for row in transactions if row.type == 'Buy')
    result = []
    invested = previous_gain = ZERO
    purchase_index = 0
    for index, quote in enumerate(sorted(history, key=lambda item: item.date)):
        while purchase_index < len(purchases) and purchases[purchase_index][0] <= quote.date:
            invested += purchases[purchase_index][1]
            purchase_index += 1
        realized = sum((series[index]['realized_gain'] for series in broker_series), ZERO)
        unrealized = sum((series[index]['unrealized_gain'] for series in broker_series), ZERO)
        gain = realized + unrealized
        row = {
            'date': quote.date, 'realized_gain': realized,
            'unrealized_gain': unrealized, 'total_gain': gain,
            'accumulated_profitability_pct': gain / invested * 100 if invested > 0 else None,
            'daily_profitability_pct': (
                (gain - previous_gain) / previous_gain * 100 if previous_gain else ZERO
            ),
        }
        if corporate_events:
            income = defaultdict(lambda: ZERO)
            for series in broker_series:
                for currency, amount in series[index]['income_by_currency'].items():
                    income[currency] += amount
            row['income_by_currency'] = dict(income)
        result.append(row)
        previous_gain = gain
    return result


def overview(transactions, assets, display_currency='BRL', display_factors=None,
             display_cost_factors=None):
    display_factors = display_factors or {}
    display_cost_factors = display_cost_factors or {}
    assets_by_identity = {
        (
            getattr(asset, 'instrument_id', ('legacy', asset.ticker)),
            getattr(asset, 'transaction_currency', 'BRL'),
        ): asset
        for asset in assets
    }
    positions = []
    asset_rows = []
    identities = {
        (
            getattr(transaction, 'instrument_id', None) or ('legacy', transaction.asset),
            getattr(transaction, 'transaction_currency', 'BRL'),
        )
        for transaction in transactions
    }
    for identity, currency in sorted(identities, key=str):
        asset_transactions = [
            transaction for transaction in transactions
            if (
                getattr(transaction, 'instrument_id', None) or ('legacy', transaction.asset),
                getattr(transaction, 'transaction_currency', 'BRL'),
            ) == (identity, currency)
        ]
        asset = assets_by_identity.get((identity, currency))
        corporate_events = getattr(asset, 'corporate_events', ()) if asset else ()
        average = quantity = ZERO
        income = defaultdict(lambda: ZERO)
        ticker = asset.ticker if asset else asset_transactions[0].asset
        latest = max(asset.history, key=lambda quote: quote.date) if asset and asset.history else None
        price_matches_position = _price_matches_split_state(latest, corporate_events)
        asset_rows.append({
            'id': asset.id if asset else None,
            'ticker': ticker,
            'transaction_currency': currency,
            'quantity': quantity,
            'average_cost': average,
            'current_price': decimal(latest.close) if price_matches_position else None,
            'total_value': (
                quantity * decimal(latest.close) if price_matches_position
                else (ZERO if quantity == 0 else None)
            ),
            'price_date': latest.date if latest else None,
            'income_by_currency': income,
            'corporate_action_count': len(corporate_events),
        })

        # Use the same cost calculation for the consolidated position and each broker.
        by_broker = defaultdict(list)
        for transaction in asset_transactions:
            by_broker[transaction.broker].append(transaction)
        broker_breakdown = []
        realized = invested = ZERO
        for broker, broker_transactions in sorted(by_broker.items()):
            broker_average, broker_quantity, broker_income, broker_realized, broker_invested = _position_state(broker_transactions, corporate_events)
            realized += broker_realized
            invested += broker_invested
            for income_currency, amount in broker_income.items():
                income[income_currency] += amount
            broker_breakdown.append({
                'broker': broker, 'quantity': broker_quantity,
                'average_cost': broker_average,
                'acquisition_cost': broker_quantity * broker_average,
            })
        quantity = sum((row['quantity'] for row in broker_breakdown), ZERO)
        acquisition_cost = sum((row['acquisition_cost'] for row in broker_breakdown), ZERO)
        average = acquisition_cost / quantity if quantity else ZERO
        if quantity == 0:
            display_acquisition_cost = ZERO
        elif currency == display_currency:
            display_acquisition_cost = acquisition_cost
        elif all(transaction.id in display_cost_factors for transaction in asset_transactions
                 if transaction.type == 'Buy'):
            display_acquisition_cost = sum((
                _position_state(broker_transactions, corporate_events, display_cost_factors)[0]
                * next(row['quantity'] for row in broker_breakdown if row['broker'] == broker)
                for broker, broker_transactions in by_broker.items()
            ), ZERO)
        else:
            display_acquisition_cost = None
        display_average_cost = (
            display_acquisition_cost / quantity if display_acquisition_cost is not None and quantity else
            ZERO if quantity == 0 else None
        )
        asset_rows[-1]['quantity'] = quantity
        asset_rows[-1]['average_cost'] = average
        asset_rows[-1]['total_value'] = (
            quantity * decimal(latest.close) if price_matches_position
            else ZERO if quantity == 0 else None
        )
        native_value = asset_rows[-1]['total_value']
        factor = (Decimal('1') if currency == display_currency else
                  display_factors.get((currency, latest.date)) if latest else None)
        display_value = (native_value * decimal(factor) if native_value is not None and factor is not None
                         else ZERO if native_value == ZERO else None)
        asset_rows[-1]['acquisition_cost'] = acquisition_cost
        asset_rows[-1]['display_acquisition_cost'] = display_acquisition_cost
        asset_rows[-1]['display_average_cost'] = display_average_cost
        asset_rows[-1]['display_value'] = display_value
        # Current gains use all activity, even when the latest quote predates a
        # sale. Repricing does not need to rebuild daily historical returns.
        unrealized = native_value - acquisition_cost if native_value is not None else None
        gain = realized + unrealized if unrealized is not None else None
        allocations = {transaction.allocation_class for transaction in asset_transactions}
        positions.append({
            'asset_id': asset.id if asset else None, 'asset': ticker,
            'native_currency': getattr(asset, 'native_currency', currency),
            'transaction_currency': currency, 'display_currency': display_currency,
            'broker': ', '.join(sorted(by_broker)),
            'allocation_class': next(iter(allocations)) if len(allocations) == 1 else 'Múltiplas classes',
            'broker_breakdown': broker_breakdown,
            'quantity': quantity, 'average_cost': average, 'acquisition_cost': acquisition_cost,
            'display_average_cost': display_average_cost,
            'display_acquisition_cost': display_acquisition_cost,
            'current_price': asset_rows[-1]['current_price'], 'total_value': native_value,
            'display_price': asset_rows[-1]['current_price'] * decimal(factor)
            if asset_rows[-1]['current_price'] is not None and factor is not None else None,
            'display_value': display_value,
            'realized_gain': realized,
            'unrealized_gain': unrealized,
            'current_total_gain': gain,
            'current_accumulated_profitability': gain / invested * 100
            if gain is not None and invested > 0 else None,
            'income_by_currency': income, 'corporate_action_count': len(corporate_events),
            'price_date': latest.date if latest else None,
            'gain_date': latest.date if latest else None,
            'history_behind_transactions': bool(latest and latest.date < max(
                [transaction_date(transaction) for transaction in asset_transactions]
                + [event.effective_date for event in corporate_events]
            )),
        })

    missing = [asset['ticker'] for asset in asset_rows if asset['total_value'] is None]
    currencies = sorted({asset['transaction_currency'] for asset in asset_rows})
    totals_by_currency = {
        currency: sum((
            asset['total_value'] or ZERO for asset in asset_rows
            if asset['transaction_currency'] == currency
        ), ZERO)
        for currency in currencies
    }
    priced_value = sum((asset['display_value'] or ZERO for asset in asset_rows), ZERO)
    missing_fx = [f"{asset['ticker']} ({asset['transaction_currency']})" for asset in asset_rows
                  if asset['total_value'] is not None and asset['display_value'] is None]
    missing_cost_fx = [f"{asset['ticker']} ({asset['transaction_currency']})" for asset in asset_rows
                       if asset['display_acquisition_cost'] is None]
    income_by_currency = defaultdict(lambda: ZERO)
    for asset in asset_rows:
        for currency, amount in asset['income_by_currency'].items():
            income_by_currency[currency] += amount
    return {
        'positions': positions,
        'assets': asset_rows,
        'summary': {
            'transactions': len(transactions),
            'positions': len(positions),
            'assets': len({asset['id'] for asset in asset_rows}),
            'priced_value': priced_value,
            'total_value': None if missing or missing_fx else priced_value,
            'missing_prices': missing,
            'missing_fx': missing_fx,
            'missing_cost_fx': missing_cost_fx,
            'display_currency': display_currency,
            'currencies': currencies,
            'totals_by_currency': totals_by_currency,
            'income_by_currency': dict(income_by_currency),
        },
        'methodology': (
            'Custo médio inclui taxas; vendas usam o valor líquido de taxas; renda de eventos é exibida separadamente do ganho; '
            'conversões de cotações usam FX da data da cotação. Moedas sem FX não entram no total.'
        ),
    }


def corporate_event_effects(transactions, corporate_events):
    """Return auditable portfolio effects without persisting derived amounts."""
    quantity = average = cost_quantity = ZERO
    mixed_currencies = len({
        getattr(transaction, 'transaction_currency', 'BRL')
        for transaction in transactions
    }) > 1
    effects = []
    for _, _, _, _, kind, item in ordered_activity(transactions, corporate_events):
        if kind == 'transaction':
            transaction_quantity = decimal(item.quantity)
            transaction_price = decimal(item.price)
            if item.type == 'Buy':
                denominator = cost_quantity + transaction_quantity
                average = (
                    average * cost_quantity + transaction_price * transaction_quantity + transaction_fees(item)
                ) / denominator
                cost_quantity += transaction_quantity
                quantity += transaction_quantity
            else:
                cost_quantity = max(cost_quantity - transaction_quantity, ZERO)
                quantity = max(quantity - transaction_quantity, ZERO)
            continue
        eligible = quantity
        gross = None
        before_quantity, before_average = quantity, average
        if item.event_type in SPLIT_TYPES:
            average, cost_quantity, quantity = _apply_split(
                average, cost_quantity, quantity, item,
            )
        elif item.event_type in INCOME_TYPES:
            gross = eligible * decimal(item.amount_per_unit or ZERO)
        effects.append({
            'event': item,
            'eligible_quantity': eligible,
            'gross_amount': gross,
            'withholding_tax': None,
            'net_amount': None,
            'quantity_before': before_quantity,
            'quantity_after': quantity,
            'average_cost_before': None if mixed_currencies else before_average,
            'average_cost_after': None if mixed_currencies else average,
        })
    return effects
