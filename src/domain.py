"""Pure portfolio calculations for trades and resolved corporate events."""
from collections import defaultdict
from datetime import time, timedelta
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
            if transaction_quantity > quantity:
                raise ValueError('Venda excede a quantidade disponível nesta posição.')
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
                if transaction_quantity > quantity:
                    raise ValueError('Venda excede a quantidade disponível nesta posição.')
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
                if transaction_quantity > quantity:
                    raise ValueError('Venda excede a quantidade disponível nesta posição.')
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


class PositionLedger:
    """One instrument's holdings and lifetime results in a reporting currency.

    Trades and events are applied before that day's closing valuation. Purchases
    enter the daily return denominator; sale proceeds leave the position. Gross
    distributions are investment return rather than external contributions.
    """

    def __init__(self, currency, rates, state=None):
        self.currency = currency
        self.rates = rates
        self.brokers = {}
        self.realized = ZERO
        self.income = ZERO
        self.income_by_currency = defaultdict(lambda: ZERO)
        self.return_factor = Decimal('1')
        self.last_value = ZERO
        self.last_status = 'complete'
        self.last_split_date = None
        if state:
            self.brokers = {
                broker: {'quantity': decimal(row['quantity']),
                         'cost': decimal(row['cost']) if row['cost'] is not None else None}
                for broker, row in state['brokers'].items()
            }
            self.realized = decimal(state['realized']) if state['realized'] is not None else None
            self.income = decimal(state['income']) if state['income'] is not None else None
            self.income_by_currency.update({key: decimal(value)
                                            for key, value in state['income_by_currency'].items()})
            self.return_factor = (decimal(state['return_factor'])
                                  if state['return_factor'] is not None else None)
            self.last_value = decimal(state['last_value']) if state['last_value'] is not None else None
            self.last_status = state['last_status']
            self.last_split_date = state.get('last_split_date')

    @property
    def quantity(self):
        return sum((row['quantity'] for row in self.brokers.values()), ZERO)

    @property
    def cost(self):
        values = [row['cost'] for row in self.brokers.values() if row['quantity'] > 0]
        return sum(values, ZERO) if all(value is not None for value in values) else None

    def factor(self, currency, day):
        if currency == self.currency:
            return Decimal('1')
        value = self.rates.get((currency, day))
        return decimal(value) if value is not None else None

    def apply(self, kind, item):
        """Return the external cash flow and gross income for one activity."""
        if kind == 'event':
            if item.event_type in SPLIT_TYPES:
                factor = decimal(item.conversion_factor)
                if factor <= 0:
                    raise ValueError('O fator de conversão do desdobramento deve ser positivo.')
                for row in self.brokers.values():
                    row['quantity'] *= factor
                self.last_split_date = item.effective_date.isoformat()
                return ZERO, ZERO
            if item.event_type in INCOME_TYPES and self.quantity > 0:
                gross = self.quantity * decimal(item.amount_per_unit or ZERO)
                self.income_by_currency[item.currency] += gross
                factor = self.factor(item.currency, item.effective_date)
                if factor is None:
                    self.income = None
                    return ZERO, None
                amount = gross * factor
                if self.income is not None:
                    self.income += amount
                return ZERO, amount
            return ZERO, ZERO

        quantity = decimal(item.quantity)
        row = self.brokers.setdefault(item.broker, {'quantity': ZERO, 'cost': ZERO})
        factor = self.rates.get(('transaction', item.id))
        if factor is None:
            factor = self.factor(item.transaction_currency, item.settlement_date)
        gross = decimal(item.price) * quantity
        fees = transaction_fees(item)
        cash = (gross + fees if item.type == 'Buy' else -(gross - fees))
        cash = cash * factor if factor is not None else None
        if item.type == 'Buy':
            row['quantity'] += quantity
            if row['cost'] is not None:
                row['cost'] = row['cost'] + cash if cash is not None else None
        else:
            if quantity > row['quantity']:
                raise ValueError('Venda excede a quantidade disponível nesta corretora.')
            attributed = row['cost'] * quantity / row['quantity'] if row['cost'] is not None else None
            proceeds = -cash if cash is not None else None
            if attributed is None or proceeds is None:
                self.realized = None
            elif self.realized is not None:
                self.realized += proceeds - attributed
            row['quantity'] -= quantity
            row['cost'] = (ZERO if row['quantity'] == 0 else
                           row['cost'] - attributed if attributed is not None else None)
        return cash, ZERO

    def snapshot(self, day, quote, flow=ZERO, daily_income=ZERO, *, purchases=ZERO, previous_value=None):
        if quote is not None and self.last_split_date and quote.date.isoformat() < self.last_split_date:
            quote = None
        quantity = self.quantity
        cost = self.cost
        if quantity == 0:
            market_value, price = ZERO, None
            status = 'complete'
        elif quote is None:
            market_value = price = None
            status = 'missing_price'
        else:
            factor = self.factor(quote.currency, day)
            price = decimal(quote.close) * factor if factor is not None else None
            market_value = quantity * price if price is not None else None
            status = 'complete' if factor is not None else 'missing_fx'
        if cost is None or self.realized is None or self.income is None or flow is None or daily_income is None:
            status = 'missing_price_and_fx' if status == 'missing_price' else 'missing_fx'
        unrealized = market_value - cost if market_value is not None and cost is not None else None
        total = (self.realized + unrealized + self.income
                 if self.realized is not None and unrealized is not None and self.income is not None else None)
        start_value = self.last_value if previous_value is None else previous_value
        denominator = (start_value + purchases
                       if start_value is not None and purchases is not None else None)
        if (market_value is not None and daily_income is not None and flow is not None
                and start_value is not None and denominator is not None and denominator > 0):
            daily_return = (market_value + daily_income - start_value - flow) / denominator
            if self.return_factor is not None:
                self.return_factor *= Decimal('1') + daily_return
        elif status == 'complete' and quantity == 0 and start_value == ZERO:
            daily_return = ZERO
        else:
            daily_return = None
            self.return_factor = None
        if status != 'complete':
            daily_return = None
            self.return_factor = None
        self.last_value = market_value
        self.last_status = status
        return {
            'date': day, 'quantity': quantity,
            'remaining_acquisition_cost': cost,
            'average_cost': cost / quantity if cost is not None and quantity else ZERO if quantity == 0 else None,
            'market_value': market_value, 'current_price': price,
            'realized_gain': self.realized, 'unrealized_gain': unrealized,
            'gross_income': self.income, 'income_by_currency': dict(self.income_by_currency),
            'total_gain': total,
            'daily_return_pct': daily_return * 100 if daily_return is not None else None,
            'cumulative_return_pct': (self.return_factor - 1) * 100
            if self.return_factor is not None else None,
            'reporting_currency': self.currency, 'status': status,
            'net_flow': flow, 'daily_income': daily_income, 'purchases': purchases,
            'broker_breakdown': [
                {'broker': broker, 'quantity': value['quantity'],
                 'acquisition_cost': value['cost'],
                 'average_cost': value['cost'] / value['quantity']
                 if value['cost'] is not None and value['quantity'] else ZERO if value['quantity'] == 0 else None}
                for broker, value in sorted(self.brokers.items())
            ],
        }

    def state(self):
        return {
            'brokers': {key: {'quantity': str(row['quantity']),
                              'cost': str(row['cost']) if row['cost'] is not None else None}
                        for key, row in self.brokers.items()},
            'realized': str(self.realized) if self.realized is not None else None,
            'income': str(self.income) if self.income is not None else None,
            'income_by_currency': {key: str(value) for key, value in self.income_by_currency.items()},
            'return_factor': str(self.return_factor) if self.return_factor is not None else None,
            'last_value': str(self.last_value) if self.last_value is not None else None,
            'last_status': self.last_status,
            'last_split_date': self.last_split_date,
        }


def position_history(transactions, corporate_events, prices, reporting_currency, rates,
                     *, start=None, end=None, initial_state=None):
    """Daily reproducible values; weekdays without a quote remain incomplete.

    Weekend closes carry Friday's published price, but a missing weekday quote
    is never fabricated. Trades and events take effect before that day's close.
    """
    activity = ordered_activity(transactions, corporate_events)
    if not activity and start is None:
        return []
    start = start or activity[0][0]
    end = end or max([start] + [item.date for item in prices])
    quotes = {item.date: item for item in prices}
    ledger = PositionLedger(reporting_currency, rates, initial_state)
    cursor = 0
    while cursor < len(activity) and activity[cursor][0] < start:
        cursor += 1
    result = []
    day = start
    previous_quotes = [item for item in prices if item.date < start]
    last_quote = max(previous_quotes, key=lambda item: item.date) if previous_quotes else None
    while day <= end:
        flow = daily_income = purchases = ZERO
        while cursor < len(activity) and activity[cursor][0] == day:
            _, _, _, _, kind, item = activity[cursor]
            item_flow, item_income = ledger.apply(kind, item)
            if kind == 'transaction' and item.type == 'Buy':
                purchases = (purchases + item_flow
                             if purchases is not None and item_flow is not None else None)
            if kind == 'event' and item.event_type in SPLIT_TYPES:
                last_quote = None
            flow = flow + item_flow if flow is not None and item_flow is not None else None
            daily_income = (daily_income + item_income
                            if daily_income is not None and item_income is not None else None)
            cursor += 1
        quote = quotes.get(day)
        if quote is not None:
            last_quote = quote
        elif day.weekday() >= 5:
            quote = last_quote
        result.append(ledger.snapshot(day, quote, flow, daily_income, purchases=purchases))
        if (result[-1]['status'] == 'complete'
                and result[-1]['cumulative_return_pct'] is None):
            result[-1]['status'] = ledger.last_status = 'incomplete_history'
        result[-1]['ledger_state'] = ledger.state()
        day += timedelta(days=1)
    return result


def position_now(transactions, corporate_events, quote, reporting_currency, rates):
    """Use the same ledger rules for the current position without daily replay."""
    ledger = PositionLedger(reporting_currency, rates)
    for _, _, _, _, kind, item in ordered_activity(transactions, corporate_events):
        ledger.apply(kind, item)
    if quote is not None and any(event.event_type in SPLIT_TYPES and
                                 event.effective_date > quote.date for event in corporate_events):
        quote = None
    return ledger.snapshot(quote.date if quote else None, quote)


def sum_known(rows, field):
    values = [getattr(row, field) if not isinstance(row, dict) else row[field] for row in rows]
    return sum(values, ZERO) if all(value is not None for value in values) else None


def summary_totals(positions):
    fields = {
        'acquisition_cost': 'acquisition_cost',
        'market_value': 'display_value',
        'realized_gain': 'realized_gain',
        'unrealized_gain': 'unrealized_gain',
        'gross_income': 'gross_income',
        'total_gain': 'current_total_gain',
    }
    result = {name: sum_known(positions, field) for name, field in fields.items()}
    result['priced_value'] = sum((decimal(row['display_value']) for row in positions
                                  if row['display_value'] is not None), ZERO)
    return result


def portfolio_day(rows, previous_value, previous_factor):
    """Aggregate reporting-currency position snapshots without mixing unknowns."""
    fields = ('remaining_acquisition_cost', 'market_value', 'realized_gain',
              'unrealized_gain', 'gross_income', 'total_gain')
    values = {field: sum_known(rows, field) for field in fields}
    flow = sum_known(rows, 'net_flow')
    purchases = sum_known(rows, 'purchases')
    income = sum_known(rows, 'daily_income')
    status = 'complete' if all(row.status == 'complete' for row in rows) else 'incomplete'
    current_value = values['market_value']
    denominator = (previous_value + purchases
                   if previous_value is not None and purchases is not None else None)
    if (status == 'complete' and current_value is not None and previous_value is not None
            and flow is not None and income is not None and denominator is not None and denominator > 0):
        daily_return = (current_value + income - previous_value - flow) / denominator
        factor = previous_factor * (Decimal('1') + daily_return) if previous_factor is not None else None
    elif status == 'complete' and current_value == previous_value == ZERO:
        daily_return = ZERO
        factor = previous_factor
    else:
        daily_return = factor = None
    return {
        **values, 'status': status, 'return_factor': factor,
        'daily_return_pct': daily_return * 100 if daily_return is not None else None,
        'cumulative_return_pct': (factor - 1) * 100 if factor is not None else None,
    }
