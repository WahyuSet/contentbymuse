import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.models import (
    Asset,
    Base,
    ContentIdea,
    Project,
    Provider,
    Scene,
    Script,
)
from app.jobs import queue
from app.services import lang_qc


@pytest.fixture
def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/voice_qc.db")
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    cfg = Settings(app_secret_key="rahasia-tes", storage_path=tmp_path / "storage")
    monkeypatch.setattr("app.jobs.voice.get_settings", lambda: cfg)
    monkeypatch.setattr("app.jobs.align.get_settings", lambda: cfg)
    return cfg


@pytest.fixture
def qc_on(monkeypatch):
    monkeypatch.setenv("WHISPER_MODEL", "tiny")


def _fake_detector(monkeypatch, outcomes):
    calls = {"count": 0}
    sequence = iter(outcomes)

    def _detect(audio_path):
        calls["count"] += 1
        outcome = next(sequence)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(lang_qc, "detect_language", _detect)
    return calls


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
        from app.db.models import GenerationJob

        return await session.get(GenerationJob, job.id)


async def _clips(factory):
    async with factory() as session:
        return (
            await session.execute(
                select(Asset).where(Asset.kind == "voice_clip").order_by(Asset.version)
            )
        ).scalars().all()


# --- Unit: evaluate_qc / rank_key / qc_enabled -------------------------------


def test_evaluate_qc_threshold_and_language():
    assert lang_qc.evaluate_qc("id", 0.6) is True
    assert lang_qc.evaluate_qc("id", 0.59) is False
    assert lang_qc.evaluate_qc("ms", 0.99) is False
    assert lang_qc.evaluate_qc("en", 0.9) is False


def test_rank_key_prefers_pass_then_id_then_probability():
    assert lang_qc.rank_key("id", 0.9) > lang_qc.rank_key("en", 0.99)
    assert lang_qc.rank_key("id", 0.5) > lang_qc.rank_key("ms", 0.99)
    assert lang_qc.rank_key("ms", 0.9) > lang_qc.rank_key("en", 0.8)


def test_qc_enabled_follows_env(monkeypatch):
    monkeypatch.delenv("WHISPER_MODEL", raising=False)
    assert lang_qc.qc_enabled() is False
    monkeypatch.setenv("WHISPER_MODEL", "")
    assert lang_qc.qc_enabled() is False
    monkeypatch.setenv("WHISPER_MODEL", "tiny")
    assert lang_qc.qc_enabled() is True


# --- Integrasi job voice ------------------------------------------------------


async def test_qc_pass_keeps_single_clip(factory, settings, qc_on, monkeypatch):
    from app.jobs.voice import run_voice

    _fake_detector(monkeypatch, [("id", 0.9)])
    project_id, _script_id, scene_ids = await _seed(factory)
    job = await _voice_job(factory, project_id, scene_ids[0])
    result = await run_voice(job, factory)

    clips = await _clips(factory)
    assert len(clips) == 1
    assert clips[0].is_selected
    record = clips[0].data["lang_qc"]
    assert record["language"] == "id"
    assert record["probability"] == pytest.approx(0.9)
    assert record["attempts"] == 0
    assert record["passed"] is True
    assert result["lang_qc"]["passed"] is True
    assert not result.get("warnings")


async def test_qc_fail_then_regen_passes(factory, settings, qc_on, monkeypatch):
    from app.jobs.voice import run_voice

    _fake_detector(monkeypatch, [("en", 0.8), ("id", 0.95)])
    project_id, _script_id, scene_ids = await _seed(factory)
    job = await _voice_job(factory, project_id, scene_ids[0])
    result = await run_voice(job, factory)

    clips = await _clips(factory)
    assert len(clips) == 2
    first, second = clips
    assert not first.is_selected
    assert second.is_selected
    assert result["asset_id"] == second.id
    assert first.data["lang_qc"]["language"] == "en"
    assert first.data["lang_qc"]["passed"] is False
    record = second.data["lang_qc"]
    assert record["language"] == "id"
    assert record["attempts"] == 1
    assert record["passed"] is True
    assert result["lang_qc"]["passed"] is True
    assert not result.get("warnings")


async def test_qc_always_fail_caps_regenerations(factory, settings, qc_on, monkeypatch):
    from app.jobs.voice import run_voice

    _fake_detector(monkeypatch, [("ms", 0.9)] * 5)
    project_id, _script_id, scene_ids = await _seed(factory)
    job = await _voice_job(factory, project_id, scene_ids[0])
    result = await run_voice(job, factory)

    clips = await _clips(factory)
    assert len(clips) == 3  # 1 awal + 2 regenerasi, tidak lebih
    selected = [c for c in clips if c.is_selected]
    assert len(selected) == 1
    record = result["lang_qc"]
    assert record["attempts"] == 2
    assert record["passed"] is False
    assert selected[0].data["lang_qc"]["attempts"] == 2
    assert selected[0].data["lang_qc"]["passed"] is False
    assert result.get("warnings")


async def test_qc_detector_error_marks_unavailable(factory, settings, qc_on, monkeypatch):
    from app.jobs.voice import run_voice

    _fake_detector(monkeypatch, [RuntimeError("whisper meledak")])
    project_id, _script_id, scene_ids = await _seed(factory)
    job = await _voice_job(factory, project_id, scene_ids[0])
    result = await run_voice(job, factory)

    clips = await _clips(factory)
    assert len(clips) == 1
    assert clips[0].is_selected
    assert clips[0].data["lang_qc"]["status"] == "unavailable"
    assert "whisper meledak" in clips[0].data["lang_qc"]["error"]
    assert result["asset_id"] == clips[0].id
