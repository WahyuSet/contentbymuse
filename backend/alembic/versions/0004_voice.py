"""Kolom suara project, tabel asset dan voice_calibration (Fase 4)

Revision ID: 0004
Revises: 0003
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("project", sa.Column("voice_provider_id", sa.String(length=26)))
    op.add_column("project", sa.Column("voice_id", sa.String(length=128)))
    op.add_column(
        "project",
        sa.Column("voice_settings", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_table(
        "asset",
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("project_id", sa.String(length=26)),
        sa.Column("scene_id", sa.String(length=26)),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("mime", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("duration_s", sa.Float()),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("data", sa.JSON()),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("provider_id", sa.String(length=26)),
        sa.Column("model", sa.String(length=128)),
        sa.Column("params", sa.JSON()),
        sa.Column("is_selected", sa.Boolean(), nullable=False),
        sa.Column("job_id", sa.String(length=26)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "scene_id", "kind", "version"),
    )
    op.create_index("ix_asset_project_id", "asset", ["project_id"])
    op.create_index("ix_asset_scene_id", "asset", ["scene_id"])
    op.create_index("ix_asset_input_hash", "asset", ["input_hash"])
    op.create_index(
        "uq_asset_selected",
        "asset",
        ["project_id", sa.text("coalesce(scene_id, '')"), "kind"],
        unique=True,
        sqlite_where=sa.text("is_selected = 1"),
    )
    op.create_table(
        "voice_calibration",
        sa.Column("provider_id", sa.String(length=26), nullable=False),
        sa.Column("voice_id", sa.String(length=128), nullable=False),
        sa.Column("words_per_second", sa.Float(), nullable=False),
        sa.Column("samples", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("provider_id", "voice_id"),
    )


def downgrade() -> None:
    op.drop_table("voice_calibration")
    op.drop_table("asset")
    op.drop_column("project", "voice_settings")
    op.drop_column("project", "voice_id")
    op.drop_column("project", "voice_provider_id")
