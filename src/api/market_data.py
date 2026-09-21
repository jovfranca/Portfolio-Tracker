"""Network adapters for asset prices and historical currency rates."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import math
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from src.config import rate_provider


def search_instruments(query):
    """Search Yahoo on demand; callers decide whether a result is selected."""
    params = urlencode({'q': query, 'quotesCount': 20, 'newsCount': 0})
    request = Request(
        f'https://query1.finance.yahoo.com/v1/finance/search?{params}',
        headers={'User-Agent': 'Portfolio-Tracker/1.0'},
    )
    with urlopen(request, timeout=15) as response:
        payload = json.load(response)
    type_map = {
        'EQUITY': 'STOCK', 'ETF': 'ETF', 'CRYPTOCURRENCY': 'CRYPTO',
    }
    results = []
    for item in payload.get('quotes', []):
        provider_symbol = item.get('symbol')
        currency = item.get('currency')
        if not provider_symbol:
            continue
        quote_type = str(item.get('quoteType', 'OTHER')).upper()
        canonical_symbol = (
            str(item.get('fromCurrency')).upper()
            if quote_type == 'CRYPTOCURRENCY' and item.get('fromCurrency')
            else '' if quote_type == 'CRYPTOCURRENCY' else provider_symbol.upper()
        )
        results.append({
            'symbol': canonical_symbol,
            'name': item.get('longname') or item.get('shortname') or provider_symbol,
            'asset_type': type_map.get(quote_type, 'OTHER'),
            'exchange': item.get('exchange'),
            # Search metadata can omit currency; require explicit selection then.
            'currency': currency.upper() if currency and quote_type in ('EQUITY', 'ETF') else None,
            'quote_currency': currency.upper() if currency else None,
            'provider': 'yfinance',
            'provider_symbol': provider_symbol.upper(),
            'provider_exchange': item.get('exchDisp') or item.get('exchange'),
        })
    return results


def fetch_history(ticker, currency, start, end):
    """Fetch unadjusted daily closes for an inclusive, bounded range."""
    import yfinance as yf
    instrument = yf.Ticker(ticker)
    frame = instrument.history(
        start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(),
        interval='1d', auto_adjust=False, timeout=15, raise_errors=True,
    )
    metadata = instrument.get_history_metadata()
    _verify_currency(metadata, currency)
    exchange_timezone = _exchange_timezone(metadata)
    retrieved_at = datetime.now(timezone.utc)
    rows = []
    for timestamp, row in frame.iterrows():
        trading_date = _trading_date(timestamp, exchange_timezone)
        if not start <= trading_date <= end:
            continue
        if trading_date >= retrieved_at.astimezone(exchange_timezone).date():
            raise ValueError('O fechamento diário ainda não é final no fuso do mercado.')
        close = float(row['Close'])
        if not math.isfinite(close) or close <= 0:
            raise ValueError('O provedor retornou um fechamento inválido.')
        dividends = float(row.get('Dividends', 0))
        splits = float(row.get('Stock Splits', 0))
        rows.append({
            'date': trading_date, 'price': Decimal(str(close)),
            'dividends': Decimal(str(dividends)) if math.isfinite(dividends) else Decimal('0'),
            'stock_splits': Decimal(str(splits)) if math.isfinite(splits) else Decimal('0'),
            'currency': currency, 'source': 'yfinance', 'retrieved_at': retrieved_at,
        })
    return rows


def _verify_currency(metadata, currency):
    # Preserve case: Yahoo's GBp denotes pence, not GBP (pounds).
    actual = metadata.get('currency')
    if actual != currency:
        raise ValueError(f'Provider currency {actual!r} does not match {currency!r}.')


def _exchange_timezone(metadata):
    name = metadata.get('exchangeTimezoneName')
    if not name:
        raise ValueError('O provedor não informou o fuso horário do mercado.')
    try:
        return ZoneInfo(name)
    except Exception as error:
        raise ValueError(f'O provedor informou um fuso horário inválido: {name!r}.') from error


def _market_datetime(value, exchange_timezone):
    if hasattr(value, 'to_pydatetime'):
        value = value.to_pydatetime()
    if not hasattr(value, 'date') or not hasattr(value, 'tzinfo'):
        raise ValueError('O provedor não informou o horário da cotação regular.')
    if value.tzinfo is None:
        return value.replace(tzinfo=exchange_timezone)
    return value.astimezone(exchange_timezone)


def _trading_date(value, exchange_timezone):
    return _market_datetime(value, exchange_timezone).date()


def fetch_latest(ticker, currency):
    """Fetch Yahoo's canonical regular-session price and market timestamp."""
    import yfinance as yf
    instrument = yf.Ticker(ticker)
    metadata = instrument.get_history_metadata()
    _verify_currency(metadata, currency)
    exchange_timezone = _exchange_timezone(metadata)
    price = float(metadata.get('regularMarketPrice', math.nan))
    if not math.isfinite(price) or price <= 0:
        raise ValueError('O provedor não retornou uma cotação regular válida.')
    market_at = _market_datetime(metadata.get('regularMarketTime'), exchange_timezone)
    return {
        'price': Decimal(str(price)), 'currency': currency, 'source': 'yfinance',
        'market_at': market_at, 'retrieved_at': datetime.now(timezone.utc),
    }


def fetch_rates(currency, rate_type, start, end):
    """Fetch BRL per currency unit for the inclusive date range."""
    currency = currency.upper()
    rate_type = rate_type.upper()
    if currency == 'BRL':
        retrieved_at = datetime.now(timezone.utc)
        sides = ['BUY', 'SELL'] if rate_type == 'PTAX' else ['MARKET']
        return [
            {
                'currency': currency,
                'rate_type': rate_type,
                'rate_side': side,
                'reference_date': start + timedelta(days=offset),
                'rate': Decimal('1'),
                'source': 'identity',
                'retrieved_at': retrieved_at,
            }
            for offset in range((end - start).days + 1)
            for side in sides
        ]

    provider = rate_provider(rate_type)
    if provider == 'yfinance':
        return _fetch_yfinance_rates(currency, rate_type, start, end)
    if provider == 'bcb':
        return _fetch_ptax_rates(currency, rate_type, start, end)
    raise ValueError(f'Provedor de câmbio não suportado: {provider}.')


def _fetch_yfinance_rates(currency, rate_type, start, end):
    import yfinance as yf

    frame = yf.Ticker(f'{currency}BRL=X').history(
        start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(),
        interval='1d', auto_adjust=False, timeout=15, raise_errors=True,
    )
    retrieved_at = datetime.now(timezone.utc)
    rows = []
    for timestamp, item in frame.iterrows():
        # Yahoo includes the live daily candle. It is not immutable history yet.
        if timestamp.date() >= datetime.now(timestamp.tzinfo).date():
            continue
        close = float(item['Close'])
        if math.isfinite(close) and close > 0:
            rows.append({
                'currency': currency,
                'rate_type': rate_type,
                'rate_side': 'MARKET',
                'reference_date': timestamp.date(),
                'rate': Decimal(str(close)),
                'source': 'yfinance',
                'retrieved_at': retrieved_at,
            })
    if not rows:
        raise ValueError('O provedor não retornou taxas de câmbio válidas.')
    return rows


def _fetch_ptax_rates(currency, rate_type, start, end):
    base = (
        'https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/'
        'CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)'
    )
    params = {
        '@moeda': f"'{currency}'",
        '@dataInicial': f"'{start:%m-%d-%Y}'",
        '@dataFinalCotacao': f"'{end:%m-%d-%Y}'",
        '$format': 'json',
        '$select': 'cotacaoCompra,cotacaoVenda,dataHoraCotacao,tipoBoletim',
    }
    request = Request(f'{base}?{urlencode(params)}', headers={'User-Agent': 'Portfolio-Tracker/1.0'})
    with urlopen(request, timeout=15) as response:
        payload = json.load(response)
    return _parse_ptax_rows(currency, rate_type, payload.get('value', []))


def _parse_ptax_rows(currency, rate_type, values):
    """Keep both rates from the final PTAX bulletin published for each date."""
    candidates = {}
    for item in values:
        raw_timestamp = item.get('dataHoraCotacao')
        if not raw_timestamp or item.get('tipoBoletim') not in {'Fechamento', 'Fechamento PTAX'}:
            continue
        timestamp = datetime.fromisoformat(raw_timestamp.replace('Z', '+00:00'))
        current = candidates.get(timestamp.date())
        rank = timestamp
        if current is None or rank > current[0]:
            candidates[timestamp.date()] = (rank, item)

    retrieved_at = datetime.now(timezone.utc)
    rows = []
    for reference_date, (_, item) in sorted(candidates.items()):
        try:
            pair = [Decimal(str(item[field])) for field in ('cotacaoCompra', 'cotacaoVenda')]
        except (KeyError, InvalidOperation):
            continue
        if not all(rate.is_finite() and rate > 0 for rate in pair):
            continue
        for side, rate in zip(('BUY', 'SELL'), pair):
            rows.append({
                'currency': currency,
                'rate_type': rate_type,
                'rate_side': side,
                'reference_date': reference_date,
                'rate': rate,
                'source': 'bcb-ptax-closing',
                'retrieved_at': retrieved_at,
            })
    if not rows:
        raise ValueError('O Banco Central não retornou taxas PTAX válidas.')
    return rows
