"""Explicitly destroy and recreate only the recognized local development DB."""
import argparse
import subprocess
import sys

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from src.config import database_url


def validated_local_target(url_text):
    url = make_url(url_text)
    if url.query:
        raise ValueError('Reset refused: DATABASE_URL query options are not allowed.')
    if url.drivername != 'postgresql+psycopg':
        raise ValueError('Reset refused: use the postgresql+psycopg driver.')
    if url.host not in {'127.0.0.1', 'localhost'}:
        raise ValueError('Reset refused: DATABASE_URL must target localhost.')
    if url.database != 'portfolio_tracker' and not (url.database or '').endswith('_dev'):
        raise ValueError(
            'Reset refused: database must be named portfolio_tracker or end with _dev.'
        )
    if not url.username or not url.database:
        raise ValueError('Reset refused: incomplete DATABASE_URL.')
    return url


def reset_database(url):
    with psycopg.connect(
        host=url.host, port=url.port or 5432, user=url.username,
        password=url.password, dbname='postgres', autocommit=True,
    ) as connection:
        connection.execute(
            'SELECT pg_terminate_backend(pid) FROM pg_stat_activity '
            'WHERE datname = %s AND pid <> pg_backend_pid()',
            (url.database,),
        )
        connection.execute(sql.SQL('DROP DATABASE IF EXISTS {}').format(sql.Identifier(url.database)))
        connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(url.database)))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Reset the local development database.')
    parser.add_argument('--confirm-local-reset', action='store_true')
    args = parser.parse_args(argv)
    if not args.confirm_local_reset:
        parser.error('--confirm-local-reset is required')
    url = validated_local_target(database_url())
    print(f'Resetting local development database {url.database} on {url.host}:{url.port or 5432}.')
    reset_database(url)
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], check=True)
    subprocess.run([sys.executable, '-m', 'src.instrument_catalog'], check=True)
    print('Local database reset, migrated, and seeded.')


if __name__ == '__main__':
    main()
