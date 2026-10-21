import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Project, Provider, Script, ValidationResult
from app.domain.llm_outputs import ValidationOutput
from app.domain.script_rules import apply_validation_rules, count_words
from app.jobs.context import DbCallContext
from app.jobs.queue import enqueue_once
from app.jobs.script_chain import (
    ScriptInputError,
    checks_for,
    issues_payload,
    llm_pairs,
    load_scenes,
    record_usage,
)
from app.services.prompts import PromptService
from app.services.settings import get_setting
from app.services.structured_llm import StructuredLLM


async def build_validation_pairs(session: AsyncSession):
    pairs = await llm_pairs(session)
    preferred_id = await get_setting(session, "validation_provider_id")
    if preferred_id:
        provider = await session.get(Provider, preferred_id)
        if provider is not None and provider.enabled and provider.capability == "llm":
            from app.config import get_settings
            from app.providers.router import ProviderRouter

            preferred = await ProviderRouter(session).build_llm(provider, get_settings())
            pairs = [(provider, preferred)] + [
                pair for pair in pairs if pair[0].id != provider.id
            ]
    return pairs


def validation_payload(script: Script, scenes) -> dict:
    total_words = sum(count_words(s.voiceover) for s in scenes)
    return {
        "title": script.title,
        "hook": script.hook,
        "estimated_total_s": script.estimated_duration_s,
        "total_words": total_words,
        "scenes": [
            {
                "position": s.position,
                "beat": s.beat,
                "voiceover": s.voiceover,
                "words": count_words(s.voiceover),
                "est_seconds": s.est_duration_s,
                "visual_type": s.visual_type,
                "include_mascot": s.include_mascot,
            }
            for s in scenes
        ],
    }


async def _apply_decision(
    session: AsyncSession,
    *,
    project: Project,
    script: Script,
    status: str,
    validation_id: str,
    auto_revise: bool,
) -> None:
    from app.services.finalize import finalize_best

    if status == "PASS":
        script.status = "validated"
        if auto_revise:
            await finalize_best(session, project)
        return
    if status == "NEEDS_REVISION" and auto_revise:
        max_revisions = int((project.settings or {}).get("max_revisions", 2))
        revised_count = (
            await session.execute(
                select(func.count(Script.id)).where(
                    Script.project_id == project.id,
                    Script.idea_id == script.idea_id,
                    Script.source == "revised",
                )
            )
        ).scalar_one()
        if revised_count < max_revisions:
            await enqueue_once(
                session,
                type="revise",
                input={"script_id": script.id, "validation_id": validation_id},
                project_id=project.id,
            )
            return
    script.status = "needs_attention"
    if auto_revise:
        await finalize_best(session, project)


async def run_validate(job, factory: async_sessionmaker) -> dict:
    ctx = DbCallContext(job.id, factory)
    script_id = (job.input or {}).get("script_id")
    auto_revise = bool((job.input or {}).get("auto_revise", False))
    async with factory() as session:
        existing = (
            await session.execute(
                select(ValidationResult).where(ValidationResult.job_id == job.id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            script = await session.get(Script, existing.script_id)
            project = await session.get(Project, script.project_id)
            await _apply_decision(
                session,
                project=project,
                script=script,
                status=existing.status,
                validation_id=existing.id,
                auto_revise=auto_revise,
            )
            await session.commit()
            await ctx.log("info", "Hasil validasi dari job ini sudah ada, dipakai ulang")
            return {"script_id": script.id, "status": existing.status, "reused": True}
        script = await session.get(Script, script_id) if script_id else None
        if script is None:
            raise ScriptInputError("Script untuk job validate tidak ditemukan.")
        project = await session.get(Project, script.project_id)
        scenes = await load_scenes(session, script.id)
        checks = await checks_for(session, project, script)
        inputs = {
            "script": json.dumps(validation_payload(script, scenes), ensure_ascii=False),
            "checks": json.dumps(issues_payload(checks), ensure_ascii=False),
        }
        pairs = await build_validation_pairs(session)
        prompts = PromptService(session)
    await ctx.progress(30, "Memvalidasi script")
    result = await StructuredLLM(pairs, prompts).generate(
        task="validate.script",
        inputs=inputs,
        output_model=ValidationOutput,
        ctx=ctx,
        validate=apply_validation_rules,
    )
    data: ValidationOutput = result.data
    async with factory() as session:
        script = await session.get(Script, script_id)
        project = await session.get(Project, script.project_id)
        attempt = (
            await session.execute(
                select(func.count(ValidationResult.id)).where(
                    ValidationResult.script_id == script.id
                )
            )
        ).scalar_one()
        record = ValidationResult(
            script_id=script.id,
            attempt=attempt + 1,
            status=data.status,
            score=data.score,
            issues=[issue.model_dump() for issue in data.issues],
            claims_to_verify=list(data.claims_to_verify),
            summary=data.summary,
            prompt_version_id=result.prompt_version_id,
            job_id=job.id,
        )
        session.add(record)
        script.best_score = data.score
        await session.flush()
        await record_usage(session, job=job, project=project, result=result)
        await _apply_decision(
            session,
            project=project,
            script=script,
            status=data.status,
            validation_id=record.id,
            auto_revise=auto_revise,
        )
        await session.commit()
    await ctx.progress(100, "Validasi selesai")
    return {"script_id": script_id, "status": data.status, "score": data.score}
