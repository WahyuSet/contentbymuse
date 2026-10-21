"""Tabel job, job_event, usage_record (Fase 1).

Revision ID: 0001
"""

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generation_job",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("project_id", sa.String(26)),
        sa.Column("scene_id", sa.String(26)),
        sa.Column("parent_id", sa.String(26)),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("resource_key", sa.String(64), nullable=False, server_default="local"),
        sa.Column("input", sa.JSON, nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("result", sa.JSON),
        sa.Column("error", sa.JSON),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_by", sa.String(64)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_requested", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("progress", sa.Integer, nullable=False, server_default="0"),
        sa.Column("progress_message", sa.String(255), nullable=False, server_default=""),
        sa.Column("prompt_version_id", sa.String(26)),
        sa.Column("provider_id", sa.String(26)),
        sa.Column("model", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    # coalesce() supaya baris dengan project/scene NULL tetap terdedup.
    op.execute(
        "CREATE UNIQUE INDEX uq_job_active_dedup ON generation_job "
        "(type, coalesce(project_id, ''), coalesce(scene_id, ''), input_hash) "
        "WHERE status IN ('queued','processing')"
    )
    op.create_table(
        "job_event",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("job_id", sa.String(26), sa.ForeignKey("generation_job.id"), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("level", sa.String(16), nullable=False, server_default="info"),
        sa.Column("message", sa.String(500), nullable=False, server_default=""),
        sa.Column("data", sa.JSON),
    )
    op.create_index("ix_job_event_job_id", "job_event", ["job_id"])
    op.create_table(
        "usage_record",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("job_id", sa.String(26), sa.ForeignKey("generation_job.id")),
        sa.Column("project_id", sa.String(26)),
        sa.Column("provider_id", sa.String(26)),
        sa.Column("model", sa.String(128)),
        sa.Column("capability", sa.String(16), nullable=False),
        sa.Column("input_tokens", sa.Integer),
        sa.Column("output_tokens", sa.Integer),
        sa.Column("characters", sa.Integer),
        sa.Column("images", sa.Integer),
        sa.Column("seconds", sa.Numeric(12, 3)),
        sa.Column("cost_estimate", sa.Numeric(12, 6)),
        sa.Column("currency", sa.String(3)),
        sa.Column("succeeded", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("usage_record")
    op.drop_table("job_event")
    op.drop_index("uq_job_active_dedup", table_name="generation_job")
    op.drop_table("generation_job")
