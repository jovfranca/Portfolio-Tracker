"""Environment-backed application configuration."""
import os
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
