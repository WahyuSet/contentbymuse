import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.db.models import GenerationJob, utcnow
from app.db.session import create_engine, session_factory
from app.jobs import queue
from app.jobs.context import JobCancelled
from app.jobs.handlers import HANDLERS
from app.services.reconcile import reconcile

logger = logging.getLogger(__name__)

STALE_AFTER_S = 60


def _as_utc(value: datetime) -> datetime:
    # SQLite mengembalikan datetime naive; semua waktu di sistem ini UTC.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class Worker:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker,
        worker_id: str | None = None,
        concurrency: int = 6,
        poll_interval_s: float = 1.0,
    ):
        self._factory = session_factory
        self._worker_id = worker_id or f"worker-{os.getpid()}"
        self._concurrency = concurrency
        self._poll_interval_s = poll_interval_s
        self._stopping = asyncio.Event()
        self._running: set[asyncio.Task] = set()

    async def run_once(self) -> bool:
        async with self._factory() as session:
            job = await queue.claim_next(session, worker_id=self._worker_id)
        if job is None:
            return False
        await self._execute(job.id)
        return True

    async def _execute(self, job_id: str) -> None:
        async with self._factory() as session:
            job = await session.get(GenerationJob, job_id)
            if job is None:
                return
            handler = HANDLERS.get(job.type)
            try:
                if handler is None:
                    raise LookupError(f"Tidak ada handler untuk tipe job {job.type}")
                result = await handler(job, self._factory)
            except JobCancelled:
                await queue.mark_cancelled(session, job)
            except Exception as exc:  # worker tetap hidup apa pun kegagalan handler
                error = {
                    "kind": type(exc).__name__,
                    "message": str(exc),
                    "retryable": bool(getattr(exc, "retryable", True)),
                }
                if error["retryable"] and job.attempts < job.max_attempts:
                    # Backoff Spec §7.3: 5 dtk sebelum percobaan ke-2, 20 dtk ke-3.
                    delay = 5 if job.attempts <= 1 else 20
                    await queue.requeue_after_failure(session, job, error, delay)
                    logger.warning("Job %s gagal, diantrekan ulang: %s", job_id, exc)
                else:
                    error["retryable"] = False
                    await queue.mark_failed(session, job, error)
                    logger.exception("Job %s gagal permanen", job_id)
            else:
                await session.refresh(job)
                if job.cancel_requested:
                    await queue.mark_cancelled(session, job)
                else:
                    await queue.mark_completed(session, job, result)
            project_id = job.project_id
        await reconcile(project_id)

    async def recover_stale_once(self) -> None:
        cutoff = utcnow() - timedelta(seconds=STALE_AFTER_S)
        async with self._factory() as session:
            rows = (
                await session.execute(
                    select(GenerationJob).where(GenerationJob.status == "processing")
                )
            ).scalars()
            for job in rows:
                if job.heartbeat_at is None or _as_utc(job.heartbeat_at) >= cutoff:
                    continue
                if job.attempts < job.max_attempts:
                    job.status = "queued"
                    job.locked_by = None
                    job.heartbeat_at = None
                else:
                    job.status = "failed"
                    job.error = {
                        "kind": "WorkerInterrupted",
                        "message": "Job terputus dan percobaan sudah habis. Cek manual sebelum mengulang.",
                        "retryable": False,
                    }
                    job.finished_at = utcnow()
            await session.commit()

    async def _heartbeat_ticker(self) -> None:
        while not self._stopping.is_set():
            async with self._factory() as session:
                rows = (
                    await session.execute(
                        select(GenerationJob).where(
                            GenerationJob.status == "processing",
                            GenerationJob.locked_by == self._worker_id,
                        )
                    )
                ).scalars()
                for job in rows:
                    job.heartbeat_at = utcnow()
                await session.commit()
            await asyncio.sleep(10)

    async def _recover_ticker(self) -> None:
        while not self._stopping.is_set():
            await self.recover_stale_once()
            await asyncio.sleep(30)

    async def run(self) -> None:
        await self.recover_stale_once()
        tickers = [
            asyncio.create_task(self._heartbeat_ticker()),
            asyncio.create_task(self._recover_ticker()),
        ]
        try:
            while not self._stopping.is_set():
                self._running = {t for t in self._running if not t.done()}
                claimed = False
                while len(self._running) < self._concurrency:
                    async with self._factory() as session:
                        job = await queue.claim_next(session, worker_id=self._worker_id)
                    if job is None:
                        break
                    claimed = True
                    self._running.add(asyncio.create_task(self._execute(job.id)))
                if not claimed:
                    await asyncio.sleep(self._poll_interval_s)
                else:
                    await asyncio.sleep(0.05)
        finally:
            for task in tickers:
                task.cancel()

    def stop(self) -> None:
        self._stopping.set()


async def _main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    engine = create_engine(settings)
    worker = Worker(
        session_factory=session_factory(engine),
        concurrency=settings.worker_concurrency,
    )
    logger.info("Worker mulai: %s", worker._worker_id)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(_main())
