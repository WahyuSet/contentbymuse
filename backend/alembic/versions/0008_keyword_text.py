"""teks kata kunci visual per scene (Fase 9)

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scene",
        sa.Column("keyword_text", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scene", "keyword_text")
