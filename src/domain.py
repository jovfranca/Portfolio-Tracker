"""Pure portfolio calculations for trades and resolved corporate events."""
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import time
from decimal import Decimal


ZERO = Decimal('0')
SPLIT_TYPES = {'STOCK_SPLIT', 'REVERSE_SPLIT'}
INCOME_TYPES = {'DIVIDEND', 'JCP', 'AMORTIZATION'}


def decimal(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


def transaction_date(transaction):
    return getattr(transaction, 'trade_date', None) or transaction.date_time.date()


@dataclass
class Position:
    asset: str
    broker: str
    allocation_class: str
    transaction_currency: str
    quantity: Decimal = ZERO
    average_cost: Decimal = ZERO
    current_price: Decimal | None = None
    total_value: Decimal | None = None
    realized_gain: Decimal = ZERO
    unrealized_gain: Decimal | None = None
    current_total_gain: Decimal | None = None
    current_accumulated_profitability: Decimal | None = None
    income_by_currency: dict[str, Decimal] = field(default_factory=dict)
    corporate_action_count: int = 0


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


def _position_state(transactions, corporate_events=()):
    average = cost_quantity = quantity = ZERO
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
        transaction_price = decimal(item.price)
        if item.type == 'Buy':
            denominator = cost_quantity + transaction_quantity
            if denominator == 0:
                raise ValueError('Histórico produz divisão por zero no preço médio legado. Revise vendas e compras.')
            average = (
                average * cost_quantity + transaction_price * transaction_quantity
            ) / denominator
            cost_quantity += transaction_quantity
            quantity += transaction_quantity
        else:
            if cost_quantity > 0:
                cost_quantity -= transaction_quantity
            quantity = max(quantity - transaction_quantity, ZERO)
    return average if cost_quantity > 0 else ZERO, quantity, dict(income)


def cost_and_quantity(transactions, corporate_events=()):
    average, quantity, _ = _position_state(transactions, corporate_events)
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
            if item.type == 'Buy':
                denominator = quantity + transaction_quantity
                if denominator == 0:
                    raise ValueError('Histórico inválido para cálculo de ganho.')
                average = (
                    average * quantity + transaction_price * transaction_quantity
                ) / denominator
                quantity += transaction_quantity
                invested += transaction_quantity * transaction_price
            else:
                realized += (transaction_price - average) * transaction_quantity
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


def overview(transactions, assets):
    groups = defaultdict(list)
    assets_by_identity = {
        (
            getattr(asset, 'instrument_id', ('legacy', asset.ticker)),
            getattr(asset, 'transaction_currency', 'BRL'),
        ): asset
        for asset in assets
    }
    for transaction in ordered(transactions):
        identity = getattr(transaction, 'instrument_id', None)
        if identity is None:
            identity = ('legacy', transaction.asset)
        currency = getattr(transaction, 'transaction_currency', 'BRL')
        groups[(identity, currency, transaction.broker, transaction.allocation_class)].append(transaction)

    positions = []
    for (identity, currency, broker, allocation), position_transactions in sorted(
        groups.items(), key=lambda item: (item[0][3], str(item[0][0]), item[0][2], item[0][1])
    ):
        asset = assets_by_identity.get((identity, currency))
        ticker = asset.ticker if asset else position_transactions[0].asset
        quotes = asset.history if asset else []
        corporate_events = getattr(asset, 'corporate_events', ()) if asset else ()
        average, quantity, income = _position_state(position_transactions, corporate_events)
        latest = max(quotes, key=lambda quote: quote.date) if quotes else None
        price_matches_position = _price_matches_split_state(latest, corporate_events)
        series = historical_profitability(position_transactions, quotes, corporate_events)
        last = series[-1] if series else None
        position = Position(ticker, broker, allocation, currency, quantity, average)
        position.current_price = decimal(latest.close) if price_matches_position else None
        position.total_value = (
            quantity * decimal(latest.close) if price_matches_position
            else (ZERO if quantity == 0 else None)
        )
        position.realized_gain = last['realized_gain'] if last else ZERO
        position.unrealized_gain = last['unrealized_gain'] if last and price_matches_position else None
        position.current_total_gain = last['total_gain'] if last and price_matches_position else None
        position.current_accumulated_profitability = (
            last['accumulated_profitability_pct'] if last and price_matches_position else None
        )
        position.income_by_currency = income
        position.corporate_action_count = len(corporate_events)
        positions.append({
            **asdict(position),
            'asset_id': asset.id if asset else None,
            'price_date': latest.date if latest else None,
            'gain_date': latest.date if last else None,
            'history_behind_transactions': bool(latest and latest.date < max(
                [transaction_date(position_transactions[-1])]
                + [event.effective_date for event in corporate_events]
            )),
        })

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
        average, quantity, income = _position_state(asset_transactions, corporate_events)
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

    missing = [asset['ticker'] for asset in asset_rows if asset['total_value'] is None]
    currencies = sorted({asset['transaction_currency'] for asset in asset_rows})
    totals_by_currency = {
        currency: sum((
            asset['total_value'] or ZERO for asset in asset_rows
            if asset['transaction_currency'] == currency
        ), ZERO)
        for currency in currencies
    }
    priced_value = totals_by_currency[currencies[0]] if len(currencies) == 1 else None
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
            'total_value': None if missing or len(currencies) != 1 else priced_value,
            'missing_prices': missing,
            'currencies': currencies,
            'totals_by_currency': totals_by_currency,
            'income_by_currency': dict(income_by_currency),
        },
        'methodology': (
            'Custo médio sem taxas; renda de eventos é exibida separadamente do ganho; '
            'moedas não são somadas. A variação diária é a variação do ganho, não TWR.'
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
                    average * cost_quantity + transaction_price * transaction_quantity
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
