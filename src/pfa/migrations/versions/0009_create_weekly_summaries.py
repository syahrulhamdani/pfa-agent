"""create weekly summaries

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-11 09:40:27.118203

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "weekly_summaries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column(
            "stats_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("recommendations_text", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("week_start"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("weekly_summaries")
