import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.jobs.render as render_job
from app.config import Settings
from app.db.models import Asset, Base, GenerationJob, Project, Scene, Script
from app.jobs.queue import enqueue
from app.jobs.script_chain import ScriptInputError
from app.services import assets as asset_service
from app.services.ffmpeg_render import RenderResult


@pytest.fixture
def world(tmp_path, monkeypatch):
    cfg = Settings(app_secret_key="rahasia-tes", storage_path=tmp_path / "storage")
    monkeypatch.setattr("app.jobs.render.get_settings", lambda: cfg)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            project = Project(title="P", topic="t")
            session.add(project)
            await session.flush()
            script = Script(
                project_id=project.id, version=1, status="approved",
                title="N", hook="H",
            )
            session.add(script)
            await session.flush()
            project.active_script_id = script.id
            scene = Scene(
                script_id=script.id, position=1, voiceover="cicak menempel",
                visual_prompt="v", visual_type="character", est_duration_s=3.0,
            )
            session.add(scene)
            await session.flush()
            for kind, key, mime in (
                ("voice_clip", f"assets/{project.id}/{scene.id}/voice.mp3", "audio/mpeg"),
                ("image", f"assets/{project.id}/{scene.id}/image.png", "image/png"),
            ):
                path = cfg.storage_path / key
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"x" * 16)
                created = await asset_service.create_asset(
                    session, project_id=project.id, scene_id=scene.id,
                    kind=kind, storage_key=key, mime=mime, size_bytes=16,
                    duration_s=3.0 if kind == "voice_clip" else None,
                    input_hash=f"hash-{kind}",
                    # Bentuk kanonis media_probe — regresi bug 2026-10-22:
                    # render.py sempat membaca "start"/"end" dan KeyError
                    # pada clip pertama yang benar-benar punya trim.
                    data={"trim": {"start_s": 0.0, "end_s": 3.0}}
                    if kind == "voice_clip"
                    else {},
                )
                await asset_service.select_asset(session, created)
            await session.commit()
            return project.id, scene.id

    ids = asyncio.run(_setup())
    yield factory, ids, cfg
    asyncio.run(engine.dispose())


def _fake_result(workdir_holder):
    async def fake_run_render(plan, *, workdir, **kwargs):
        video = workdir / "video.mp4"
        video.write_bytes(b"\x00" * 2048)
        (workdir / "subtitles.srt").write_text("1\n", encoding="utf-8")
        (workdir / "subtitles.ass").write_text("[Script Info]\n", encoding="utf-8")
        (workdir / "thumbnail.jpg").write_bytes(b"\xff\xd8" * 32)
        workdir_holder.append(workdir)
        return RenderResult(
            video_path=video,
            srt_path=workdir / "subtitles.srt",
            ass_path=workdir / "subtitles.ass",
            thumbnail_path=workdir / "thumbnail.jpg",
            duration_s=plan.total_duration_s,
            encoder="libx264",
            render_seconds=1.5,
            warnings=[],
        )

    return fake_run_render


async def test_render_job_creates_render_asset(world, monkeypatch):
    factory, (project_id, _scene_id), _cfg = world
    monkeypatch.setattr(render_job, "run_render", _fake_result([]))
    async with factory() as session:
        job = await enqueue(
            session, type="render", input={}, project_id=project_id
        )
        await session.commit()
        job_id = job.id
    async with factory() as session:
        job = await session.get(GenerationJob, job_id)
    result = await render_job.run_render_job(job, factory)
    assert result["cached"] is False
    async with factory() as session:
        asset = (
            await session.execute(
                select(Asset).where(
                    Asset.project_id == project_id, Asset.kind == "render"
                )
            )
        ).scalar_one()
    assert asset.is_selected
    assert asset.data["encoder"] == "libx264"
    assert set(asset.data["files"]) == {"video", "srt", "ass", "thumbnail"}


async def test_render_job_cache_hit(world, monkeypatch):
    factory, (project_id, _scene_id), _cfg = world
    calls: list = []
    monkeypatch.setattr(render_job, "run_render", _fake_result(calls))
    async with factory() as session:
        job = await enqueue(session, type="render", input={}, project_id=project_id)
        await session.commit()
        first = await render_job.run_render_job(job, factory)
        job.status = "completed"  # handler dipanggil langsung; tiru worker
        await session.commit()
        job2 = await enqueue(
            session, type="render", input={}, project_id=project_id
        )
        await session.commit()
        second = await render_job.run_render_job(job2, factory)
    assert first["cached"] is False
    assert second["cached"] is True
    assert len(calls) == 1  # ffmpeg hanya sekali


async def test_render_job_rejects_unapproved(world, monkeypatch):
    factory, (project_id, _scene_id), _cfg = world
    monkeypatch.setattr(render_job, "run_render", _fake_result([]))
    async with factory() as session:
        script = (await session.execute(select(Script))).scalar_one()
        script.status = "validated"
        job = await enqueue(session, type="render", input={}, project_id=project_id)
        await session.commit()
    with pytest.raises(ScriptInputError):
        await render_job.run_render_job(job, factory)


async def test_reconcile_render_enqueues_once(world):
    factory, (project_id, _scene_id), _cfg = world
    from app.services.reconcile import _reconcile_render

    async with factory() as session:
        project = await session.get(Project, project_id)
        await _reconcile_render(session, project)
        await _reconcile_render(session, project)
        await session.commit()
    async with factory() as session:
        jobs = (
            await session.execute(
                select(GenerationJob).where(GenerationJob.type == "render")
            )
        ).scalars().all()
    assert len(jobs) == 1
