"""Initial PostgreSQL schema; balances are calculated from transactions."""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('portfolios', sa.Column('id', sa.Integer, primary_key=True), sa.Column('name', sa.String(120), nullable=False))
    op.create_table('brokers', sa.Column('id', sa.Integer, primary_key=True),
                    sa.Column('name', sa.String(120), nullable=False), sa.UniqueConstraint('name'))
    op.create_table('assets',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('portfolio_id', sa.Integer, sa.ForeignKey('portfolios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ticker', sa.String(40), nullable=False),
        sa.Column('asset_class', sa.String(120), nullable=False),
        sa.Column('sector', sa.String(120), nullable=False),
        sa.Column('sub_sector', sa.String(120), nullable=False),
        sa.UniqueConstraint('portfolio_id', 'ticker'))
    op.create_table('transactions',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('portfolio_id', sa.Integer, sa.ForeignKey('portfolios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('date_time', sa.DateTime, nullable=False),
        sa.Column('type', sa.String(4), nullable=False),
        sa.Column('asset', sa.String(40), nullable=False),
        sa.Column('broker', sa.String(120), nullable=False),
        sa.Column('allocation_class', sa.String(120), nullable=False),
        sa.Column('quantity', sa.Float, nullable=False),
        sa.Column('price', sa.Float, nullable=False),
        sa.Column('brokerage_fee', sa.Float, nullable=False),
        sa.Column('other_fees', sa.Float, nullable=False),
        sa.Column('notes', sa.Text, nullable=False),
        sa.CheckConstraint("type IN ('Buy', 'Sell')", name='type'),
        sa.CheckConstraint('quantity > 0 AND price >= 0 AND brokerage_fee >= 0 AND other_fees >= 0', name='amounts'))
    op.create_index('ix_transactions_portfolio_date', 'transactions', ['portfolio_id', 'date_time', 'id'])
    op.create_table('asset_history',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('asset_id', sa.Integer, sa.ForeignKey('assets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('date', sa.Date, nullable=False), sa.Column('close', sa.Float, nullable=False),
        sa.Column('dividends', sa.Float, nullable=False), sa.Column('stock_splits', sa.Float, nullable=False),
        sa.Column('source', sa.String(30), nullable=False),
        sa.UniqueConstraint('asset_id', 'date'), sa.CheckConstraint('close >= 0', name='close'))
    op.create_table('legacy_imports',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('portfolio_id', sa.Integer, sa.ForeignKey('portfolios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('digest', sa.String(64), nullable=False), sa.Column('records', sa.Integer, nullable=False),
        sa.UniqueConstraint('portfolio_id', 'digest'))


def downgrade():
    for table in ['legacy_imports', 'asset_history', 'transactions', 'assets', 'brokers', 'portfolios']:
        op.drop_table(table)
