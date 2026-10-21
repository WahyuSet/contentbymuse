from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import Script
from app.domain.llm_outputs import ScriptDraft
from app.domain.script_rules import validate_script_draft
from app.jobs.context import DbCallContext
from app.jobs.script_chain import (
    llm_pairs,
    load_project_and_idea,
    queue_checks_or_validate,
    record_usage,
    save_draft,
    script_inputs,
)
from app.services.prompts import PromptService
from app.services.structured_llm import StructuredLLM


async def run_script(job, factory: async_sessionmaker) -> dict:
    ctx = DbCallContext(job.id, factory)
    async with factory() as session:
        existing = (
            await session.execute(select(Script).where(Script.job_id == job.id))
        ).scalar_one_or_none()
        if existing is not None:
            from app.db.models import Project

            project = await session.get(Project, existing.project_id)
            await queue_checks_or_validate(session, project=project, script=existing)
            await session.commit()
            await ctx.log("info", "Versi script dari job ini sudah ada, dipakai ulang")
            return {"script_id": existing.id, "version": existing.version, "reused": True}
        project, idea = await load_project_and_idea(session, job)
        inputs = await script_inputs(session, project, idea)
        pairs = await llm_pairs(session)
        prompts = PromptService(session)
    await ctx.progress(30, "Menulis script dari ide terpilih")
    result = await StructuredLLM(pairs, prompts).generate(
        task="script.generate",
        inputs=inputs,
        output_model=ScriptDraft,
        ctx=ctx,
        validate=validate_script_draft,
    )
    async with factory() as session:
        project, idea = await load_project_and_idea(session, job)
        script = await save_draft(
            session,
            project=project,
            idea_id=idea.id,
            draft=result.data,
            source="generated",
            parent_id=None,
            job=job,
            prompt_version_id=result.prompt_version_id,
        )
        await record_usage(session, job=job, project=project, result=result)
        await queue_checks_or_validate(session, project=project, script=script)
        await session.commit()
        script_id, version = script.id, script.version
    await ctx.progress(100, "Script selesai ditulis")
    return {
        "script_id": script_id,
        "version": version,
        "llm_raw": {
            "prompt": result.prompt_text[:20000],
            "raw": result.raw_text[:20000],
        },
    }
