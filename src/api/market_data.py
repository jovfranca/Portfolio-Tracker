"""Network adapter. Manual prices work without any external provider."""
from datetime import date, timedelta
import math


def fetch_history(ticker, start):
    import yfinance as yf
    frame = yf.Ticker(ticker).history(
        start=start.isoformat(), end=(date.today() + timedelta(days=1)).isoformat(),
        interval='1d', auto_adjust=True, timeout=15, raise_errors=True,
    )
    if frame.empty:
        raise ValueError('O provedor não retornou cotações para o ativo e período.')
    rows = []
    for timestamp, row in frame.iterrows():
        close = float(row['Close'])
        if not math.isfinite(close) or close < 0:
            continue
        dividends = float(row.get('Dividends', 0))
        splits = float(row.get('Stock Splits', 0))
        rows.append({
            'date': timestamp.date(), 'close': close,
            'dividends': dividends if math.isfinite(dividends) else 0,
            'stock_splits': splits if math.isfinite(splits) else 0,
            'source': 'yfinance',
        })
    if not rows:
        raise ValueError('Nenhuma cotação válida foi recebida.')
    return rows
