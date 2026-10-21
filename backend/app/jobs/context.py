import time

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import GenerationJob, JobEvent, utcnow


class JobCancelled(Exception):
    """Dinaikkan handler saat permintaan batal terlihat lewat ctx.cancelled()."""


class DbCallContext:
    """CallContext yang menulis progres dan log job ke DB (Spec §7.6)."""

    def __init__(self, job_id: str, factory: async_sessionmaker):
        self.job_id = job_id
        self._factory = factory
        self._last_progress_write = 0.0

    async def progress(self, percent: int, message: str) -> None:
        now = time.monotonic()
        if percent < 100 and now - self._last_progress_write < 1.0:
            return
        self._last_progress_write = now
        async with self._factory() as session:
            job = await session.get(GenerationJob, self.job_id)
            if job is None:
                return
            job.progress = percent
            job.progress_message = message
            job.heartbeat_at = utcnow()
            await session.commit()

    async def log(self, level: str, message: str, data: dict | None = None) -> None:
        async with self._factory() as session:
            session.add(JobEvent(job_id=self.job_id, level=level, message=message, data=data))
            await session.commit()

    async def cancelled(self) -> bool:
        async with self._factory() as session:
            job = await session.get(GenerationJob, self.job_id)
            return bool(job and job.cancel_requested)
