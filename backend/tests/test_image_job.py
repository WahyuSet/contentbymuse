import io

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.jobs.image as image_job
from app.db.models import Base, GenerationJob, Project, Provider, Scene, Script, VisualStyle
from app.jobs.queue import enqueue
from app.providers.registry import ADAPTERS
from app.services.prompts import sync_prompts


@pytest.fixture
async def factory(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    from app.config import get_settings

    get_settings.cache_clear()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        await sync_prompts(session)
        provider = Provider(
            name="Gambar Fake", capability="image", adapter="fake",
            enabled=True, priority=100,
        )
        session.add(provider)
        session.add(
            VisualStyle(
                name="Gaya", style_text="flat doodle", negative_text="photo",
                mascot_anchor="Si Klepon, a green-headed stick figure.",
                image_params={}, is_default=True,
            )
        )
        project = Project(title="P", topic="t")
        session.add(project)
        await session.flush()
        script = Script(
            project_id=project.id, version=1, status="approved",
            source="generated", title="Naskah", hook="h",
        )
        session.add(script)
        await session.flush()
        project.active_script_id = script.id
        scene = Scene(
            script_id=script.id, position=1, voiceover="cicak menempel",
            visual_prompt="a gecko on a wall", visual_type="character",
            include_mascot=True, est_duration_s=1.0,
        )
        session.add(scene)
        await session.commit()
        ids = (project.id, scene.id, provider.id)
    yield maker, ids
    await engine.dispose()
    get_settings.cache_clear()


async def _run_one(maker, scene_id, extra=None):
    async with maker() as session:
        job = await enqueue(
            session, type="image", input={"scene_id": scene_id, **(extra or {})}
        )
        await session.commit()
        job_id = job.id
    await image_job.run_image(job, maker)
    # Seperti worker: tandai selesai agar indeks dedup aktif melepas antrean
    # berikutnya dengan input yang sama.
    async with maker() as session:
        stored = await session.get(GenerationJob, job_id)
        stored.status = "completed"
        await session.commit()
    return job_id


async def test_image_job_creates_selected_portrait(factory):
    maker, (_project_id, scene_id, _pid) = factory
    await _run_one(maker, scene_id)
    async with maker() as session:
        rows = (
            await session.execute(
                select(image_job.Asset).where(image_job.Asset.kind == "image")
            )
        ).scalars().all()
    assert len(rows) == 1
    asset = rows[0]
    assert asset.is_selected is True
    assert asset.width == 1080 and asset.height == 1920
    assert asset.storage_key.endswith("image-v1.png")
    assert "gecko" in asset.data["prompt"]
    from app.config import get_settings

    path = get_settings().storage_path / asset.storage_key
    image = Image.open(io.BytesIO(path.read_bytes()))
    assert image.size == (1080, 1920)


async def test_image_job_cache_and_force(factory):
    maker, (_p, scene_id, _pid) = factory
    calls = {"n": 0}
    original = ADAPTERS[("image", "fake")]

    class CountingFake(original):
        async def generate_image(self, req, ctx=None):
            calls["n"] += 1
            return await super().generate_image(req, ctx)

    ADAPTERS[("image", "fake")] = CountingFake
    try:
        await _run_one(maker, scene_id)
        await _run_one(maker, scene_id)
        assert calls["n"] == 1  # kedua dari cache
        await _run_one(maker, scene_id, {"force": True})
        assert calls["n"] == 2
    finally:
        ADAPTERS[("image", "fake")] = original
    async with maker() as session:
        rows = (
            await session.execute(
                select(image_job.Asset)
                .where(image_job.Asset.kind == "image")
                .order_by(image_job.Asset.version)
            )
        ).scalars().all()
    assert [r.version for r in rows] == [1, 2]
    assert rows[1].is_selected is True
