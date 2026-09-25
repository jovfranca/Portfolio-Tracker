from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace as Obj
import pickle
import io
import pytest
from src.domain import cost_and_quantity, consolidated_profitability, historical_profitability, overview
from src.import_legacy import TransactionReader, read_transactions, read_assets


def tx(id, kind, quantity, price, day):
    return Obj(id=id, type=kind, quantity=quantity, price=price,
               date_time=datetime(2024, 1, day), asset='TEST', broker='A', allocation_class='Stocks')


def test_original_cost_partial_sale_and_repurchase():
    rows = [tx(1, 'Buy', 10, 20, 1), tx(2, 'Buy', 10, 40, 2), tx(3, 'Sell', 5, 50, 3)]
    assert cost_and_quantity(list(reversed(rows))) == (30, 15)
    rows += [tx(4, 'Sell', 15, 50, 4)]
    assert cost_and_quantity(rows) == (0, 0)
    rows += [tx(5, 'Buy', 2, 70, 5)]
    assert cost_and_quantity(rows) == (70, 2)


def test_original_gain_formulas():
    rows = [tx(1, 'Buy', 10, 20, 1), tx(2, 'Sell', 4, 30, 2)]
    quotes = [Obj(date=date(2024, 1, 1), close=25), Obj(date=date(2024, 1, 2), close=35)]
    result = historical_profitability(rows, quotes)
    assert result[0]['total_gain'] == 50
    assert result[1]['realized_gain'] == 40
    assert result[1]['unrealized_gain'] == 90
    assert result[1]['total_gain'] == 130
    assert result[1]['accumulated_profitability_pct'] == 65
    assert result[1]['daily_profitability_pct'] == 160


def test_same_day_legacy_order_uses_timestamp_before_id():
    buy = tx(2, 'Buy', 10, 20, 1)
    sell = tx(1, 'Sell', 5, 30, 1)
    buy.date_time = datetime(2024, 1, 1, 9)
    sell.date_time = datetime(2024, 1, 1, 15)
    buy.trade_date = sell.trade_date = date(2024, 1, 1)
    assert cost_and_quantity([sell, buy]) == (20, 5)
    assert historical_profitability([sell, buy], [Obj(date=date(2024, 1, 1), close=30)])[0]['realized_gain'] == 50


def test_domain_accepts_date_only_transactions():
    row = tx(1, 'Buy', 2, 10, 1)
    row.trade_date = row.date_time.date()
    del row.date_time
    assert cost_and_quantity([row]) == (10, 2)


def test_transaction_before_first_quote_is_not_lost():
    rows = [tx(1, 'Buy', 10, 20, 1)]
    result = historical_profitability(rows, [Obj(date=date(2024, 1, 3), close=30)])
    assert result[0]['total_gain'] == 100


def test_missing_quote_and_grouping():
    rows = [tx(1, 'Buy', 10, 20, 1), tx(2, 'Buy', 3, 30, 2)]
    rows[1].broker = 'B'
    result = overview(rows, [])
    assert len(result['positions']) == 1
    assert result['positions'][0]['quantity'] == 13
    assert {row['broker']: row['quantity'] for row in result['positions'][0]['broker_breakdown']} == {'A': 10, 'B': 3}
    assert result['summary']['total_value'] is None
    assert result['summary']['missing_prices'] == ['TEST']


def test_oversell_behavior_is_characterized():
    """Keep the legacy inconsistency visible until short-sale rules are decided."""
    rows = [tx(1, 'Buy', 10, 20, 1), tx(2, 'Sell', 15, 30, 2)]
    assert cost_and_quantity(rows) == (0, 0)
    result = historical_profitability(rows, [Obj(date=date(2024, 1, 3), close=40)])
    assert result[0] == {
        'date': date(2024, 1, 3), 'unrealized_gain': -100,
        'realized_gain': 150, 'total_gain': 50,
        'accumulated_profitability_pct': 25, 'daily_profitability_pct': 0,
    }


def test_asset_cost_pooling_and_broker_breakdown():
    rows = [tx(1, 'Buy', 10, 20, 1), tx(2, 'Buy', 10, 40, 2), tx(3, 'Sell', 10, 50, 3)]
    rows[1].broker = 'B'
    asset = Obj(id=1, ticker='TEST', history=[Obj(date=date(2024, 1, 3), close=50)])
    result = overview(rows, [asset])
    assert len(result['positions']) == 1
    assert result['positions'][0]['quantity'] == 10
    assert result['positions'][0]['average_cost'] == 40
    assert result['positions'][0]['acquisition_cost'] == 400
    assert [(p['broker'], p['quantity'], p['acquisition_cost']) for p in result['positions'][0]['broker_breakdown']] == [
        ('A', 0, 0), ('B', 10, 400),
    ]
    assert result['assets'][0]['average_cost'] == 40
    assert result['positions'][0]['realized_gain'] == 300


def test_consolidated_performance_uses_broker_cost_bases():
    rows = [tx(1, 'Buy', 10, 20, 1), tx(2, 'Buy', 10, 40, 2), tx(3, 'Sell', 10, 50, 3)]
    rows[1].broker = 'B'
    quote = [Obj(date=date(2024, 1, 3), close=50)]
    series = consolidated_profitability(rows, quote)
    assert series[0]['realized_gain'] == 300
    assert series[0]['unrealized_gain'] == 100
    assert series[0]['total_gain'] == 400


def test_consolidated_position_partial_sale_and_split():
    rows = [tx(1, 'Buy', 10, 20, 1), tx(2, 'Buy', 10, 40, 2), tx(3, 'Sell', 5, 50, 3)]
    rows[1].broker = 'B'
    event = Obj(id=1, event_type='STOCK_SPLIT', effective_date=date(2024, 1, 4), conversion_factor=2)
    asset = Obj(id=1, ticker='TEST', history=[Obj(date=date(2024, 1, 4), close=25)], corporate_events=[event])
    position = overview(rows, [asset])['positions'][0]
    assert (position['quantity'], position['average_cost'], position['acquisition_cost']) == (30, Decimal('16.66666666666666666666666667'), 500)
    assert position['total_value'] == 750
    assert [(p['broker'], p['quantity'], p['average_cost']) for p in position['broker_breakdown']] == [
        ('A', 10, 10), ('B', 20, 20),
    ]


def test_display_conversion_requires_all_fx_quotes():
    usd = tx(1, 'Buy', 2, 10, 1)
    usd.transaction_currency = 'USD'
    asset = Obj(id=1, ticker='TEST', transaction_currency='USD', history=[Obj(date=date(2024, 1, 2), close=12)])
    missing = overview([usd], [asset], display_currency='BRL')
    assert missing['positions'][0]['total_value'] == 24
    assert missing['positions'][0]['display_value'] is None
    assert missing['summary']['total_value'] is None
    assert missing['summary']['missing_fx'] == ['TEST (USD)']
    converted = overview([usd], [asset], display_currency='BRL',
                         display_factors={('USD', date(2024, 1, 2)): 5},
                         display_cost_factors={1: 4})
    assert converted['positions'][0]['display_value'] == 120
    assert converted['positions'][0]['display_acquisition_cost'] == 80
    assert converted['positions'][0]['display_average_cost'] == 40
    assert converted['summary']['total_value'] == 120


def test_fees_reduce_realized_gain_and_remain_in_unsold_cost():
    rows = [tx(1, 'Buy', 10, 20, 1), tx(2, 'Sell', 4, 30, 2)]
    rows[0].brokerage_fee, rows[0].other_fees = 8, 2
    rows[1].brokerage_fee, rows[1].other_fees = 3, 1
    assert cost_and_quantity(rows) == (21, 6)
    asset = Obj(id=1, ticker='TEST', history=[Obj(date=date(2024, 1, 2), close=30)])
    position = overview(rows, [asset])['positions'][0]
    assert position['acquisition_cost'] == 126
    assert position['realized_gain'] == 32
    assert position['unrealized_gain'] == 54
    assert position['current_total_gain'] == 86
    history = consolidated_profitability(rows, asset.history)[0]
    assert history['total_gain'] == 86


@pytest.mark.parametrize('with_quote', [False, True])
def test_liquidation_keeps_realized_gain_without_a_quote_after_sale(with_quote):
    rows = [tx(1, 'Buy', 10, 20, 1), tx(2, 'Sell', 10, 30, 3)]
    history = [Obj(date=date(2024, 1, 1), close=25)] if with_quote else []
    position = overview(rows, [Obj(id=1, ticker='TEST', history=history)])['positions'][0]
    assert position['quantity'] == position['acquisition_cost'] == position['total_value'] == 0
    assert position['realized_gain'] == position['current_total_gain'] == 100
    assert position['unrealized_gain'] == 0


def test_current_gain_uses_latest_holdings_without_rebuilding_history(monkeypatch):
    import src.domain as domain
    rows = [tx(1, 'Buy', 10, 20, 1), tx(2, 'Sell', 4, 30, 3), tx(3, 'Buy', 2, 25, 4)]
    asset = Obj(id=1, ticker='TEST', history=[Obj(date=date(2024, 1, 2), close=30)])
    def no_history(*args, **kwargs):
        pytest.fail('Current valuation must not rebuild the historical series')
    monkeypatch.setattr(domain, 'consolidated_profitability', no_history)
    position = overview(rows, [asset])['positions'][0]
    assert position['realized_gain'] == 40
    assert position['unrealized_gain'] == 70
    assert position['current_total_gain'] == 110
    assert position['history_behind_transactions']


def test_converted_acquisition_cost_includes_purchase_fees():
    row = tx(1, 'Buy', 2, 10, 1)
    row.transaction_currency = 'USD'
    row.brokerage_fee = 2
    result = overview([row], [], display_cost_factors={1: 5})
    assert result['positions'][0]['display_acquisition_cost'] == 110


def test_overview_does_not_combine_different_currencies():
    brl = tx(1, 'Buy', 2, 10, 1)
    brl.transaction_currency = 'BRL'
    usd = tx(2, 'Buy', 1, 20, 1)
    usd.asset = 'USD-ASSET'
    usd.transaction_currency = 'USD'
    assets = [
        Obj(id=1, instrument_id=('legacy', 'TEST'), ticker='TEST', transaction_currency='BRL', history=[Obj(date=date(2024, 1, 2), close=10)]),
        Obj(id=2, instrument_id=('legacy', 'USD-ASSET'), ticker='USD-ASSET', transaction_currency='USD', history=[Obj(date=date(2024, 1, 2), close=20)]),
    ]
    result = overview([brl, usd], assets)
    assert result['summary']['total_value'] is None
    assert result['summary']['priced_value'] == 20
    assert result['summary']['missing_fx'] == ['USD-ASSET (USD)']
    assert result['summary']['totals_by_currency'] == {'BRL': 20, 'USD': 20}


def test_legacy_files_are_readable_from_synthetic_fixtures(tmp_path, monkeypatch):
    import importlib
    import pandas as pd
    asset_module = importlib.import_module('src.models.asset')
    transaction_module = importlib.import_module('src.models.transaction')

    old_transaction_type = type('Transaction', (), {'__module__': 'src.models.transaction'})
    monkeypatch.setattr(transaction_module, 'Transaction', old_transaction_type)
    transaction = old_transaction_type()
    transaction.__dict__.update(
        id=1, date_time='2024-01-02 10:00:00', type='Buy', asset='TEST',
        broker='Broker', allocation_class='Stocks', quantity=2, price=10,
        brokerage_fee=0, other_fees=0, notes='',
    )
    transactions_path = tmp_path / 'transactions.pkl'
    transactions_path.write_bytes(pickle.dumps([transaction]))

    old_asset_type = type('Asset', (), {'__module__': 'src.models.asset'})
    monkeypatch.setattr(asset_module, 'Asset', old_asset_type)
    asset = old_asset_type()
    asset.__dict__.update(
        ticker='TEST', asset_class='Stocks', sector='', sub_sector='',
        history=pd.DataFrame(
            {'Close': [11.0], 'Dividends': [0.0], 'Stock Splits': [0.0]},
            index=pd.to_datetime(['2024-01-03'], utc=True),
        ),
    )
    assets_path = tmp_path / 'assets.pkl'
    assets_path.write_bytes(pickle.dumps([asset]))

    _, records = read_transactions(transactions_path)
    assets = read_assets(assets_path)
    assert len(records) == 1
    assert records[0].asset == 'TEST'
    late = old_transaction_type()
    late.__dict__.update(transaction.__dict__ | {'date_time': '2024-01-02 15:00:00', 'price': 30})
    transactions_path.write_bytes(pickle.dumps([late, transaction]))
    _, ordered_records = read_transactions(transactions_path)
    assert [record.price for record in ordered_records] == [10, 30]
    assert len(assets) == 1
    assert assets[0][1][0].close == 11


def test_unknown_pickle_global_rejected():
    with pytest.raises(pickle.UnpicklingError):
        TransactionReader(io.BytesIO(pickle.dumps(Exception('not a transaction')))).load()


def test_oversized_legacy_file_is_rejected_before_read(tmp_path, monkeypatch):
    path = tmp_path / 'oversized.pkl'
    with path.open('wb') as file:
        file.truncate(20_000_001)
    monkeypatch.setattr(
        type(path),
        'read_bytes',
        lambda self: pytest.fail('oversized file was read into memory'),
    )
    with pytest.raises(ValueError, match='20 MB'):
        read_transactions(path)
