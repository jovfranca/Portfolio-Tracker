import pytest

from src.reset_local_db import validated_local_target


@pytest.mark.parametrize('suffix', ['?host=remote.example.com', '?dbname=production', '?service=production'])
def test_reset_rejects_connection_overrides(suffix):
    with pytest.raises(ValueError, match='query'):
        validated_local_target('postgresql+psycopg://user:secret@localhost/example_dev' + suffix)


def test_reset_accepts_only_recognized_local_development_database():
    assert validated_local_target(
        'postgresql+psycopg://portfolio:secret@127.0.0.1:5432/portfolio_tracker'
    ).database == 'portfolio_tracker'
    assert validated_local_target(
        'postgresql+psycopg://portfolio:secret@localhost/example_dev'
    ).database == 'example_dev'
    with pytest.raises(ValueError, match='localhost'):
        validated_local_target('postgresql+psycopg://portfolio:secret@db.example.com/portfolio_tracker')
    with pytest.raises(ValueError, match='database'):
        validated_local_target('postgresql+psycopg://portfolio:secret@localhost/production')
