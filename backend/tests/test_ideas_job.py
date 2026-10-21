import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings, get_settings
from app.db.models import ContentIdea, GenerationJob, Project, UsageRecord
from app.jobs.handlers import HANDLERS
from app.jobs.queue import enqueue
from app.services.prompts import sync_prompts
from app.services.providers_seed import seed_providers
from app.worker import Worker


@pytest.fixture(autouse=True)
def _app_secret(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def factory_of(session):
    return async_sessionmaker(session.bind, expire_on_commit=False)


async def make_project(session, *, with_fake_provider=True) -> Project:
    await sync_prompts(session)
    if with_fake_provider:
        await seed_providers(session, Settings(app_secret_key="test-secret-key"))
    project = Project(title="cicak", topic="kenapa cicak bisa menempel di dinding")
    session.add(project)
    await session.commit()
    return project


async def test_ideas_job_writes_batch_of_eight(session):
    project = await make_project(session)
    job = await enqueue(session, type="ideas", input={}, project_id=project.id)
    await session.commit()

    worker = Worker(session_factory=factory_of(session))
    assert await worker.run_once() is True

    ideas = (
        (
            await session.execute(
                select(ContentIdea)
                .where(ContentIdea.project_id == project.id)
                .order_by(ContentIdea.position)
            )
        )
        .scalars()
        .all()
    )
    assert len(ideas) == 8
    assert ideas[0].batch == 1
    assert all(row.job_id == job.id for row in ideas)
    assert any("cicak" in row.title.lower() for row in ideas)
    assert {row.fact_risk for row in ideas} <= {"low", "check"}
    for row in ideas:
        if row.fact_risk == "check":
            assert row.fact_note

    refreshed = await session.get(GenerationJob, job.id)
    await session.refresh(refreshed)
    assert refreshed.status == "completed"
    assert refreshed.provider_id and refreshed.prompt_version_id
    assert refreshed.result["batch"] == 1
    assert "llm_raw" in refreshed.result

    usage = (await session.execute(select(UsageRecord))).scalars().all()
    assert len(usage) == 1 and usage[0].capability == "llm"

    project_after = await session.get(Project, project.id)
    await session.refresh(project_after)
    assert project_after.category_source == "suggested"
    assert project_after.category_id is not None


async def test_ideas_handler_retry_reuses_batch(session):
    project = await make_project(session)
    job = await enqueue(session, type="ideas", input={}, project_id=project.id)
    await session.commit()
    handler = HANDLERS["ideas"]
    first = await handler(job, factory_of(session))
    second = await handler(job, factory_of(session))
    assert first["batch"] == second["batch"] == 1
    rows = (
        (await session.execute(select(ContentIdea).where(ContentIdea.project_id == project.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 8


async def test_ideas_job_without_provider_fails_with_kind(session):
    project = await make_project(session, with_fake_provider=False)
    job = await enqueue(session, type="ideas", input={}, project_id=project.id)
    await session.commit()
    worker = Worker(session_factory=factory_of(session))
    assert await worker.run_once() is True
    refreshed = await session.get(GenerationJob, job.id)
    await session.refresh(refreshed)
    assert refreshed.status == "failed"
    assert refreshed.error["kind"] == "NoLlmProvider"
    assert refreshed.error["retryable"] is False
