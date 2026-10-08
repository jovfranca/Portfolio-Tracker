"""Persist invitation authors and recipient rejection without guessing legacy audit data."""
from alembic import op
import sqlalchemy as sa

revision = '0027'
down_revision = '0026'
branch_labels = depends_on = None


def upgrade():
    op.add_column('household_invitations', sa.Column('invited_by_user_id', sa.Integer(), nullable=True))
    op.add_column('household_invitations', sa.Column('resolved_by_user_id', sa.Integer(), nullable=True))
    op.add_column('household_invitations', sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True))
    for field in ('invited_by_user_id', 'resolved_by_user_id'):
        op.create_foreign_key(f'fk_household_invitations_{field}_users', 'household_invitations',
                              'users', [field], ['id'], ondelete='SET NULL')
    op.drop_constraint(op.f('ck_household_invitations_valid_status'), 'household_invitations', type_='check')
    op.create_check_constraint('valid_status', 'household_invitations',
                               "status IN ('PENDING', 'ACCEPTED', 'REJECTED', 'REVOKED')")


def downgrade():
    # Rejected tokens remain unusable in the old lifecycle.
    op.execute("UPDATE household_invitations SET status = 'REVOKED' WHERE status = 'REJECTED'")
    op.drop_constraint(op.f('ck_household_invitations_valid_status'), 'household_invitations', type_='check')
    op.create_check_constraint('valid_status', 'household_invitations',
                               "status IN ('PENDING', 'ACCEPTED', 'REVOKED')")
    for field in ('invited_by_user_id', 'resolved_by_user_id'):
        op.drop_constraint(f'fk_household_invitations_{field}_users', 'household_invitations', type_='foreignkey')
        op.drop_column('household_invitations', field)
    op.drop_column('household_invitations', 'resolved_at')
