from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
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
