"""Pure portfolio calculations.

The formulas intentionally preserve the original Buy/Sell behavior. Fees,
dividends and splits are stored by the application but are not applied here.
"""
from collections import defaultdict
from dataclasses import asdict, dataclass


@dataclass
class Position:
    asset: str
    broker: str
    allocation_class: str
    quantity: float = 0
    average_cost: float = 0
    current_price: float | None = None
    total_value: float | None = None
    realized_gain: float = 0
    unrealized_gain: float | None = None
    current_total_gain: float | None = None
    current_accumulated_profitability: float | None = None


def ordered(transactions):
    return sorted(transactions, key=lambda transaction: (transaction.date_time, transaction.id or 0))


def cost_and_quantity(transactions):
    average, cost_quantity, quantity = 0.0, 0.0, 0.0
    for transaction in ordered(transactions):
        if transaction.type == 'Buy':
            denominator = cost_quantity + transaction.quantity
            if denominator == 0:
                raise ValueError('Histórico produz divisão por zero no preço médio legado. Revise vendas e compras.')
            average = (
                average * cost_quantity + transaction.price * transaction.quantity
            ) / denominator
            cost_quantity += transaction.quantity
            quantity += transaction.quantity
        else:
            if cost_quantity > 0:
                cost_quantity -= transaction.quantity
            quantity = max(quantity - transaction.quantity, 0)
    return (average if cost_quantity > 0 else 0.0), quantity


def historical_profitability(transactions, history):
    """Apply legacy gain formulas and carry operations to the next quote."""
    transactions = ordered(transactions)
    quantity = average = realized = invested = 0.0
    previous_gain = None
    cursor = 0
    result = []
    for quote in sorted(history, key=lambda item: item.date):
        while cursor < len(transactions) and transactions[cursor].date_time.date() <= quote.date:
            transaction = transactions[cursor]
            if transaction.type == 'Buy':
                denominator = quantity + transaction.quantity
                if denominator == 0:
                    raise ValueError('Histórico inválido para cálculo de ganho.')
                average = (
                    average * quantity + transaction.price * transaction.quantity
                ) / denominator
                quantity += transaction.quantity
                invested += transaction.quantity * transaction.price
            else:
                realized += (transaction.price - average) * transaction.quantity
                quantity -= transaction.quantity
            cursor += 1
        unrealized = (quote.close - average) * quantity
        gain = unrealized + realized
        result.append({
            'date': quote.date,
            'unrealized_gain': unrealized,
            'realized_gain': realized,
            'total_gain': gain,
            'accumulated_profitability_pct': gain / invested * 100 if invested > 0 else None,
            'daily_profitability_pct': (
                (gain - previous_gain) / previous_gain * 100 if previous_gain else 0.0
            ),
        })
        previous_gain = gain
    return result


def overview(transactions, assets):
    groups = defaultdict(list)
    assets_by_ticker = {asset.ticker: asset for asset in assets}
    for transaction in ordered(transactions):
        groups[(transaction.asset, transaction.broker, transaction.allocation_class)].append(transaction)

    positions = []
    for (ticker, broker, allocation), position_transactions in sorted(
        groups.items(), key=lambda item: (item[0][2], item[0][0], item[0][1])
    ):
        asset = assets_by_ticker.get(ticker)
        quotes = asset.history if asset else []
        average, quantity = cost_and_quantity(position_transactions)
        latest = max(quotes, key=lambda quote: quote.date) if quotes else None
        series = historical_profitability(position_transactions, quotes)
        last = series[-1] if series else None
        position = Position(ticker, broker, allocation, quantity, average)
        position.current_price = latest.close if latest else None
        position.total_value = quantity * latest.close if latest else (0 if quantity == 0 else None)
        position.realized_gain = last['realized_gain'] if last else 0
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
                latest and latest.date < position_transactions[-1].date_time.date()
            ),
        })

    asset_rows = []
    for ticker in sorted({transaction.asset for transaction in transactions}):
        asset_transactions = [transaction for transaction in transactions if transaction.asset == ticker]
        average, quantity = cost_and_quantity(asset_transactions)
        asset = assets_by_ticker.get(ticker)
        latest = max(asset.history, key=lambda quote: quote.date) if asset and asset.history else None
        asset_rows.append({
            'id': asset.id if asset else None,
            'ticker': ticker,
            'quantity': quantity,
            'average_cost': average,
            'current_price': latest.close if latest else None,
            'total_value': quantity * latest.close if latest else (0 if quantity == 0 else None),
            'price_date': latest.date if latest else None,
        })

    missing = [asset['ticker'] for asset in asset_rows if asset['total_value'] is None]
    priced_value = sum(asset['total_value'] or 0 for asset in asset_rows)
    return {
        'positions': positions,
        'assets': asset_rows,
        'summary': {
            'transactions': len(transactions),
            'positions': len(positions),
            'assets': len(asset_rows),
            'priced_value': priced_value,
            'total_value': None if missing else priced_value,
            'missing_prices': missing,
        },
        'methodology': (
            'Legado: custo médio sem taxas; ganho sem dividendos; sem conversão cambial. '
            'A variação diária é a variação do ganho, não TWR.'
        ),
    }
