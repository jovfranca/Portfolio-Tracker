import pytest

from src.config import (
    allowed_origins, database_url, market_data_provider, quote_ttl, rate_fallback_days,
    rate_provider,
)


def test_database_url_normalizes_postgresql_scheme(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgresql://user:password@localhost/example')
    assert database_url() == 'postgresql+psycopg://user:password@localhost/example'


def test_database_url_rejects_other_database_engines(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///portfolio.db')
    with pytest.raises(ValueError, match='PostgreSQL'):
        database_url()


def test_allowed_origins_ignores_empty_entries(monkeypatch):
    monkeypatch.setenv('ALLOWED_ORIGINS', 'http://localhost:5173, ,http://127.0.0.1:5173')
    assert allowed_origins() == [
        'http://localhost:5173',
        'http://127.0.0.1:5173',
    ]


def test_rate_provider_defaults_and_validation(monkeypatch):
    monkeypatch.delenv('FX_RATE_PROVIDER', raising=False)
    monkeypatch.delenv('PTAX_RATE_PROVIDER', raising=False)
    assert rate_provider('fx') == 'yfinance'
    assert rate_provider('PTAX') == 'bcb'
    monkeypatch.setenv('FX_RATE_PROVIDER', 'unknown')
    with pytest.raises(ValueError, match='não suportado'):
        rate_provider('FX')


def test_rate_fallback_days_is_bounded(monkeypatch):
    monkeypatch.setenv('RATE_FALLBACK_DAYS', '0')
    with pytest.raises(ValueError, match='entre 1 e 31'):
        rate_fallback_days()


def test_market_price_provider_and_quote_ttl(monkeypatch):
    monkeypatch.delenv('MARKET_DATA_PROVIDER', raising=False)
    monkeypatch.delenv('MARKET_QUOTE_TTL_MINUTES', raising=False)
    assert market_data_provider() == 'yfinance'
    assert quote_ttl().total_seconds() == 15 * 60
    monkeypatch.setenv('MARKET_DATA_PROVIDER', 'unknown')
    with pytest.raises(ValueError, match='não suportado'):
        market_data_provider()
    monkeypatch.setenv('MARKET_DATA_PROVIDER', 'yfinance')
    monkeypatch.setenv('MARKET_QUOTE_TTL_MINUTES', '0')
    with pytest.raises(ValueError, match='entre 1 e 1440'):
        quote_ttl()
