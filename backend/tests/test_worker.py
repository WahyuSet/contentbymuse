from datetime import timedelta

from sqlalchemy import select

from app.db.models import GenerationJob, JobEvent, UsageRecord, utcnow
from app.jobs.queue import enqueue
from app.providers.base import ImageRequest, VoiceRequest
from app.providers.registry import ADAPTERS
from app.worker import Worker


def test_registry_has_all_fake_adapters():
    for capability in ("llm", "voice", "image", "video"):
        assert (capability, "fake") in ADAPTERS


async def test_fake_voice_timings_and_image_size():
    voice = ADAPTERS[("voice", "fake")]()
    result = await voice.synthesize(VoiceRequest(text="satu dua tiga", voice_id="fake"), None)
    assert len(result.word_timings) == 3
    assert result.audio

    image = ADAPTERS[("image", "fake")]()
    made = await image.generate_image(ImageRequest(prompt="stickman", extra={"label": "01"}), None)
    assert (made.width, made.height) == (1080, 1920)


async def test_worker_completes_provider_test_job(session):
    job = await enqueue(session, type="provider_test", input={"label": "halo"})
    await session.commit()

    worker = Worker(session_factory=session_factory_of(session))
    assert await worker.run_once() is True

    refreshed = await session.get(GenerationJob, job.id)
    await session.refresh(refreshed)
    assert refreshed.status == "completed"
    assert refreshed.result["llm"]["ok"] is True
    events = (await session.execute(select(JobEvent))).scalars().all()
    assert events
    usage = (await session.execute(select(UsageRecord))).scalars().all()
    assert len(usage) == 1
    assert usage[0].capability == "llm"


async def test_recover_stale_requeues_then_fails(session):
    job = await enqueue(session, type="provider_test", input={})
    job.status = "processing"
    job.attempts = 1
    job.heartbeat_at = utcnow() - timedelta(seconds=120)
    await session.commit()

    worker = Worker(session_factory=session_factory_of(session))
    await worker.recover_stale_once()
    refreshed = await session.get(GenerationJob, job.id)
    await session.refresh(refreshed)
    assert refreshed.status == "queued"

    refreshed.status = "processing"
    refreshed.attempts = 3
    refreshed.heartbeat_at = utcnow() - timedelta(seconds=120)
    await session.commit()
    await worker.recover_stale_once()
    refreshed = await session.get(GenerationJob, job.id)
    await session.refresh(refreshed)
    assert refreshed.status == "failed"
    assert refreshed.error["kind"] == "WorkerInterrupted"


async def test_cancel_during_processing_discards_result(session):
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    job = await enqueue(
        session, type="provider_test", input={"label": "batal", "sleep_ms": 1500}
    )
    await session.commit()
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    worker = Worker(session_factory=factory)
    task = asyncio.create_task(worker.run_once())
    for _ in range(50):
        await asyncio.sleep(0.05)
        async with factory() as other:
            current = await other.get(GenerationJob, job.id)
            if current.status == "processing":
                current.cancel_requested = True
                await other.commit()
                break
    assert await task is True
    refreshed = await session.get(GenerationJob, job.id)
    await session.refresh(refreshed)
    assert refreshed.status == "cancelled"
    assert refreshed.result is None


async def test_handler_failure_requeues_with_backoff_then_fails(session, monkeypatch):
    from app.jobs.handlers import HANDLERS

    async def always_fails(job, factory):
        raise RuntimeError("gangguan sementara")

    monkeypatch.setitem(HANDLERS, "flaky", always_fails)
    job = await enqueue(session, type="flaky", input={})
    await session.commit()
    worker = Worker(session_factory=session_factory_of(session))

    for expected in ("queued", "queued", "failed"):
        assert await worker.run_once() is True
        refreshed = await session.get(GenerationJob, job.id)
        await session.refresh(refreshed)
        assert refreshed.status == expected
        if expected == "queued":
            assert refreshed.error["kind"] == "RuntimeError"
            refreshed.run_after = utcnow() - timedelta(seconds=1)
            await session.commit()


def session_factory_of(session):
    bind = session.bind

    from sqlalchemy.ext.asyncio import async_sessionmaker

    return async_sessionmaker(bind, expire_on_commit=False)
