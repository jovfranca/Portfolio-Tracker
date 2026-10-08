"""Verify the invitation upgrade and downgrade on PostgreSQL, retaining legacy rows."""
import importlib
import os
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import text

from src.database import Base, engine


@pytest.mark.integration
@pytest.mark.skipif(os.getenv('RUN_DB_TESTS') != '1', reason='Requires a migrated PostgreSQL test database.')
def test_invitation_lifecycle_migration_preserves_legacy_and_terminal_tokens():
    migration = importlib.import_module('migrations.versions.0027_invitation_lifecycle')
    schema = 'invitation_' + uuid4().hex
    with engine.connect() as connection, connection.begin():
        connection.execute(text(f'CREATE SCHEMA {schema}'))
        connection.execute(text(f'SET LOCAL search_path TO {schema}'))
        connection.execute(text('CREATE TABLE users (id integer PRIMARY KEY)'))
        connection.execute(text('INSERT INTO users VALUES (1)'))
        connection.execute(text("CREATE TABLE household_invitations (id integer PRIMARY KEY, token_hash text, status varchar(16), CONSTRAINT ck_household_invitations_valid_status CHECK (status IN ('PENDING', 'ACCEPTED', 'REVOKED')))"))
        connection.execute(text("INSERT INTO household_invitations VALUES (1, 'private-hash', 'PENDING'), (2, 'accepted-hash', 'ACCEPTED')"))
        context = MigrationContext.configure(connection, opts={'target_metadata': Base.metadata})
        with Operations.context(context):
            migration.upgrade()
        assert connection.execute(text('SELECT id, token_hash, status, invited_by_user_id, resolved_at FROM household_invitations ORDER BY id')).all() == [
            (1, 'private-hash', 'PENDING', None, None), (2, 'accepted-hash', 'ACCEPTED', None, None)]
        connection.execute(text("UPDATE household_invitations SET status = 'REJECTED', invited_by_user_id = 1, resolved_by_user_id = 1, resolved_at = now() WHERE id = 1"))
        connection.execute(text('DELETE FROM users WHERE id = 1'))
        assert connection.execute(text('SELECT invited_by_user_id, resolved_by_user_id, resolved_at IS NOT NULL FROM household_invitations WHERE id = 1')).one() == (None, None, True)
        with Operations.context(context):
            migration.downgrade()
        assert connection.execute(text('SELECT id, token_hash, status FROM household_invitations ORDER BY id')).all() == [
            (1, 'private-hash', 'REVOKED'), (2, 'accepted-hash', 'ACCEPTED')]
        connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
