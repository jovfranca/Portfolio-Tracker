"""Add insert-only historical FX and PTAX rates."""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'exchange_rates',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('rate_type', sa.String(4), nullable=False),
        sa.Column('reference_date', sa.Date, nullable=False),
        sa.Column('rate', sa.Numeric(28, 12), nullable=False),
        sa.Column('source', sa.String(80), nullable=False),
        sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('currency', 'rate_type', 'reference_date'),
        sa.CheckConstraint("rate_type IN ('FX', 'PTAX')", name='rate_type'),
        sa.CheckConstraint('rate > 0', name='positive_rate'),
    )
    op.create_index(
        'ix_exchange_rates_lookup',
        'exchange_rates',
        ['currency', 'rate_type', 'reference_date'],
    )


def downgrade():
    op.drop_index('ix_exchange_rates_lookup', table_name='exchange_rates')
    op.drop_table('exchange_rates')
