"""rekor publish per platform (Fase 8)

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "publish_record",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("project_id", sa.String(26), nullable=False),
        sa.Column("render_id", sa.String(26), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("external_id", sa.String(128)),
        sa.Column("url", sa.String(512)),
        sa.Column("error", sa.Text()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "project_id", "render_id", "platform", name="uq_publish_per_render"
        ),
    )
    op.create_index("ix_publish_record_project_id", "publish_record", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_publish_record_project_id", table_name="publish_record")
    op.drop_table("publish_record")
