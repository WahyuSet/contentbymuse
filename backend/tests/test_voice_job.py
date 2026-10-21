import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.models import (
    Asset,
    Base,
    ContentIdea,
    GenerationJob,
    Project,
    Provider,
    Scene,
    Script,
    VoiceCalibration,
)
from app.jobs import queue


@pytest.fixture
def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/voice.db")
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    cfg = Settings(app_secret_key="rahasia-tes", storage_path=tmp_path / "storage")
    monkeypatch.setattr("app.jobs.voice.get_settings", lambda: cfg)
    monkeypatch.setattr("app.jobs.align.get_settings", lambda: cfg)
    return cfg


async def _seed(factory):
    async with factory() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)
        await session.commit()
    async with factory() as session:
        provider = Provider(
            name="Suara Fake", capability="voice", adapter="fake",
            quirks={"default_voice": "fake-1"}, enabled=True, priority=100,
        )
        session.add(provider)
        project = Project(title="Cicak", topic="cicak")
        session.add(project)
        await session.flush()
        idea = ContentIdea(
            project_id=project.id, batch=1, position=1, title="Judul ide", job_id="01JI"
        )
        session.add(idea)
        await session.flush()
        script = Script(
            project_id=project.id, idea_id=idea.id, version=1, title="Naskah",
            hook="Hook", status="approved", job_id="01JS",
        )
        session.add(script)
        await session.flush()
        scene_ids = []
        for pos in range(1, 4):
            scene = Scene(
                script_id=script.id, position=pos,
                beat="hook" if pos == 1 else "main",
                voiceover=f"Narasi scene nomor {pos} yang cukup panjang",
                visual_prompt=f"Visual {pos}", visual_type="character",
                est_duration_s=3.6,
            )
            session.add(scene)
            await session.flush()
            scene_ids.append(scene.id)
        project.selected_idea_id = idea.id
        project.active_script_id = script.id
        await session.commit()
        return project.id, script.id, scene_ids


async def _voice_job(factory, project_id, scene_id, force=False):
    async with factory() as session:
        job = await queue.enqueue(
            session, type="voice",
            input={"scene_id": scene_id, "force": force},
            project_id=project_id, scene_id=scene_id,
        )
        await session.commit()
        return await session.get(GenerationJob, job.id)


async def _finish(factory, job):
    # Tiru worker: job yang sudah dijalankan handler ditandai selesai agar
    # indeks dedup aktif tidak menolak job berikutnya yang identik.
    async with factory() as session:
        row = await session.get(GenerationJob, job.id)
        row.status = "completed"
        await session.commit()


async def test_voice_job_creates_clip_timings_and_calibration(factory, settings):
    from app.jobs.voice import run_voice

    project_id, _script_id, scene_ids = await _seed(factory)
    job = await _voice_job(factory, project_id, scene_ids[0])
    result = await run_voice(job, factory)
    assert result["cached"] is False

    async with factory() as session:
        assets = (await session.execute(select(Asset))).scalars().all()
        kinds = sorted(a.kind for a in assets)
        assert kinds == ["voice_clip", "word_timings"]
        clip = next(a for a in assets if a.kind == "voice_clip")
        timings = next(a for a in assets if a.kind == "word_timings")
        assert clip.is_selected and timings.is_selected
        assert clip.duration_s > 0
        assert timings.data["method"] == "provider"
        assert timings.data["clip_asset_id"] == clip.id
        assert len(timings.data["words"]) == 7
        calibration = await session.get(VoiceCalibration, (clip.provider_id, "fake-1"))
        assert calibration.samples == 1
        assert calibration.words_per_second == pytest.approx(2.5, abs=0.4)


async def test_voice_job_cache_hit_skips_provider(factory, settings, monkeypatch):
    import app.providers.voice.fake as fake_module
    from app.jobs.voice import run_voice

    calls = {"count": 0}
    original = fake_module.FakeVoice.synthesize

    async def _counting(self, req, ctx=None):
        calls["count"] += 1
        return await original(self, req, ctx)

    monkeypatch.setattr(fake_module.FakeVoice, "synthesize", _counting)
    project_id, _script_id, scene_ids = await _seed(factory)
    first = await _voice_job(factory, project_id, scene_ids[0])
    await run_voice(first, factory)
    await _finish(factory, first)
    result = await run_voice(await _voice_job(factory, project_id, scene_ids[0]), factory)
    assert result["cached"] is True
    assert calls["count"] == 1
    async with factory() as session:
        clips = (
            await session.execute(select(Asset).where(Asset.kind == "voice_clip"))
        ).scalars().all()
        assert len(clips) == 1


async def test_voice_job_force_creates_new_version(factory, settings):
    from app.jobs.voice import run_voice

    project_id, _script_id, scene_ids = await _seed(factory)
    first = await _voice_job(factory, project_id, scene_ids[0])
    await run_voice(first, factory)
    await _finish(factory, first)
    await run_voice(
        await _voice_job(factory, project_id, scene_ids[0], force=True), factory
    )
    async with factory() as session:
        clips = (
            await session.execute(
                select(Asset).where(Asset.kind == "voice_clip")
                .order_by(Asset.version)
            )
        ).scalars().all()
        assert [c.version for c in clips] == [1, 2]
        assert clips[1].is_selected and not clips[0].is_selected


async def test_voice_without_timestamps_enqueues_align(factory, settings, monkeypatch):
    import app.jobs.voice as voice_module
    from app.providers.base import Usage, VoiceResult

    class SilentVoice:
        caps = type("Caps", (), {"returns_timestamps": False, "supports_context": False})()

        async def synthesize(self, req, ctx=None):
            return VoiceResult(
                audio=_tiny_wav(), mime="audio/wav", word_timings=None,
                usage=Usage(characters=len(req.text)),
            )

    project_id, _script_id, scene_ids = await _seed(factory)
    async with factory() as session:
        project = await session.get(Project, project_id)
        project.voice_provider_id = None
        await session.commit()

    async def _candidates(session, project):
        async with factory() as s:
            provider = (
                await s.execute(select(Provider).where(Provider.capability == "voice"))
            ).scalars().first()
        return [(provider, "fake-1", SilentVoice())]

    monkeypatch.setattr(voice_module, "voice_candidates", _candidates)
    job = await _voice_job(factory, project_id, scene_ids[1])
    await voice_module.run_voice(job, factory)
    async with factory() as session:
        align_jobs = (
            await session.execute(
                select(GenerationJob).where(GenerationJob.type == "align")
            )
        ).scalars().all()
        assert len(align_jobs) == 1
        assert align_jobs[0].scene_id == scene_ids[1]


def _tiny_wav() -> bytes:
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * 8000)
    return buffer.getvalue()


async def test_align_job_writes_proportional_timings(factory, settings, monkeypatch):
    import app.jobs.align as align_module
    from app.jobs.voice import run_voice
    from app.services.aligner import ProportionalAligner

    project_id, _script_id, scene_ids = await _seed(factory)
    first = await _voice_job(factory, project_id, scene_ids[0])
    await run_voice(first, factory)
    await _finish(factory, first)
    async with factory() as session:
        clip = (
            await session.execute(select(Asset).where(Asset.kind == "voice_clip"))
        ).scalars().one()
        # Hapus timing provider agar align bekerja dari nol.
        timings = (
            await session.execute(select(Asset).where(Asset.kind == "word_timings"))
        ).scalars().all()
        for row in timings:
            await session.delete(row)
        await session.commit()
        job = await queue.enqueue(
            session, type="align",
            input={"scene_id": scene_ids[0], "clip_asset_id": clip.id},
            project_id=project_id, scene_id=scene_ids[0],
        )
        await session.commit()
        job_id = job.id

    async def _fake_align(path, text, *, bounds, ctx=None):
        return ProportionalAligner().align(path, text, bounds=bounds)

    monkeypatch.setattr(align_module, "align_words", _fake_align)
    async with factory() as session:
        job = await session.get(GenerationJob, job_id)
    result = await align_module.run_align(job, factory)
    assert result["method"] == "proportional"
    async with factory() as session:
        timings = (
            await session.execute(select(Asset).where(Asset.kind == "word_timings"))
        ).scalars().all()
        assert len(timings) == 1
        assert timings[0].is_selected
        assert len(timings[0].data["words"]) == 7
