from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.ids import new_ulid


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class GenerationJob(Base):
    __tablename__ = "generation_job"
    # coalesce: NULL project/scene (job tingkat project) tetap ikut dedup;
    # unique index biasa memperlakukan NULL sebagai selalu berbeda.
    __table_args__ = (
        Index(
            "uq_job_active_dedup",
            "type",
            text("coalesce(project_id, '')"),
            text("coalesce(scene_id, '')"),
            "input_hash",
            unique=True,
            sqlite_where=text("status IN ('queued','processing')"),
            postgresql_where=text("status IN ('queued','processing')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    type: Mapped[str] = mapped_column(String(32))
    project_id: Mapped[str | None] = mapped_column(String(26))
    scene_id: Mapped[str | None] = mapped_column(String(26))
    parent_id: Mapped[str | None] = mapped_column(String(26))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    resource_key: Mapped[str] = mapped_column(String(64), default="local")
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    input_hash: Mapped[str] = mapped_column(String(64), default="")
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[dict | None] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    locked_by: Mapped[str | None] = mapped_column(String(64))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    progress_message: Mapped[str] = mapped_column(String(255), default="")
    prompt_version_id: Mapped[str | None] = mapped_column(String(26))
    provider_id: Mapped[str | None] = mapped_column(String(26))
    model: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobEvent(Base):
    __tablename__ = "job_event"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    job_id: Mapped[str] = mapped_column(ForeignKey("generation_job.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    level: Mapped[str] = mapped_column(String(16), default="info")
    message: Mapped[str] = mapped_column(String(500), default="")
    data: Mapped[dict | None] = mapped_column(JSON)


class UsageRecord(Base):
    __tablename__ = "usage_record"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("generation_job.id"))
    project_id: Mapped[str | None] = mapped_column(String(26))
    provider_id: Mapped[str | None] = mapped_column(String(26))
    model: Mapped[str | None] = mapped_column(String(128))
    capability: Mapped[str] = mapped_column(String(16))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    characters: Mapped[int | None] = mapped_column(Integer)
    images: Mapped[int | None] = mapped_column(Integer)
    seconds: Mapped[float | None] = mapped_column(Numeric(12, 3))
    # Selalu null: biaya dihitung saat dibaca dari harga provider (Spec §2.3).
    cost_estimate: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    currency: Mapped[str | None] = mapped_column(String(3))
    succeeded: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Category(Base):
    __tablename__ = "category"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(500), default="")
    fact_check: Mapped[str] = mapped_column(String(16), default="normal")
    prompt_template_id: Mapped[str | None] = mapped_column(String(26))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Format(Base):
    __tablename__ = "format"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(500), default="")
    prompt_template_id: Mapped[str | None] = mapped_column(String(26))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Provider(Base):
    __tablename__ = "provider"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    name: Mapped[str] = mapped_column(String(128))
    capability: Mapped[str] = mapped_column(String(16))
    adapter: Mapped[str] = mapped_column(String(64))
    base_url: Mapped[str | None] = mapped_column(String(255))
    api_key_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    # 4 karakter terakhir kunci, untuk ditampilkan sebagai petunjuk (Spec §9).
    api_key_hint: Mapped[str | None] = mapped_column(String(4))
    default_model: Mapped[str | None] = mapped_column(String(128))
    quirks: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PromptTemplate(Base):
    __tablename__ = "prompt_template"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(16))
    active_version_id: Mapped[str | None] = mapped_column(String(26))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PromptVersion(Base):
    __tablename__ = "prompt_version"
    __table_args__ = (
        UniqueConstraint("template_id", "version"),
        UniqueConstraint("template_id", "content_hash"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    template_id: Mapped[str] = mapped_column(
        ForeignKey("prompt_template.id"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(16), default="builtin")
    content: Mapped[str] = mapped_column(Text)
    frontmatter: Mapped[dict] = mapped_column(JSON, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Project(Base):
    __tablename__ = "project"
    __table_args__ = (
        CheckConstraint(
            "topic IS NOT NULL OR category_id IS NOT NULL",
            name="ck_project_topic_or_category",
        ),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    title: Mapped[str] = mapped_column(String(255))
    topic: Mapped[str | None] = mapped_column(String(500))
    category_id: Mapped[str | None] = mapped_column(ForeignKey("category.id"))
    category_source: Mapped[str | None] = mapped_column(String(16))
    format_id: Mapped[str | None] = mapped_column(ForeignKey("format.id"))
    language: Mapped[str] = mapped_column(String(8), default="id-ID")
    target_min_s: Mapped[int] = mapped_column(Integer, default=30)
    target_max_s: Mapped[int] = mapped_column(Integer, default=40)
    selected_idea_id: Mapped[str | None] = mapped_column(String(26))
    active_script_id: Mapped[str | None] = mapped_column(String(26))
    voice_provider_id: Mapped[str | None] = mapped_column(String(26))
    voice_id: Mapped[str | None] = mapped_column(String(128))
    voice_settings: Mapped[dict] = mapped_column(JSON, default=dict)
    image_provider_id: Mapped[str | None] = mapped_column(String(26))
    visual_style_id: Mapped[str | None] = mapped_column(String(26))
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ContentIdea(Base):
    __tablename__ = "content_idea"
    __table_args__ = (UniqueConstraint("project_id", "batch", "position"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    batch: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(255))
    angle: Mapped[str] = mapped_column(Text, default="")
    hook: Mapped[str] = mapped_column(Text, default="")
    why_it_works: Mapped[str] = mapped_column(Text, default="")
    suggested_category_slug: Mapped[str | None] = mapped_column(String(64))
    fact_risk: Mapped[str | None] = mapped_column(String(8))
    fact_note: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[str] = mapped_column(String(26), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Script(Base):
    __tablename__ = "script"
    __table_args__ = (UniqueConstraint("project_id", "version"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    idea_id: Mapped[str | None] = mapped_column(String(26))
    version: Mapped[int] = mapped_column(Integer)
    parent_id: Mapped[str | None] = mapped_column(String(26))
    source: Mapped[str] = mapped_column(String(16), default="generated")
    schema_version: Mapped[str] = mapped_column(String(16), default="script.v1")
    title: Mapped[str] = mapped_column(String(255))
    hook: Mapped[str] = mapped_column(Text, default="")
    estimated_duration_s: Mapped[float] = mapped_column(default=0.0)
    claims_to_verify: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    edited_after_validation: Mapped[bool] = mapped_column(Boolean, default=False)
    best_score: Mapped[int | None] = mapped_column(Integer)
    prompt_version_id: Mapped[str | None] = mapped_column(String(26))
    job_id: Mapped[str | None] = mapped_column(String(26), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Scene(Base):
    __tablename__ = "scene"
    __table_args__ = (UniqueConstraint("script_id", "position"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    script_id: Mapped[str] = mapped_column(ForeignKey("script.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    beat: Mapped[str] = mapped_column(String(16), default="main")
    voiceover: Mapped[str] = mapped_column(Text, default="")
    subtitle_override: Mapped[str | None] = mapped_column(Text)
    visual_prompt: Mapped[str] = mapped_column(Text, default="")
    include_mascot: Mapped[bool] = mapped_column(Boolean, default=True)
    visual_type: Mapped[str] = mapped_column(String(16), default="character")
    transition: Mapped[str] = mapped_column(String(16), default="cut")
    emphasis_words: Mapped[list] = mapped_column(JSON, default=list)
    sfx_cues: Mapped[list] = mapped_column(JSON, default=list)
    est_duration_s: Mapped[float] = mapped_column(default=0.0)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ValidationResult(Base):
    __tablename__ = "validation_result"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    script_id: Mapped[str] = mapped_column(ForeignKey("script.id"), index=True)
    attempt: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    score: Mapped[int] = mapped_column(Integer, default=0)
    issues: Mapped[list] = mapped_column(JSON, default=list)
    claims_to_verify: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    prompt_version_id: Mapped[str | None] = mapped_column(String(26))
    job_id: Mapped[str | None] = mapped_column(String(26), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppSetting(Base):
    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[object] = mapped_column(JSON)


class Asset(Base):
    __tablename__ = "asset"
    __table_args__ = (
        UniqueConstraint("project_id", "scene_id", "kind", "version"),
        Index(
            "uq_asset_selected",
            "project_id",
            text("coalesce(scene_id, '')"),
            "kind",
            unique=True,
            sqlite_where=text("is_selected = 1"),
            postgresql_where=text("is_selected"),
        ),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    project_id: Mapped[str | None] = mapped_column(String(26), index=True)
    scene_id: Mapped[str | None] = mapped_column(String(26), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    version: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(512))
    mime: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    duration_s: Mapped[float | None] = mapped_column()
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    data: Mapped[dict | None] = mapped_column(JSON)
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    provider_id: Mapped[str | None] = mapped_column(String(26))
    model: Mapped[str | None] = mapped_column(String(128))
    params: Mapped[dict | None] = mapped_column(JSON)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    job_id: Mapped[str | None] = mapped_column(String(26))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VoiceCalibration(Base):
    __tablename__ = "voice_calibration"

    provider_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    voice_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    words_per_second: Mapped[float] = mapped_column(default=0.0)
    samples: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class VisualStyle(Base):
    __tablename__ = "visual_style"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer, default=1)
    style_text: Mapped[str] = mapped_column(Text, default="")
    negative_text: Mapped[str] = mapped_column(Text, default="")
    mascot_anchor: Mapped[str] = mapped_column(Text, default="")
    reference_asset_id: Mapped[str | None] = mapped_column(String(26))
    image_params: Mapped[dict] = mapped_column(JSON, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
