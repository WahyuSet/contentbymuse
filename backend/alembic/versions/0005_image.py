"""visual_style dan pin gambar project (Fase 5)

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "visual_style",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("style_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("negative_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("mascot_anchor", sa.Text(), nullable=False, server_default=""),
        sa.Column("reference_asset_id", sa.String(26)),
        sa.Column("image_params", sa.JSON(), server_default="{}"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.add_column("project", sa.Column("image_provider_id", sa.String(26)))
    op.add_column("project", sa.Column("visual_style_id", sa.String(26)))


def downgrade() -> None:
    op.drop_column("project", "visual_style_id")
    op.drop_column("project", "image_provider_id")
    op.drop_table("visual_style")
