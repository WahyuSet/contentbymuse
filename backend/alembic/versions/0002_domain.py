"""Domain Fase 2: category, format, provider, prompt, project, content_idea.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "category",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("fact_check", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("prompt_template_id", sa.String(26)),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="1"),
        *_timestamps(),
    )
    op.create_index("ix_category_slug", "category", ["slug"])
    op.create_table(
        "format",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("prompt_template_id", sa.String(26)),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="1"),
        *_timestamps(),
    )
    op.create_index("ix_format_slug", "format", ["slug"])
    op.create_table(
        "provider",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("capability", sa.String(16), nullable=False),
        sa.Column("adapter", sa.String(64), nullable=False),
        sa.Column("base_url", sa.String(255)),
        sa.Column("api_key_encrypted", sa.LargeBinary),
        sa.Column("api_key_hint", sa.String(4)),
        sa.Column("default_model", sa.String(128)),
        sa.Column("quirks", sa.JSON, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
        *_timestamps(),
    )
    op.create_table(
        "prompt_template",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("key", sa.String(128), nullable=False, unique=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("active_version_id", sa.String(26)),
        *_timestamps(),
    )
    op.create_index("ix_prompt_template_key", "prompt_template", ["key"])
    op.create_table(
        "prompt_version",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column(
            "template_id", sa.String(26), sa.ForeignKey("prompt_template.id"), nullable=False
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="builtin"),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("frontmatter", sa.JSON, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("template_id", "version"),
        sa.UniqueConstraint("template_id", "content_hash"),
    )
    op.create_index("ix_prompt_version_template_id", "prompt_version", ["template_id"])
    op.create_index("ix_prompt_version_content_hash", "prompt_version", ["content_hash"])
    op.create_table(
        "project",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("topic", sa.String(500)),
        sa.Column("category_id", sa.String(26), sa.ForeignKey("category.id")),
        sa.Column("category_source", sa.String(16)),
        sa.Column("format_id", sa.String(26), sa.ForeignKey("format.id")),
        sa.Column("language", sa.String(8), nullable=False, server_default="id-ID"),
        sa.Column("target_min_s", sa.Integer, nullable=False, server_default="30"),
        sa.Column("target_max_s", sa.Integer, nullable=False, server_default="40"),
        sa.Column("selected_idea_id", sa.String(26)),
        sa.Column("settings", sa.JSON, nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "topic IS NOT NULL OR category_id IS NOT NULL",
            name="ck_project_topic_or_category",
        ),
    )
    op.create_table(
        "content_idea",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("project_id", sa.String(26), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("batch", sa.Integer, nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("angle", sa.Text, nullable=False, server_default=""),
        sa.Column("hook", sa.Text, nullable=False, server_default=""),
        sa.Column("why_it_works", sa.Text, nullable=False, server_default=""),
        sa.Column("suggested_category_slug", sa.String(64)),
        sa.Column("fact_risk", sa.String(8)),
        sa.Column("fact_note", sa.Text),
        sa.Column("job_id", sa.String(26), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "batch", "position"),
    )
    op.create_index("ix_content_idea_project_id", "content_idea", ["project_id"])
    op.create_index("ix_content_idea_job_id", "content_idea", ["job_id"])


def downgrade() -> None:
    op.drop_table("content_idea")
    op.drop_table("project")
    op.drop_table("prompt_version")
    op.drop_table("prompt_template")
    op.drop_table("provider")
    op.drop_table("format")
    op.drop_table("category")
