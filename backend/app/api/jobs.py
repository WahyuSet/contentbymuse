from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.errors import AppError, NotFoundError
from app.db.models import GenerationJob, JobEvent, utcnow
from app.jobs import queue

SUPPORTED_JOB_TYPES = {"provider_test"}

router = APIRouter(prefix="/api", tags=["jobs"])


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    project_id: str | None
    scene_id: str | None
    parent_id: str | None
    status: str
    resource_key: str
    input: dict[str, Any]
    input_hash: str
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    attempts: int
    max_attempts: int
    priority: int
    run_after: datetime
    locked_by: str | None
    heartbeat_at: datetime | None
    cancel_requested: bool
    progress: int
    progress_message: str
    provider_id: str | None
    model: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: str
    ts: datetime
    level: str
    message: str
    data: dict[str, Any] | None


class EnqueueJobIn(BaseModel):
    type: str
    input: dict[str, Any] = {}


def get_factory(request: Request) -> async_sessionmaker:
    return request.app.state.session_factory


async def get_session(factory: async_sessionmaker = Depends(get_factory)):
    async with factory() as session:
        yield session


@router.post("/jobs", status_code=202, response_model=JobOut)
async def enqueue_job(body: EnqueueJobIn, session: AsyncSession = Depends(get_session)):
    if body.type not in SUPPORTED_JOB_TYPES:
        raise AppError(
            422,
            "UnsupportedJobType",
            f"Tipe job '{body.type}' belum didukung di Fase 1. "
            f"Yang didukung: {', '.join(sorted(SUPPORTED_JOB_TYPES))}.",
        )
    try:
        job = await queue.enqueue(session, type=body.type, input=body.input)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise AppError(
            409,
            "DuplicateActiveJob",
            "Job aktif dengan input yang sama sudah ada.",
        ) from None
    return job


@router.get("/jobs", response_model=list[JobOut])
async def list_jobs(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(50, ge=1, le=200),
):
    stmt = select(GenerationJob).order_by(GenerationJob.created_at.desc()).limit(limit)
    return (await session.execute(stmt)).scalars().all()


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)):
    job = await session.get(GenerationJob, job_id)
    if job is None:
        raise NotFoundError("Job tidak ditemukan.")
    return job


@router.get("/jobs/{job_id}/events", response_model=list[JobEventOut])
async def get_job_events(job_id: str, session: AsyncSession = Depends(get_session)):
    if await session.get(GenerationJob, job_id) is None:
        raise NotFoundError("Job tidak ditemukan.")
    stmt = (
        select(JobEvent).where(JobEvent.job_id == job_id).order_by(JobEvent.ts, JobEvent.id)
    )
    return (await session.execute(stmt)).scalars().all()


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
async def cancel_job(job_id: str, session: AsyncSession = Depends(get_session)):
    job = await session.get(GenerationJob, job_id)
    if job is None:
        raise NotFoundError("Job tidak ditemukan.")
    if job.status == "queued":
        job.status = "cancelled"
        job.finished_at = utcnow()
    elif job.status == "processing":
        job.cancel_requested = True
    else:
        raise AppError(409, "JobNotCancellable", f"Job berstatus {job.status} tidak bisa dibatalkan.")
    await session.commit()
    await session.refresh(job)
    return job
