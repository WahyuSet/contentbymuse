import dataclasses

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import ContentIdea, Format, Project, Scene, Script, UsageRecord
from app.domain.llm_outputs import ScriptDraft
from app.domain.script_rules import estimate_scene_s, run_checks
from app.jobs.ideas import NoLlmProviderError, _catalog_input
from app.providers.router import ProviderRouter
from app.services import sfx_catalog

WPS_DEFAULT = 2.3


class ScriptInputError(Exception):
    kind = "ScriptInputMissing"
    retryable = False


async def load_project_and_idea(session: AsyncSession, job) -> tuple[Project, ContentIdea]:
    project = await session.get(Project, job.project_id) if job.project_id else None
    if project is None:
        raise ScriptInputError("Project untuk job script tidak ditemukan.")
    idea_id = (job.input or {}).get("idea_id") or project.selected_idea_id
    idea = await session.get(ContentIdea, idea_id) if idea_id else None
    if idea is None:
        raise ScriptInputError("Pilih ide dulu sebelum membuat script.")
    return project, idea


async def script_inputs(session: AsyncSession, project: Project, idea: ContentIdea) -> dict:
    from app.db.models import Category

    category = (
        await session.get(Category, project.category_id) if project.category_id else None
    )
    fmt = await session.get(Format, project.format_id) if project.format_id else None
    return {
        "idea": {"title": idea.title, "angle": idea.angle, "hook": idea.hook},
        "category": await _catalog_input(session, category, "category"),
        "format": await _catalog_input(session, fmt, "format"),
        "language": project.language,
        "target_min_s": project.target_min_s,
        "target_max_s": project.target_max_s,
    }


async def llm_pairs(session: AsyncSession):
    router = ProviderRouter(session)
    settings = get_settings()
    pairs = []
    for provider in await router.candidates("llm"):
        pairs.append((provider, await router.build_llm(provider, settings)))
    if not pairs:
        raise NoLlmProviderError()
    return pairs


async def load_scenes(session: AsyncSession, script_id: str) -> list[Scene]:
    stmt = select(Scene).where(Scene.script_id == script_id).order_by(Scene.position)
    return list((await session.execute(stmt)).scalars())


async def save_draft(
    session: AsyncSession,
    *,
    project: Project,
    idea_id: str | None,
    draft: ScriptDraft,
    source: str,
    parent_id: str | None,
    job,
    prompt_version_id: str | None,
) -> Script:
    version = (
        await session.execute(
            select(func.max(Script.version)).where(Script.project_id == project.id)
        )
    ).scalar_one_or_none() or 0
    script = Script(
        project_id=project.id,
        idea_id=idea_id,
        version=version + 1,
        parent_id=parent_id,
        source=source,
        title=draft.title,
        hook=draft.hook,
        claims_to_verify=list(draft.claims_to_verify),
        prompt_version_id=prompt_version_id,
        job_id=job.id,
    )
    session.add(script)
    await session.flush()
    wps = await calibrated_wps(session, project)
    total = 0.0
    for position, scene in enumerate(draft.scenes, start=1):
        est = estimate_scene_s(scene.voiceover, wps)
        total += est
        session.add(
            Scene(
                script_id=script.id,
                position=position,
                beat=scene.beat,
                voiceover=scene.voiceover,
                subtitle_override=scene.subtitle,
                visual_prompt=scene.visual_prompt,
                include_mascot=scene.include_mascot,
                visual_type=scene.visual_type,
                transition=scene.transition,
                emphasis_words=list(scene.emphasis_words),
                sfx_cues=sfx_catalog.sanitize_sfx_cues(
                    [cue.model_dump() for cue in scene.sfx_cues], scene.voiceover
                ),
                est_duration_s=est,
            )
        )
    script.estimated_duration_s = total
    await session.flush()
    return script


def draft_payload(script: Script, scenes: list[Scene]) -> dict:
    return {
        "title": script.title,
        "hook": script.hook,
        "claims_to_verify": script.claims_to_verify,
        "scenes": [
            {
                "position": s.position,
                "beat": s.beat,
                "voiceover": s.voiceover,
                "subtitle": s.subtitle_override,
                "visual_prompt": s.visual_prompt,
                "include_mascot": s.include_mascot,
                "visual_type": s.visual_type,
                "transition": s.transition,
                "emphasis_words": s.emphasis_words,
            }
            for s in scenes
        ],
    }


def issues_payload(issues) -> list[dict]:
    return [dataclasses.asdict(issue) for issue in issues]


async def calibrated_wps(session: AsyncSession, project: Project) -> float:
    """wps dari kalibrasi suara project (Spec §4.3); belum ada sampel -> bawaan."""
    from app.db.models import VoiceCalibration
    from app.providers.router import ProviderRouter

    expected = await ProviderRouter(session).expected_voice(project)
    if expected is None:
        return WPS_DEFAULT
    provider, voice_id = expected
    row = await session.get(VoiceCalibration, (provider.id, voice_id))
    if row is None or row.samples == 0:
        return WPS_DEFAULT
    return row.words_per_second


async def checks_for(session: AsyncSession, project: Project, script: Script) -> list:
    scenes = await load_scenes(session, script.id)
    fmt = await session.get(Format, project.format_id) if project.format_id else None
    return run_checks(
        scenes,
        wps=await calibrated_wps(session, project),
        target_min_s=project.target_min_s,
        target_max_s=project.target_max_s,
        format_slug=fmt.slug if fmt else None,
    )


async def queue_checks_or_validate(
    session: AsyncSession, *, project: Project, script: Script, after_fix: bool = False
):
    from app.jobs.queue import enqueue_once

    issues = await checks_for(session, project, script)
    has_errors = any(issue.severity == "error" for issue in issues)
    if has_errors and not after_fix:
        job, _ = await enqueue_once(
            session,
            type="checks_fix",
            input={"script_id": script.id},
            project_id=project.id,
        )
        return job
    job, _ = await enqueue_once(
        session,
        type="validate",
        input={"script_id": script.id, "auto_revise": True},
        project_id=project.id,
    )
    return job


async def record_usage(session: AsyncSession, *, job, project: Project, result) -> None:
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
    from app.db.models import GenerationJob

    job_row = await session.get(GenerationJob, job.id)
    if job_row is not None:
        job_row.prompt_version_id = result.prompt_version_id
        job_row.provider_id = result.provider.id
        job_row.model = result.model
