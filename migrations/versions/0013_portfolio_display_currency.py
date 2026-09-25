"""Add configurable portfolio reporting currency."""
from alembic import op
import sqlalchemy as sa


revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('portfolios', sa.Column('display_currency', sa.String(3),
                                          nullable=False, server_default='BRL'))
    op.create_check_constraint('ck_portfolios_display_currency', 'portfolios',
                               "display_currency ~ '^[A-Z]{3}$'")


def downgrade():
    op.drop_constraint('ck_portfolios_display_currency', 'portfolios', type_='check')
    op.drop_column('portfolios', 'display_currency')
