"""Canonical benchmarks, provider mappings and shared observation history."""
from alembic import op
import sqlalchemy as sa


revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('benchmarks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('code', sa.String(40), nullable=False, unique=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('kind', sa.String(40), nullable=False),
        sa.Column('frequency', sa.String(20), nullable=False),
        sa.Column('value_type', sa.String(40), nullable=False),
        sa.Column('unit', sa.String(80), nullable=False),
        sa.Column('reference_currency', sa.String(3)),
        sa.Column('jurisdiction', sa.String(40)),
        sa.Column('status', sa.String(16), nullable=False))
    op.create_table('benchmark_provider_mappings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('benchmark_id', sa.Integer(), sa.ForeignKey('benchmarks.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('provider', sa.String(80), nullable=False),
        sa.Column('series_id', sa.String(120), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('is_primary', sa.Boolean(), nullable=False),
        sa.UniqueConstraint('provider', 'series_id'),
        sa.CheckConstraint('NOT is_primary OR active', name='ck_benchmark_provider_mappings_primary_mapping_active'))
    op.create_index('uq_benchmark_primary_mapping', 'benchmark_provider_mappings',
                    ['benchmark_id'], unique=True, postgresql_where=sa.text('is_primary'))
    op.create_table('benchmark_observations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('benchmark_id', sa.Integer(), sa.ForeignKey('benchmarks.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('provider_mapping_id', sa.Integer(), sa.ForeignKey('benchmark_provider_mappings.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('reference_date', sa.Date(), nullable=False),
        sa.Column('value', sa.Numeric(28, 12), nullable=False),
        sa.Column('source', sa.String(80), nullable=False),
        sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('provider_mapping_id', 'reference_date', 'retrieved_at'))
    op.create_index('ix_benchmark_observations_lookup', 'benchmark_observations',
                    ['benchmark_id', 'reference_date'])
    op.create_table('benchmark_coverage',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('provider_mapping_id', sa.Integer(), sa.ForeignKey('benchmark_provider_mappings.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('provider_mapping_id', 'start_date', 'end_date'),
        sa.CheckConstraint('end_date >= start_date', name='ck_benchmark_coverage_valid_range'))


def downgrade():
    op.drop_table('benchmark_coverage')
    op.drop_index('ix_benchmark_observations_lookup', table_name='benchmark_observations')
    op.drop_table('benchmark_observations')
    op.drop_index('uq_benchmark_primary_mapping', table_name='benchmark_provider_mappings')
    op.drop_table('benchmark_provider_mappings')
    op.drop_table('benchmarks')
