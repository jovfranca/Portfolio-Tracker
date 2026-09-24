"""Add shared corporate actions and private portfolio events."""
from alembic import op
import sqlalchemy as sa


revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


EVENT_TYPES = "event_type IN ('STOCK_SPLIT', 'REVERSE_SPLIT', 'DIVIDEND', 'JCP', 'AMORTIZATION')"
EVENT_VALUES = """(
    (event_type = 'STOCK_SPLIT' AND conversion_factor > 1 AND amount_per_unit IS NULL AND currency IS NULL)
    OR (event_type = 'REVERSE_SPLIT' AND conversion_factor > 0 AND conversion_factor < 1 AND amount_per_unit IS NULL AND currency IS NULL)
    OR (event_type IN ('DIVIDEND', 'JCP', 'AMORTIZATION') AND amount_per_unit IS NOT NULL AND currency IS NOT NULL AND conversion_factor IS NULL)
)"""


def upgrade():
    op.create_table(
        'corporate_actions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('instrument_id', sa.Integer(), sa.ForeignKey('instruments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_type', sa.String(24), nullable=False),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('payment_date', sa.Date(), nullable=True),
        sa.Column('amount_per_unit', sa.Numeric(28, 12), nullable=True),
        sa.Column('conversion_factor', sa.Numeric(28, 12), nullable=True),
        sa.Column('currency', sa.String(3), nullable=True),
        sa.Column('source', sa.String(80), nullable=False),
        sa.Column('provider_event_id', sa.String(160), nullable=True),
        sa.Column('event_key', sa.String(64), nullable=False),
        sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(EVENT_TYPES, name='ck_corporate_actions_event_type'),
        sa.CheckConstraint(EVENT_VALUES, name='ck_corporate_actions_event_values'),
        sa.CheckConstraint('amount_per_unit IS NULL OR amount_per_unit >= 0', name='ck_corporate_actions_nonnegative_amount'),
        sa.CheckConstraint('conversion_factor IS NULL OR conversion_factor > 0', name='ck_corporate_actions_positive_factor'),
        sa.CheckConstraint("currency IS NULL OR (length(currency) = 3 AND currency = upper(currency))", name='ck_corporate_actions_currency'),
        sa.UniqueConstraint('instrument_id', 'source', 'event_key'),
    )
    op.create_index('ix_corporate_actions_lookup', 'corporate_actions', ['instrument_id', 'effective_date', 'event_type'])
    op.create_table(
        'corporate_action_coverage',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('instrument_id', sa.Integer(), sa.ForeignKey('instruments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source', sa.String(80), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('end_date >= start_date', name='ck_corporate_action_coverage_valid_range'),
        sa.UniqueConstraint('instrument_id', 'source', 'start_date', 'end_date'),
    )
    op.create_index('ix_corporate_action_coverage_lookup', 'corporate_action_coverage', ['instrument_id', 'source'])
    op.create_table(
        'user_corporate_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('asset_id', sa.Integer(), sa.ForeignKey('assets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_type', sa.String(24), nullable=False),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('payment_date', sa.Date(), nullable=True),
        sa.Column('amount_per_unit', sa.Numeric(28, 12), nullable=True),
        sa.Column('conversion_factor', sa.Numeric(28, 12), nullable=True),
        sa.Column('currency', sa.String(3), nullable=True),
        sa.Column('source', sa.String(80), nullable=False, server_default='manual'),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(EVENT_TYPES, name='ck_user_corporate_events_event_type'),
        sa.CheckConstraint(EVENT_VALUES, name='ck_user_corporate_events_event_values'),
        sa.CheckConstraint('amount_per_unit IS NULL OR amount_per_unit >= 0', name='ck_user_corporate_events_nonnegative_amount'),
        sa.CheckConstraint('conversion_factor IS NULL OR conversion_factor > 0', name='ck_user_corporate_events_positive_factor'),
        sa.CheckConstraint("currency IS NULL OR (length(currency) = 3 AND currency = upper(currency))", name='ck_user_corporate_events_currency'),
        sa.UniqueConstraint('asset_id', 'event_type', 'effective_date'),
    )
    op.create_index('ix_user_corporate_events_lookup', 'user_corporate_events', ['asset_id', 'effective_date', 'event_type'])
    op.create_index(
        'uq_user_corporate_events_split_date', 'user_corporate_events',
        ['asset_id', 'effective_date'], unique=True,
        postgresql_where=sa.text("event_type IN ('STOCK_SPLIT', 'REVERSE_SPLIT')"),
        sqlite_where=sa.text("event_type IN ('STOCK_SPLIT', 'REVERSE_SPLIT')"),
    )


def downgrade():
    op.drop_table('user_corporate_events')
    op.drop_table('corporate_action_coverage')
    op.drop_table('corporate_actions')
