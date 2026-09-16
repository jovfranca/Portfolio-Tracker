from datetime import date, datetime
from types import SimpleNamespace as Obj
import pickle
import io
import pytest
from src.domain import cost_and_quantity, historical_profitability, overview
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
    assert len(result['positions']) == 2
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


def test_asset_cost_pooling_is_characterized():
    """Asset totals currently pool brokers while positions calculate separately."""
    rows = [tx(1, 'Buy', 10, 20, 1), tx(2, 'Buy', 10, 40, 2), tx(3, 'Sell', 10, 50, 3)]
    rows[1].broker = 'B'
    asset = Obj(id=1, ticker='TEST', history=[Obj(date=date(2024, 1, 3), close=50)])
    result = overview(rows, [asset])
    assert [(p['broker'], p['quantity'], p['average_cost']) for p in result['positions']] == [
        ('A', 0, 0), ('B', 10, 40),
    ]
    assert result['assets'][0]['average_cost'] == 30


def test_overview_does_not_combine_different_currencies():
    brl = tx(1, 'Buy', 2, 10, 1)
    brl.asset_currency = 'BRL'
    usd = tx(2, 'Buy', 1, 20, 1)
    usd.asset = 'USD-ASSET'
    usd.asset_currency = 'USD'
    assets = [
        Obj(id=1, ticker='TEST', history=[Obj(date=date(2024, 1, 2), close=10)]),
        Obj(id=2, ticker='USD-ASSET', history=[Obj(date=date(2024, 1, 2), close=20)]),
    ]
    result = overview([brl, usd], assets)
    assert result['summary']['total_value'] is None
    assert result['summary']['priced_value'] is None
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
