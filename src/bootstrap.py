"""Create the configured database if missing; never reset an existing database."""
import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url
from src.config import database_url


def main():
    url = make_url(database_url())
    with psycopg.connect(host=url.host, port=url.port or 5432, user=url.username,
                         password=url.password, dbname='postgres', autocommit=True) as connection:
        exists = connection.execute('SELECT 1 FROM pg_database WHERE datname = %s', (url.database,)).fetchone()
        if not exists:
            connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(url.database)))
    print('Banco PostgreSQL pronto.')


if __name__ == '__main__':
    main()
