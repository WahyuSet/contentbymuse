import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.models import Base, ContentIdea, GenerationJob, Project, Scene, Script
from app.jobs import queue
from app.jobs.checks_fix import run_checks_fix
from app.jobs.queue import enqueue_once
from app.jobs.script import run_script
from app.services.prompts import sync_prompts
from app.services.providers_seed import seed_providers


@pytest.fixture
def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/script.db")
    return async_sessionmaker(engine, expire_on_commit=False)


async def _setup(factory):
    async with factory() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)
        await session.commit()
    async with factory() as session:
        await sync_prompts(session)
        await seed_providers(session, Settings(app_secret_key="test-secret"))
        project = Project(title="Cicak", topic="kenapa cicak bisa menempel di dinding")
        session.add(project)
        await session.flush()
        idea = ContentIdea(
            project_id=project.id,
            batch=1,
            position=1,
            title="Cicak bisa menempel di dinding",
            angle="Jawaban singkatnya: rambut mikroskopis di telapak kaki.",
            hook="Pernah lihat cicak berjalan di langit-langit?",
            job_id="01JIDEA",
        )
        session.add(idea)
        await session.flush()
        project.selected_idea_id = idea.id
        await session.commit()
        return project.id, idea.id


async def test_enqueue_once_returns_existing_even_completed(session):
    job, created = await enqueue_once(
        session, type="validate", input={"script_id": "S1"}, project_id="P1"
    )
    assert created is True
    await session.commit()
    again, created2 = await enqueue_once(
        session, type="validate", input={"script_id": "S1"}, project_id="P1"
    )
    assert created2 is False and again.id == job.id
    job.status = "completed"
    await session.commit()
    third, created3 = await enqueue_once(
        session, type="validate", input={"script_id": "S1"}, project_id="P1"
    )
    assert created3 is False and third.id == job.id


async def test_script_handler_saves_version_and_queues_validate(factory):
    project_id, idea_id = await _setup(factory)
    async with factory() as session:
        job = await queue.enqueue(
            session, type="script", input={"idea_id": idea_id}, project_id=project_id
        )
        await session.commit()
        job_id = job.id
        stored = await session.get(GenerationJob, job_id)
    await run_script(stored, factory)
    async with factory() as session:
        scripts = (await session.execute(select(Script))).scalars().all()
        assert len(scripts) == 1
        script = scripts[0]
        assert script.source == "generated" and script.version == 1
        assert script.job_id == job_id
        scenes = (
            await session.execute(select(Scene).where(Scene.script_id == script.id))
        ).scalars().all()
        assert len(scenes) == 10
        assert script.estimated_duration_s > 30
        followups = (
            await session.execute(
                select(GenerationJob).where(GenerationJob.type == "validate")
            )
        ).scalars().all()
        assert len(followups) == 1
        assert followups[0].input == {"script_id": script.id, "auto_revise": True}
        await run_script(stored, factory)
        scripts2 = (await session.execute(select(Script))).scalars().all()
        assert len(scripts2) == 1


async def test_checks_fix_creates_fixed_version(factory):
    project_id, idea_id = await _setup(factory)
    async with factory() as session:
        broken = Script(
            project_id=project_id, idea_id=idea_id, version=1,
            title="Rusak", hook="x", job_id="01JBROKEN",
        )
        session.add(broken)
        await session.flush()
        for pos in range(1, 6):
            session.add(Scene(
                script_id=broken.id, position=pos, beat="main",
                voiceover="Satu dua tiga empat lima enam", visual_prompt="v",
                visual_type="character",
            ))
        await session.commit()
        broken_id = broken.id
        job = await queue.enqueue(
            session, type="checks_fix", input={"script_id": broken_id},
            project_id=project_id,
        )
        await session.commit()
        stored = await session.get(GenerationJob, job.id)
    await run_checks_fix(stored, factory)
    async with factory() as session:
        fixed = (
            await session.execute(select(Script).where(Script.source == "fixed"))
        ).scalars().all()
        assert len(fixed) == 1
        assert fixed[0].parent_id == broken_id
        scenes = (
            await session.execute(select(Scene).where(Scene.script_id == fixed[0].id))
        ).scalars().all()
        assert len(scenes) == 10
        validate_jobs = (
            await session.execute(
                select(GenerationJob).where(GenerationJob.type == "validate")
            )
        ).scalars().all()
        assert len(validate_jobs) == 1
        assert validate_jobs[0].input["script_id"] == fixed[0].id
