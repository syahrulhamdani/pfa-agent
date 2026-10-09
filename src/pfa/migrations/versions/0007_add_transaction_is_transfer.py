"""add transaction is_transfer

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-09 10:12:40.118342

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "transactions",
        sa.Column(
            "is_transfer", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    # Until now a move between the user's own accounts was recognised by its category.
    # Flag those rows so nothing changes in what is counted; the category stays.
    op.execute(
        "UPDATE transactions SET is_transfer = true WHERE category_id IN "
        "(SELECT id FROM categories WHERE lower(name) = 'transfer')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("transactions", "is_transfer")
