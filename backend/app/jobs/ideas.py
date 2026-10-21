from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.db.models import Category, ContentIdea, Format, GenerationJob, Project, UsageRecord
from app.domain.llm_outputs import IdeasOutput
from app.jobs.context import DbCallContext
from app.providers.router import ProviderRouter
from app.services.prompts import PromptService
from app.services.structured_llm import StructuredLLM, validate_ideas


class NoLlmProviderError(Exception):
    kind = "NoLlmProvider"
    retryable = False

    def __init__(self):
        super().__init__("Belum ada provider LLM yang aktif. Aktifkan satu provider di Pengaturan.")


async def _catalog_input(session, row, kind: str) -> dict | None:
    if row is None:
        return None
    rules = await PromptService(session).active_body(f"{kind}.{row.slug}")
    return {"name": row.name, "rules": rules}


async def run_ideas(job, factory: async_sessionmaker) -> dict:
    ctx = DbCallContext(job.id, factory)
    async with factory() as session:
        existing = (
            await session.execute(
                select(ContentIdea)
                .where(ContentIdea.job_id == job.id)
                .order_by(ContentIdea.position)
            )
        ).scalars().all()
        if existing:
            # Retry sesudah worker mati: batch milik job ini sudah tertulis (Spec §2.1).
            await ctx.log("info", "Batch ide dari job ini sudah ada, dipakai ulang")
            return {
                "batch": existing[0].batch,
                "idea_ids": [row.id for row in existing],
                "reused": True,
            }
        project = await session.get(Project, job.project_id)
        if project is None:
            raise LookupError("Project untuk job ideas tidak ditemukan.")
        category = (
            await session.get(Category, project.category_id)
            if project.category_id
            else None
        )
        fmt = await session.get(Format, project.format_id) if project.format_id else None
        inputs = {
            "topic": project.topic,
            "language": project.language,
            "category": await _catalog_input(session, category, "category"),
            "format": await _catalog_input(session, fmt, "format"),
        }
        valid_slugs = {
            row.slug
            for row in (
                await session.execute(select(Category).where(Category.enabled.is_(True)))
            ).scalars()
        }
        router = ProviderRouter(session)
        settings = get_settings()
        pairs = []
        for provider in await router.candidates("llm", project):
            pairs.append((provider, await router.build_llm(provider, settings)))
        if not pairs:
            raise NoLlmProviderError()
        await ctx.progress(30, "Meminta ide ke provider LLM")
        task = "ideas.from_topic" if project.topic else "ideas.discover"
        result = await StructuredLLM(pairs, PromptService(session)).generate(
            task=task,
            inputs=inputs,
            output_model=IdeasOutput,
            ctx=ctx,
            validate=lambda out: validate_ideas(out, valid_slugs),
        )
        data: IdeasOutput = result.data
        batch = (
            await session.execute(
                select(func.max(ContentIdea.batch)).where(
                    ContentIdea.project_id == project.id
                )
            )
        ).scalar_one_or_none() or 0
        batch += 1
        rows = []
        for position, item in enumerate(data.ideas, start=1):
            row = ContentIdea(
                project_id=project.id,
                batch=batch,
                position=position,
                title=item.title,
                angle=item.angle,
                hook=item.hook,
                why_it_works=item.why_it_works,
                suggested_category_slug=data.suggested_category,
                fact_risk=item.fact_risk,
                fact_note=item.fact_note,
                job_id=job.id,
            )
            session.add(row)
            rows.append(row)
        await session.flush()
        if project.category_id is None and data.suggested_category:
            suggested = (
                await session.execute(
                    select(Category).where(Category.slug == data.suggested_category)
                )
            ).scalar_one_or_none()
            if suggested is not None:
                project.category_id = suggested.id
                project.category_source = "suggested"
        session.add(
            UsageRecord(
                job_id=job.id,
                project_id=project.id,
                provider_id=result.provider.id,
                model=result.model,
                capability="llm",
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                succeeded=True,
            )
        )
        job_row = await session.get(GenerationJob, job.id)
        if job_row is not None:
            job_row.prompt_version_id = result.prompt_version_id
            job_row.provider_id = result.provider.id
            job_row.model = result.model
        await session.commit()
        await ctx.progress(100, "Ide selesai")
        return {
            "batch": batch,
            "idea_ids": [row.id for row in rows],
            "llm_raw": {
                "prompt": result.prompt_text[:20000],
                "raw": result.raw_text[:20000],
            },
        }
