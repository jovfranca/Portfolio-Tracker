"""Preserve the provider's calendar date independently of TIMESTAMPTZ."""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    # Existing timestamps cannot recover the original exchange timezone.
    # Leave their date unknown; the quote service refreshes these cache entries.
    op.add_column('latest_market_quotes', sa.Column('reference_date', sa.Date(), nullable=True))


def downgrade():
    op.drop_column('latest_market_quotes', 'reference_date')
