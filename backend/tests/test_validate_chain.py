import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.models import (
    Base,
    ContentIdea,
    GenerationJob,
    Project,
    Scene,
    Script,
    ValidationResult,
)
from app.domain.llm_outputs import ValidationOutput
from app.jobs import queue
from app.jobs.revise import run_revise
from app.jobs.validate import run_validate
from app.providers.base import TextResult, Usage
from app.services.finalize import finalize_best
from app.services.prompts import sync_prompts
from app.services.providers_seed import seed_providers
from app.services.reconcile import reconcile
from app.worker import Worker


@pytest.fixture
def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/val.db")
    return async_sessionmaker(engine, expire_on_commit=False)


async def _setup(factory, *, max_revisions=None):
    async with factory() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)
        await session.commit()
    async with factory() as session:
        await sync_prompts(session)
        await seed_providers(session, Settings(app_secret_key="test-secret"))
        settings = {"max_revisions": max_revisions} if max_revisions is not None else {}
        project = Project(
            title="Cicak", topic="kenapa cicak bisa menempel di dinding", settings=settings
        )
        session.add(project)
        await session.flush()
        idea = ContentIdea(
            project_id=project.id, batch=1, position=1,
            title="Rahasia besar di balik cicak bisa menempel di dinding",
            angle="Rambut mikroskopis.", hook="Pernah lihat cicak di langit-langit?",
            job_id="01JIDEA",
        )
        session.add(idea)
        await session.flush()
        project.selected_idea_id = idea.id
        script = Script(
            project_id=project.id, idea_id=idea.id, version=1,
            title=idea.title, hook="Rahasia besar di balik cicak bisa menempel",
            job_id="01JSCRIPT",
        )
        session.add(script)
        await session.flush()
        voiceovers = [
            "Rahasia besar di balik cicak bisa menempel",
            "Banyak orang melihatnya tetapi jarang ada yang memperhatikan",
            "Padahal ada penjelasan sederhana di balik kejadian ini",
            "Penjelasan itu berkaitan dengan kebiasaan dan lingkungan sekitarnya",
            "Saat kondisi berubah tubuh langsung menyesuaikan diri perlahan",
            "Penyesuaian ini membantu bertahan dari gangguan di sekitarnya",
            "Tidak semua kejadian menunjukkan proses yang sama persis",
            "Ada kalanya prosesnya gagal dan hasilnya berbeda jauh",
            "Jadi kejadian tadi bukan kebetulan tanpa sebab apa pun",
            "Pernah mengalami hal serupa di rumah atau sekitarmu",
        ]
        beats = ["hook", "setup"] + ["main"] * 6 + ["payoff", "cta"]
        types = ["character", "closeup", "character", "environment", "process",
                 "diagram", "character", "closeup", "character", "environment"]
        for pos, (vo, beat, vt) in enumerate(zip(voiceovers, beats, types), start=1):
            session.add(Scene(
                script_id=script.id, position=pos, beat=beat, voiceover=vo,
                visual_prompt=f"Scene {pos}", visual_type=vt,
                include_mascot=pos not in (4, 7), est_duration_s=3.6,
            ))
        script.estimated_duration_s = 36.0
        await session.commit()
        return project.id, idea.id, script.id


class StubLLM:
    caps = None

    def __init__(self, outputs: list[ValidationOutput]):
        self.outputs = outputs
        self.calls = 0

    async def generate_text(self, req, ctx=None):
        self.calls += 1
        output = self.outputs.pop(0)
        return TextResult(
            text=output.model_dump_json(), usage=Usage(input_tokens=5, output_tokens=5)
        )


def output(status: str, score: int = 70) -> ValidationOutput:
    return ValidationOutput(status=status, score=score, summary="ringkasan", issues=[], claims_to_verify=[])


async def test_validate_pass_sets_active_via_worker_drain(factory):
    project_id, _idea_id, script_id = await _setup(factory)
    async with factory() as session:
        await queue.enqueue(
            session, type="validate",
            input={"script_id": script_id, "auto_revise": True}, project_id=project_id,
        )
        await session.commit()
    worker = Worker(session_factory=factory)
    for _ in range(6):
        await worker.run_once()
    async with factory() as session:
        project = await session.get(Project, project_id)
        script = await session.get(Script, script_id)
        assert script.status == "validated"
        assert project.active_script_id == script_id
        results = (await session.execute(select(ValidationResult))).scalars().all()
        assert len(results) == 1 and results[0].status == "PASS"


async def test_revise_loop_respects_max_revisions(factory):
    project_id, _idea_id, script_id = await _setup(factory, max_revisions=1)
    stub = StubLLM([output("NEEDS_REVISION", 55), output("NEEDS_REVISION", 60)])
    async with factory() as session:
        stored_job = await queue.enqueue(
            session, type="validate",
            input={"script_id": script_id, "auto_revise": True}, project_id=project_id,
        )
        await session.commit()
    import app.jobs.validate as validate_module

    original = validate_module.build_validation_pairs

    async def fake_pairs(session):
        from app.db.models import Provider

        provider = (
            await session.execute(select(Provider).limit(1))
        ).scalars().first()
        return [(provider, stub)]

    validate_module.build_validation_pairs = fake_pairs
    try:
        await run_validate(stored_job, factory)
    finally:
        validate_module.build_validation_pairs = original
    async with factory() as session:
        revise_jobs = (
            await session.execute(
                select(GenerationJob).where(GenerationJob.type == "revise")
            )
        ).scalars().all()
        assert len(revise_jobs) == 1
        revise_job = revise_jobs[0]
    await run_revise(revise_job, factory)
    async with factory() as session:
        versions = (
            await session.execute(select(Script).order_by(Script.version))
        ).scalars().all()
        assert [v.source for v in versions] == ["generated", "revised"]
        validate_jobs = (
            await session.execute(
                select(GenerationJob)
                .where(GenerationJob.type == "validate")
                .order_by(GenerationJob.created_at)
            )
        ).scalars().all()
        assert len(validate_jobs) == 2
        second = validate_jobs[1]
    validate_module.build_validation_pairs = fake_pairs
    try:
        await run_validate(second, factory)
    finally:
        validate_module.build_validation_pairs = original
    async with factory() as session:
        revised = (
            await session.execute(select(Script).where(Script.source == "revised"))
        ).scalar_one()
        assert revised.status == "needs_attention"
        project = await session.get(Project, project_id)
        assert project.active_script_id == revised.id
        assert stub.calls == 2


async def test_finalize_best_prefers_clean_validated(factory):
    project_id, idea_id, script_id = await _setup(factory)
    async with factory() as session:
        v2 = Script(
            project_id=project_id, idea_id=idea_id, version=2, source="revised",
            title="Versi dua", hook="h", job_id="01JV2", best_score=95,
        )
        session.add(v2)
        await session.flush()
        for pos in range(1, 6):  # scene kurang -> error cek
            session.add(Scene(
                script_id=v2.id, position=pos, beat="main",
                voiceover="Satu dua tiga empat lima enam", visual_prompt="v",
                visual_type="character",
            ))
        v1 = await session.get(Script, script_id)
        v1.best_score = 85
        session.add(ValidationResult(
            script_id=script_id, attempt=1, status="PASS", score=85, job_id="01JVR1"
        ))
        session.add(ValidationResult(
            script_id=v2.id, attempt=1, status="NEEDS_REVISION", score=95, job_id="01JVR2"
        ))
        await session.commit()
        project = await session.get(Project, project_id)
        await finalize_best(session, project)
        await session.commit()
        assert project.active_script_id == script_id


async def test_reconcile_enqueues_script_only_when_missing(factory):
    project_id, _idea_id, _script_id = await _setup(factory)
    await reconcile(project_id, factory)
    async with factory() as session:
        jobs = (
            await session.execute(
                select(GenerationJob).where(GenerationJob.type == "script")
            )
        ).scalars().all()
        assert jobs == []  # script untuk ide terpilih sudah ada
        project = await session.get(Project, project_id)
        project.selected_idea_id = "01JIDEALAIN"
        await session.commit()
    await reconcile(project_id, factory)
    async with factory() as session:
        jobs = (
            await session.execute(
                select(GenerationJob).where(GenerationJob.type == "script")
            )
        ).scalars().all()
        assert len(jobs) == 1
        assert jobs[0].input == {"idea_id": "01JIDEALAIN"}
