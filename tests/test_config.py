import pytest

from src.config import allowed_origins, database_url


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
