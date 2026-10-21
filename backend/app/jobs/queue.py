import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GenerationJob, utcnow


def sha256_of_json(obj: Any) -> str:
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def enqueue(
    session: AsyncSession,
    *,
    type: str,
    input: dict,
    project_id: str | None = None,
    scene_id: str | None = None,
    parent_id: str | None = None,
    resource_key: str = "local",
    priority: int = 100,
    max_attempts: int = 3,
) -> GenerationJob:
    job = GenerationJob(
        type=type,
        project_id=project_id,
        scene_id=scene_id,
        parent_id=parent_id,
        resource_key=resource_key,
        input=input,
        input_hash=sha256_of_json(input),
        priority=priority,
        max_attempts=max_attempts,
    )
    session.add(job)
    await session.flush()
    return job


async def claim_next(
    session: AsyncSession,
    *,
    worker_id: str,
    full_keys: frozenset[str] = frozenset(),
) -> GenerationJob | None:
    """Ambil satu job antre. SQLite berjalan satu worker (Spec §7.1), jadi klaim
    dijaga oleh UPDATE bersyarat status='queued', bukan lock baris."""
    now = utcnow()
    stmt = (
        select(GenerationJob.id)
        .where(
            GenerationJob.status == "queued",
            GenerationJob.run_after <= now,
            GenerationJob.resource_key.not_in(full_keys) if full_keys else True,
        )
        .order_by(GenerationJob.priority, GenerationJob.created_at)
        .limit(1)
    )
    job_id = (await session.execute(stmt)).scalar_one_or_none()
    if job_id is None:
        return None
    result = await session.execute(
        update(GenerationJob)
        .where(GenerationJob.id == job_id, GenerationJob.status == "queued")
        .values(
            status="processing",
            locked_by=worker_id,
            heartbeat_at=now,
            started_at=now,
            attempts=GenerationJob.attempts + 1,
        )
    )
    if result.rowcount != 1:
        await session.rollback()
        return None
    await session.commit()
    return await session.get(GenerationJob, job_id)


async def mark_completed(session: AsyncSession, job: GenerationJob, result: dict) -> None:
    job.status = "completed"
    job.result = result
    job.progress = 100
    job.finished_at = utcnow()
    await session.commit()


async def mark_failed(session: AsyncSession, job: GenerationJob, error: dict) -> None:
    job.status = "failed"
    job.error = error
    job.finished_at = utcnow()
    await session.commit()
