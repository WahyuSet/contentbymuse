import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import (
    Base,
    ContentIdea,
    GenerationJob,
    Project,
    Provider,
    Scene,
    Script,
    VisualStyle,
)
from app.services import assets as asset_service
from app.services.prompts import compose_image_prompt, sync_prompts
from app.services.reconcile import reconcile


@pytest.fixture
async def seeded(tmp_path):
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
        style = VisualStyle(
            name="Gaya", style_text="flat doodle", negative_text="photo",
            mascot_anchor="Si Klepon, a green-headed stick figure.",
            image_params={}, is_default=True,
        )
        session.add(style)
        project = Project(title="P", topic="t")
        session.add(project)
        await session.flush()
        idea = ContentIdea(
            project_id=project.id, batch=1, position=1, title="Ide", job_id="01JI"
        )
        session.add(idea)
        await session.flush()
        script = Script(
            project_id=project.id, idea_id=idea.id, version=1, title="N",
            hook="H", status="approved", job_id="01JS",
        )
        session.add(script)
        await session.flush()
        scene_ids = []
        for pos in (1, 2, 3):
            scene = Scene(
                script_id=script.id, position=pos, voiceover=f"narasi {pos}",
                visual_prompt=f"visual {pos}", visual_type="character",
                est_duration_s=3.0,
            )
            session.add(scene)
            await session.flush()
            scene_ids.append(scene.id)
        project.selected_idea_id = idea.id
        project.active_script_id = script.id
        await session.commit()
        ids = (project.id, scene_ids, provider.id, style.id)
    yield maker, ids
    await engine.dispose()


async def _image_jobs(maker):
    async with maker() as session:
        return (
            await session.execute(
                select(GenerationJob).where(GenerationJob.type == "image")
            )
        ).scalars().all()


async def test_reconcile_enqueues_image_jobs_once(seeded):
    maker, (project_id, scene_ids, provider_id, _style_id) = seeded
    await reconcile(project_id, maker)
    jobs = await _image_jobs(maker)
    assert len(jobs) == 3
    assert {j.scene_id for j in jobs} == set(scene_ids)
    assert all(j.resource_key == f"image:{provider_id}" for j in jobs)
    assert all(j.max_attempts == 3 for j in jobs)
    await reconcile(project_id, maker)
    assert len(await _image_jobs(maker)) == 3


async def test_reconcile_stops_when_image_hash_matches(seeded):
    maker, (project_id, scene_ids, provider_id, style_id) = seeded
    async with maker() as session:
        project = await session.get(Project, project_id)
        style = await session.get(VisualStyle, style_id)
        provider = await session.get(Provider, provider_id)
        scene = await session.get(Scene, scene_ids[0])
        prompt = await compose_image_prompt(session, style, scene)
        digest = asset_service.image_input_hash(
            prompt=prompt, negative_text="photo", provider=provider.id,
            model=None, params={}, reference_hash=None,
        )
        asset = await asset_service.create_asset(
            session, project_id=project_id, scene_id=scene.id, kind="image",
            storage_key="assets/x.png", mime="image/png", size_bytes=10,
            input_hash=digest, provider_id=provider.id,
        )
        await asset_service.select_asset(session, asset)
        await session.commit()
        project_id = project.id
    await reconcile(project_id, maker)
    jobs = await _image_jobs(maker)
    assert {j.scene_id for j in jobs} == {scene_ids[1], scene_ids[2]}
