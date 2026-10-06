"""Rebuild position history in each position's accounting currency.

Old snapshots, including BRL snapshots retained by 0023, were calculated in
the portfolio reporting currency. Their ledger checkpoints cannot be reused.
Portfolio snapshots were a derived BRL cache and are no longer persisted.
"""
from alembic import op


revision = '0024'
down_revision = '0023'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('DELETE FROM position_snapshots')
    op.execute('DELETE FROM portfolio_snapshots')
    op.execute('DELETE FROM position_invalidations')
    op.execute("""
        INSERT INTO position_invalidations (portfolio_id, instrument_id, dirty_from, reason)
        SELECT portfolio_id, instrument_id, MIN(day), 'accounting_currency'
        FROM (
            SELECT portfolio_id, instrument_id, MIN(trade_date) AS day
            FROM transactions GROUP BY portfolio_id, instrument_id
            UNION ALL
            SELECT a.portfolio_id, a.instrument_id, MIN(l.start_date) AS day
            FROM fixed_income_lots l JOIN assets a ON a.id = l.asset_id
            GROUP BY a.portfolio_id, a.instrument_id
        ) affected
        GROUP BY portfolio_id, instrument_id
    """)
    op.execute("""
        UPDATE portfolios SET
            dirty_from = (SELECT MIN(i.dirty_from) FROM position_invalidations i
                          WHERE i.portfolio_id = portfolios.id),
            history_built_through = NULL
    """)


def downgrade():
    # Reverting code still requires an explicit rebuild of derived histories.
    op.execute('DELETE FROM position_snapshots')
    op.execute('DELETE FROM portfolio_snapshots')
    op.execute('UPDATE portfolios SET history_built_through = NULL')
