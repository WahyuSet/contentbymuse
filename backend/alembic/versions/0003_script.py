"""Tabel script, scene, validation_result, app_setting + project.active_script_id (Fase 3)

Revision ID: 0003
Revises: 0002
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("project", sa.Column("active_script_id", sa.String(length=26)))
    op.create_table(
        "script",
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("project_id", sa.String(length=26), nullable=False),
        sa.Column("idea_id", sa.String(length=26)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.String(length=26)),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("hook", sa.Text(), nullable=False),
        sa.Column("estimated_duration_s", sa.Float(), nullable=False),
        sa.Column("claims_to_verify", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("edited_after_validation", sa.Boolean(), nullable=False),
        sa.Column("best_score", sa.Integer()),
        sa.Column("prompt_version_id", sa.String(length=26)),
        sa.Column("job_id", sa.String(length=26)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "version"),
    )
    op.create_index("ix_script_project_id", "script", ["project_id"])
    op.create_index("ix_script_job_id", "script", ["job_id"])
    op.create_table(
        "scene",
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("script_id", sa.String(length=26), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("beat", sa.String(length=16), nullable=False),
        sa.Column("voiceover", sa.Text(), nullable=False),
        sa.Column("subtitle_override", sa.Text()),
        sa.Column("visual_prompt", sa.Text(), nullable=False),
        sa.Column("include_mascot", sa.Boolean(), nullable=False),
        sa.Column("visual_type", sa.String(length=16), nullable=False),
        sa.Column("transition", sa.String(length=16), nullable=False),
        sa.Column("emphasis_words", sa.JSON(), nullable=False),
        sa.Column("est_duration_s", sa.Float(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["script_id"], ["script.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("script_id", "position"),
    )
    op.create_index("ix_scene_script_id", "scene", ["script_id"])
    op.create_table(
        "validation_result",
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("script_id", sa.String(length=26), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("claims_to_verify", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("prompt_version_id", sa.String(length=26)),
        sa.Column("job_id", sa.String(length=26)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["script_id"], ["script.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_validation_result_script_id", "validation_result", ["script_id"])
    op.create_index("ix_validation_result_job_id", "validation_result", ["job_id"])
    op.create_table(
        "app_setting",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("app_setting")
    op.drop_table("validation_result")
    op.drop_table("scene")
    op.drop_table("script")
    op.drop_column("project", "active_script_id")
