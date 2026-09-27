"""Require each benchmark observation's mapping to belong to its benchmark."""
from alembic import op


revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        'uq_benchmark_provider_mappings_id', 'benchmark_provider_mappings',
        ['id', 'benchmark_id'])
    op.create_foreign_key(
        'fk_benchmark_observations_mapping_benchmark',
        'benchmark_observations', 'benchmark_provider_mappings',
        ['provider_mapping_id', 'benchmark_id'], ['id', 'benchmark_id'],
        ondelete='RESTRICT')


def downgrade():
    op.drop_constraint(
        'fk_benchmark_observations_mapping_benchmark',
        'benchmark_observations', type_='foreignkey')
    op.drop_constraint(
        'uq_benchmark_provider_mappings_id',
        'benchmark_provider_mappings', type_='unique')
