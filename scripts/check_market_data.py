"""Manual network smoke test for the configured market-data provider."""
from datetime import date, timedelta

from src.api.market_data import fetch_history


if __name__ == '__main__':
    start = date.today() - timedelta(days=30)
    rows = fetch_history('AAPL', start)
    print(f'Received {len(rows)} rows; latest date: {rows[-1]["date"]}')
