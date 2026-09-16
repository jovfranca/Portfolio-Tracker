"""Pure portfolio calculations.

The formulas intentionally preserve the original Buy/Sell behavior. Fees,
dividends and splits are stored by the application but are not applied here.
"""
from collections import defaultdict
from dataclasses import asdict, dataclass
from decimal import Decimal
from datetime import time


ZERO = Decimal('0')


def decimal(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


def transaction_date(transaction):
    return getattr(transaction, 'trade_date', None) or transaction.date_time.date()


@dataclass
class Position:
    asset: str
    broker: str
    allocation_class: str
    asset_currency: str
    quantity: Decimal = ZERO
    average_cost: Decimal = ZERO
    current_price: Decimal | None = None
    total_value: Decimal | None = None
    realized_gain: Decimal = ZERO
    unrealized_gain: Decimal | None = None
    current_total_gain: Decimal | None = None
    current_accumulated_profitability: Decimal | None = None


def ordered(transactions):
    return sorted(transactions, key=lambda transaction: (
        transaction_date(transaction),
        transaction.date_time.time() if getattr(transaction, 'date_time', None) else time.min,
        transaction.id or 0,
    ))


def cost_and_quantity(transactions):
    average, cost_quantity, quantity = ZERO, ZERO, ZERO
    for transaction in ordered(transactions):
        transaction_quantity = decimal(transaction.quantity)
        transaction_price = decimal(transaction.price)
        if transaction.type == 'Buy':
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
    return (average if cost_quantity > 0 else ZERO), quantity


def historical_profitability(transactions, history):
    """Apply legacy gain formulas and carry operations to the next quote."""
    transactions = ordered(transactions)
    quantity = average = realized = invested = ZERO
    previous_gain = None
    cursor = 0
    result = []
    for quote in sorted(history, key=lambda item: item.date):
        while cursor < len(transactions) and transaction_date(transactions[cursor]) <= quote.date:
            transaction = transactions[cursor]
            transaction_quantity = decimal(transaction.quantity)
            transaction_price = decimal(transaction.price)
            if transaction.type == 'Buy':
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
        result.append({
            'date': quote.date,
            'unrealized_gain': unrealized,
            'realized_gain': realized,
            'total_gain': gain,
            'accumulated_profitability_pct': gain / invested * 100 if invested > 0 else None,
            'daily_profitability_pct': (
                (gain - previous_gain) / previous_gain * 100 if previous_gain else ZERO
            ),
        })
        previous_gain = gain
    return result


def overview(transactions, assets):
    groups = defaultdict(list)
    assets_by_ticker = {asset.ticker: asset for asset in assets}
    for transaction in ordered(transactions):
        groups[(
            transaction.asset, transaction.broker, transaction.allocation_class,
            getattr(transaction, 'asset_currency', 'BRL'),
        )].append(transaction)

    positions = []
    for (ticker, broker, allocation, currency), position_transactions in sorted(
        groups.items(), key=lambda item: (item[0][2], item[0][0], item[0][1])
    ):
        asset = assets_by_ticker.get(ticker)
        quotes = asset.history if asset else []
        average, quantity = cost_and_quantity(position_transactions)
        latest = max(quotes, key=lambda quote: quote.date) if quotes else None
        series = historical_profitability(position_transactions, quotes)
        last = series[-1] if series else None
        position = Position(ticker, broker, allocation, currency, quantity, average)
        position.current_price = decimal(latest.close) if latest else None
        position.total_value = quantity * decimal(latest.close) if latest else (ZERO if quantity == 0 else None)
        position.realized_gain = last['realized_gain'] if last else ZERO
        position.unrealized_gain = last['unrealized_gain'] if last else None
        position.current_total_gain = last['total_gain'] if last else None
        position.current_accumulated_profitability = (
            last['accumulated_profitability_pct'] if last else None
        )
        positions.append({
            **asdict(position),
            'price_date': latest.date if latest else None,
            'gain_date': latest.date if last else None,
            'history_behind_transactions': bool(
                latest and latest.date < transaction_date(position_transactions[-1])
            ),
        })

    asset_rows = []
    for ticker in sorted({transaction.asset for transaction in transactions}):
        asset_transactions = [transaction for transaction in transactions if transaction.asset == ticker]
        currency = getattr(asset_transactions[0], 'asset_currency', 'BRL')
        average, quantity = cost_and_quantity(asset_transactions)
        asset = assets_by_ticker.get(ticker)
        latest = max(asset.history, key=lambda quote: quote.date) if asset and asset.history else None
        asset_rows.append({
            'id': asset.id if asset else None,
            'ticker': ticker,
            'asset_currency': currency,
            'quantity': quantity,
            'average_cost': average,
            'current_price': decimal(latest.close) if latest else None,
            'total_value': quantity * decimal(latest.close) if latest else (ZERO if quantity == 0 else None),
            'price_date': latest.date if latest else None,
        })

    missing = [asset['ticker'] for asset in asset_rows if asset['total_value'] is None]
    currencies = sorted({asset['asset_currency'] for asset in asset_rows})
    totals_by_currency = {
        currency: sum((
            asset['total_value'] or ZERO for asset in asset_rows
            if asset['asset_currency'] == currency
        ), ZERO)
        for currency in currencies
    }
    priced_value = totals_by_currency[currencies[0]] if len(currencies) == 1 else None
    return {
        'positions': positions,
        'assets': asset_rows,
        'summary': {
            'transactions': len(transactions),
            'positions': len(positions),
            'assets': len(asset_rows),
            'priced_value': priced_value,
            'total_value': None if missing or len(currencies) != 1 else priced_value,
            'missing_prices': missing,
            'currencies': currencies,
            'totals_by_currency': totals_by_currency,
        },
        'methodology': (
            'Custo médio sem taxas; ganho sem dividendos; moedas não são somadas. '
            'A variação diária é a variação do ganho, não TWR.'
        ),
    }
