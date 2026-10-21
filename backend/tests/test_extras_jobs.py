import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Asset, Base, GenerationJob, Project, Provider, Scene, Script, VisualStyle
from app.jobs.metadata import run_metadata
from app.jobs.thumbnail import NoRenderError, run_thumbnail
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
        session.add_all([
            Provider(name="Gambar Fake", capability="image", adapter="fake",
                     enabled=True, priority=100),
            Provider(name="LLM Fake", capability="llm", adapter="fake",
                     enabled=True, priority=100),
            VisualStyle(name="Gaya", style_text="flat doodle", negative_text="photo",
                        mascot_anchor="Tikus Berdasi, a cartoon rat.",
                        image_params={}, is_default=True),
        ])
        project = Project(title="MSCI Mengusulkan Indonesia Turun Kelas", topic="MSCI")
        session.add(project)
        await session.flush()
        script = Script(project_id=project.id, version=1, status="approved",
                        source="generated", title="MSCI Mengusulkan Indonesia Turun Kelas",
                        hook="Kabar panas!")
        session.add(script)
        await session.flush()
        project.active_script_id = script.id
        session.add(Scene(script_id=script.id, position=1,
                          voiceover="Kabar panas dari pasar",
                          visual_prompt="a cartoon rat reading a newspaper"))
        render = Asset(project_id=project.id, scene_id=None, kind="render",
                       storage_key="assets/x/video.mp4", mime="video/mp4",
                       input_hash="rh", data={}, is_selected=True, version=1)
        session.add(render)
        for job_type in ("thumbnail", "metadata"):
            session.add(GenerationJob(type=job_type, project_id=project.id,
                                      input={}, status="processing"))
        await session.commit()
    yield maker
    await engine.dispose()


async def _jobs(factory):
    async with factory() as session:
        return {
            j.type: j for j in (await session.execute(select(GenerationJob))).scalars()
        }


async def test_thumbnail_job_creates_selected_asset(factory):
    jobs = await _jobs(factory)
    result = await run_thumbnail(jobs["thumbnail"], factory)
    async with factory() as session:
        asset = await session.get(Asset, result["asset_id"])
        assert asset.kind == "thumbnail" and asset.is_selected
        assert asset.width == 1080 and asset.height == 1920
        assert asset.data["title_text"] == "MSCI MENGUSULKAN INDONESIA TURUN KELAS"


async def test_metadata_job_creates_payload(factory):
    jobs = await _jobs(factory)
    result = await run_metadata(jobs["metadata"], factory)
    async with factory() as session:
        asset = await session.get(Asset, result["asset_id"])
        assert asset.kind == "metadata" and asset.is_selected
        assert "MSCI" in asset.data["title"]
        assert asset.data["hashtags"]
        assert asset.data["fb_caption"]


async def test_thumbnail_requires_render(factory):
    async with factory() as session:
        render = (await session.execute(
            select(Asset).where(Asset.kind == "render"))).scalar_one()
        render.is_selected = False
        await session.commit()
    jobs = await _jobs(factory)
    with pytest.raises(NoRenderError):
        await run_thumbnail(jobs["thumbnail"], factory)
