"""Environment-backed application configuration."""
import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')


def database_url():
    url = os.getenv(
        'DATABASE_URL',
        'postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio_tracker',
    )
    if url.startswith('postgresql://'):
        url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
    if not url.startswith('postgresql+psycopg://'):
        raise ValueError('DATABASE_URL deve usar PostgreSQL com psycopg.')
    return url


def allowed_origins():
    value = os.getenv(
        'ALLOWED_ORIGINS',
        'http://localhost:5173,http://127.0.0.1:5173',
    )
    return [origin.strip() for origin in value.split(',') if origin.strip()]


def rate_provider(rate_type):
    defaults = {'FX': 'yfinance', 'PTAX': 'bcb'}
    normalized = rate_type.upper()
    if normalized not in defaults:
        raise ValueError('Tipo de cotação deve ser FX ou PTAX.')
    value = os.getenv(f'{normalized}_RATE_PROVIDER', defaults[normalized]).strip().lower()
    supported = {'FX': {'yfinance'}, 'PTAX': {'bcb'}}
    if value not in supported[normalized]:
        raise ValueError(f'Provedor {value!r} não suportado para {normalized}.')
    return value


def rate_fallback_days():
    try:
        value = int(os.getenv('RATE_FALLBACK_DAYS', '7'))
    except ValueError as error:
        raise ValueError('RATE_FALLBACK_DAYS deve ser um inteiro.') from error
    if not 1 <= value <= 31:
        raise ValueError('RATE_FALLBACK_DAYS deve estar entre 1 e 31.')
    return value


def market_data_provider():
    value = os.getenv('MARKET_DATA_PROVIDER', 'yfinance').strip().lower()
    if value != 'yfinance':
        raise ValueError(f'Provedor de cotações {value!r} não suportado.')
    return value


def quote_ttl():
    try:
        minutes = int(os.getenv('MARKET_QUOTE_TTL_MINUTES', '15'))
    except ValueError as error:
        raise ValueError('MARKET_QUOTE_TTL_MINUTES deve ser um inteiro.') from error
    if not 1 <= minutes <= 1440:
        raise ValueError('MARKET_QUOTE_TTL_MINUTES deve estar entre 1 e 1440.')
    return timedelta(minutes=minutes)
