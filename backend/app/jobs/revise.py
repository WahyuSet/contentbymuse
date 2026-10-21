import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import ContentIdea, Project, Script, ValidationResult
from app.domain.llm_outputs import ScriptDraft
from app.domain.script_rules import validate_script_draft
from app.jobs.context import DbCallContext
from app.jobs.script_chain import (
    ScriptInputError,
    checks_for,
    draft_payload,
    issues_payload,
    llm_pairs,
    load_scenes,
    queue_checks_or_validate,
    record_usage,
    save_draft,
    script_inputs,
)
from app.services.prompts import PromptService
from app.services.structured_llm import StructuredLLM


async def run_revise(job, factory: async_sessionmaker) -> dict:
    ctx = DbCallContext(job.id, factory)
    script_id = (job.input or {}).get("script_id")
    validation_id = (job.input or {}).get("validation_id")
    async with factory() as session:
        existing = (
            await session.execute(
                select(Script).where(Script.job_id == job.id, Script.source == "revised")
            )
        ).scalar_one_or_none()
        if existing is not None:
            project = await session.get(Project, existing.project_id)
            await queue_checks_or_validate(session, project=project, script=existing)
            await session.commit()
            return {"script_id": existing.id, "version": existing.version, "reused": True}
        script = await session.get(Script, script_id) if script_id else None
        if script is None:
            raise ScriptInputError("Script untuk job revise tidak ditemukan.")
        validation = (
            await session.get(ValidationResult, validation_id) if validation_id else None
        )
        if validation is None:
            raise ScriptInputError("Hasil validasi untuk revisi tidak ditemukan.")
        project = await session.get(Project, script.project_id)
        scenes = await load_scenes(session, script.id)
        checks = await checks_for(session, project, script)
        idea = (
            await session.get(ContentIdea, script.idea_id)
            if script.idea_id
            else await session.get(ContentIdea, project.selected_idea_id)
        )
        if idea is None:
            raise ScriptInputError("Ide asal script tidak ditemukan.")
        inputs = await script_inputs(session, project, idea)
        inputs["draft"] = json.dumps(draft_payload(script, scenes), ensure_ascii=False)
        inputs["validation"] = json.dumps(
            {
                "status": validation.status,
                "score": validation.score,
                "summary": validation.summary,
                "issues": validation.issues,
                "claims_to_verify": validation.claims_to_verify,
            },
            ensure_ascii=False,
        )
        inputs["checks"] = json.dumps(issues_payload(checks), ensure_ascii=False)
        pairs = await llm_pairs(session)
        prompts = PromptService(session)
    await ctx.progress(30, "Merevisi script mengikuti catatan validator")
    result = await StructuredLLM(pairs, prompts).generate(
        task="script.revise",
        inputs=inputs,
        output_model=ScriptDraft,
        ctx=ctx,
        validate=validate_script_draft,
    )
    async with factory() as session:
        project = await session.get(Project, job.project_id)
        revised = await save_draft(
            session,
            project=project,
            idea_id=script.idea_id,
            draft=result.data,
            source="revised",
            parent_id=script.id,
            job=job,
            prompt_version_id=result.prompt_version_id,
        )
        await record_usage(session, job=job, project=project, result=result)
        await queue_checks_or_validate(session, project=project, script=revised)
        await session.commit()
        revised_id, version = revised.id, revised.version
    await ctx.progress(100, "Revisi selesai")
    return {"script_id": revised_id, "version": version}
