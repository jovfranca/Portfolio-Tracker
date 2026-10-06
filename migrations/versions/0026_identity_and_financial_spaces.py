"""Identity, sessions and financial-space access; retain all financial history."""
from alembic import op
import sqlalchemy as sa

revision = '0026'
down_revision = '0025'
branch_labels = None
depends_on = None


def timestamp():
    return sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)


def upgrade():
    op.create_table('users',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('display_name', sa.String(120), nullable=False), timestamp(),
        sa.Column('active', sa.Boolean(), nullable=False))
    op.create_table('households',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(120), nullable=False), timestamp())
    op.create_table('auth_identities',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('provider', sa.String(32), nullable=False),
        sa.Column('provider_subject', sa.String(255), nullable=False),
        sa.Column('email', sa.String(254), nullable=True),
        sa.Column('email_verified', sa.Boolean(), nullable=False), timestamp(),
        sa.UniqueConstraint('provider', 'provider_subject'))
    op.create_index('ix_auth_identities_user_id', 'auth_identities', ['user_id'])
    op.create_table('memberships',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('household_id', sa.Integer(), sa.ForeignKey('households.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(16), nullable=False), timestamp(),
        sa.UniqueConstraint('user_id', 'household_id'),
        sa.CheckConstraint("role IN ('OWNER', 'EDITOR', 'VIEWER')", name='valid_role'))
    op.create_index('ix_memberships_household_id', 'memberships', ['household_id'])
    op.create_table('auth_sessions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False), timestamp(),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('token_hash'))
    op.create_index('ix_auth_sessions_user_id', 'auth_sessions', ['user_id'])
    op.create_table('auth_challenges',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('token_hash', sa.String(64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('token_hash'))
    op.create_table('household_invitations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('household_id', sa.Integer(), sa.ForeignKey('households.id', ondelete='CASCADE'), nullable=False),
        sa.Column('email', sa.String(254), nullable=False),
        sa.Column('role', sa.String(16), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False), timestamp(),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('token_hash'),
        sa.CheckConstraint("role IN ('OWNER', 'EDITOR', 'VIEWER')", name='valid_role'),
        sa.CheckConstraint("status IN ('PENDING', 'ACCEPTED', 'REVOKED')", name='valid_status'))
    op.create_index('ix_household_invitations_household_id', 'household_invitations', ['household_id'])
    bind = op.get_bind()
    uid = bind.execute(sa.text(
        "INSERT INTO users (display_name, created_at, active) VALUES ('Local user', CURRENT_TIMESTAMP, true) RETURNING id"
    )).scalar_one()
    hid = bind.execute(sa.text(
        "INSERT INTO households (name, created_at) VALUES ('Personal', CURRENT_TIMESTAMP) RETURNING id"
    )).scalar_one()
    bind.execute(sa.text("INSERT INTO memberships (user_id, household_id, role, created_at) VALUES (:uid, :hid, 'OWNER', CURRENT_TIMESTAMP)"), {'uid': uid, 'hid': hid})
    bind.execute(sa.text("INSERT INTO auth_identities (user_id, provider, provider_subject, email_verified, created_at) VALUES (:uid, 'LOCAL', 'local', false, CURRENT_TIMESTAMP)"), {'uid': uid})
    op.add_column('portfolios', sa.Column('household_id', sa.Integer(), nullable=True))
    bind.execute(sa.text('UPDATE portfolios SET household_id = :hid'), {'hid': hid})
    op.alter_column('portfolios', 'household_id', nullable=False)
    op.create_foreign_key(None, 'portfolios', 'households', ['household_id'], ['id'], ondelete='RESTRICT')
    op.create_index('ix_portfolios_household_id', 'portfolios', ['household_id'])
    op.add_column('instruments', sa.Column('household_id', sa.Integer(), nullable=True))
    bind.execute(sa.text("UPDATE instruments SET household_id = :hid WHERE origin <> 'CATALOG'"), {'hid': hid})
    op.create_foreign_key(None, 'instruments', 'households', ['household_id'], ['id'], ondelete='RESTRICT')
    op.create_index('ix_instruments_household_id', 'instruments', ['household_id'])
    # Custom crypto identities may repeat across spaces, without merging private metadata.
    op.drop_index('uq_instruments_crypto_symbol', table_name='instruments')
    op.create_index('uq_instruments_crypto_symbol', 'instruments', ['symbol'], unique=True,
                    postgresql_where=sa.text("asset_type = 'CRYPTO' AND household_id IS NULL"))
    op.create_index('uq_instruments_private_crypto_symbol', 'instruments', ['household_id', 'symbol'], unique=True,
                    postgresql_where=sa.text("asset_type = 'CRYPTO' AND household_id IS NOT NULL"))


def downgrade():
    # Refuse rollback after multi-user use: removing access boundaries would expose private data.
    bind = op.get_bind()
    if bind.scalar(sa.text('SELECT COUNT(*) FROM households')) > 1 or bind.scalar(sa.text('SELECT COUNT(*) FROM users')) > 1:
        raise RuntimeError('Cannot remove financial-space isolation after multi-user use.')
    op.drop_index('uq_instruments_private_crypto_symbol', table_name='instruments')
    op.drop_index('uq_instruments_crypto_symbol', table_name='instruments')
    op.create_index('uq_instruments_crypto_symbol', 'instruments', ['symbol'], unique=True,
                    postgresql_where=sa.text("asset_type = 'CRYPTO'"))
    for table in ('instruments', 'portfolios'):
        op.drop_index(f'ix_{table}_household_id', table_name=table)
        op.drop_constraint(f'fk_{table}_household_id_households', table, type_='foreignkey')
        op.drop_column(table, 'household_id')
    for table in ('household_invitations', 'auth_challenges', 'auth_sessions', 'memberships', 'auth_identities', 'households', 'users'):
        op.drop_table(table)
