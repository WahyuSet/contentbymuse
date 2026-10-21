import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import Project, Script
from app.domain.llm_outputs import ScriptDraft
from app.domain.script_rules import validate_script_draft
from app.jobs.context import DbCallContext
from app.jobs.queue import enqueue_once
from app.jobs.script_chain import (
    ScriptInputError,
    checks_for,
    draft_payload,
    issues_payload,
    llm_pairs,
    load_scenes,
    record_usage,
    save_draft,
    script_inputs,
)
from app.services.prompts import PromptService
from app.services.structured_llm import StructuredLLM


async def run_checks_fix(job, factory: async_sessionmaker) -> dict:
    ctx = DbCallContext(job.id, factory)
    script_id = (job.input or {}).get("script_id")
    async with factory() as session:
        existing = (
            await session.execute(
                select(Script).where(Script.job_id == job.id, Script.source == "fixed")
            )
        ).scalar_one_or_none()
        if existing is not None:
            project = await session.get(Project, existing.project_id)
            await enqueue_once(
                session,
                type="validate",
                input={"script_id": existing.id, "auto_revise": True},
                project_id=project.id,
            )
            await session.commit()
            return {"script_id": existing.id, "version": existing.version, "reused": True}
        script = await session.get(Script, script_id) if script_id else None
        if script is None:
            raise ScriptInputError("Script untuk job checks_fix tidak ditemukan.")
        project = await session.get(Project, script.project_id)
        scenes = await load_scenes(session, script.id)
        issues = await checks_for(session, project, script)
        from app.db.models import ContentIdea

        idea = (
            await session.get(ContentIdea, script.idea_id)
            if script.idea_id
            else await session.get(ContentIdea, project.selected_idea_id)
        )
        if idea is None:
            raise ScriptInputError("Ide asal script tidak ditemukan.")
        inputs = await script_inputs(session, project, idea)
        inputs["draft"] = json.dumps(draft_payload(script, scenes), ensure_ascii=False)
        inputs["issues"] = json.dumps(issues_payload(issues), ensure_ascii=False)
        pairs = await llm_pairs(session)
        prompts = PromptService(session)
    await ctx.progress(30, "Memperbaiki script mengikuti hasil cek")
    result = await StructuredLLM(pairs, prompts).generate(
        task="script.fix",
        inputs=inputs,
        output_model=ScriptDraft,
        ctx=ctx,
        validate=validate_script_draft,
    )
    async with factory() as session:
        project = await session.get(Project, job.project_id)
        fixed = await save_draft(
            session,
            project=project,
            idea_id=script.idea_id,
            draft=result.data,
            source="fixed",
            parent_id=script.id,
            job=job,
            prompt_version_id=result.prompt_version_id,
        )
        await record_usage(session, job=job, project=project, result=result)
        await enqueue_once(
            session,
            type="validate",
            input={"script_id": fixed.id, "auto_revise": True},
            project_id=project.id,
        )
        await session.commit()
        fixed_id, version = fixed.id, fixed.version
    await ctx.progress(100, "Perbaikan script selesai")
    return {"script_id": fixed_id, "version": version}
