"""Rebuild CDI portfolio history using completed daily benchmark periods."""
from alembic import op


revision = '0022'
down_revision = '0021'
branch_labels = None
depends_on = None


def upgrade():
    # Only derived history is invalidated; preserve contracts and movements.
    op.execute("""
        UPDATE portfolios
        SET dirty_from = CASE
            WHEN portfolios.dirty_from IS NULL OR portfolios.dirty_from > affected.day
            THEN affected.day ELSE portfolios.dirty_from END
        FROM (
            SELECT assets.portfolio_id, MIN(fixed_income_lots.start_date) AS day
            FROM fixed_income_lots
            JOIN assets ON assets.id = fixed_income_lots.asset_id
            JOIN benchmarks ON benchmarks.id = fixed_income_lots.benchmark_id
            WHERE benchmarks.code = 'CDI'
            GROUP BY assets.portfolio_id
        ) AS affected
        WHERE portfolios.id = affected.portfolio_id
    """)


def downgrade():
    # An invalidated cache cannot be restored; the previous code can rebuild it.
    pass
