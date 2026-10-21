from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError, NotFoundError
from app.api.jobs import FactoryDep, JobOut, SessionDep
from app.db.models import GenerationJob, Project, Script, ValidationResult
from app.jobs import queue
from app.jobs.queue import enqueue_once
from app.jobs.script_chain import checks_for, load_scenes
from app.services.reconcile import reconcile

router = APIRouter(prefix="/api", tags=["scripts"])

CHAIN_JOB_TYPES = ("script", "checks_fix", "validate", "revise")


class ScriptSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    idea_id: str | None
    version: int
    parent_id: str | None
    source: str
    status: str
    title: str
    hook: str
    estimated_duration_s: float
    best_score: int | None
    edited_after_validation: bool
    created_at: datetime
    updated_at: datetime


class SceneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    script_id: str
    position: int
    beat: str
    voiceover: str
    subtitle_override: str | None
    visual_prompt: str
    include_mascot: bool
    visual_type: str
    transition: str
    emphasis_words: list
    est_duration_s: float
    revision: int


class CheckIssueOut(BaseModel):
    code: str
    severity: str
    scene_position: int | None
    message: str


class ValidationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    attempt: int
    status: str
    score: int
    summary: str
    issues: list
    claims_to_verify: list
    created_at: datetime


class ScriptDetailOut(ScriptSummaryOut):
    scenes: list[SceneOut] = []
    checks: list[CheckIssueOut] = []
    validation: ValidationOut | None = None
    claims: list[str] = []


class JobCreatedOut(BaseModel):
    job: JobOut
    created: bool


class ValidateIn(BaseModel):
    auto_revise: bool = False


class ApproveIn(BaseModel):
    claims_confirmed: bool = False


def _tokens(text: str) -> set[str]:
    return {t.strip(".,!?").lower() for t in text.split() if t.strip(".,!?")}


def merge_claims(script_claims: list[str], validation_claims: list[str]) -> list[str]:
    """Klaim gabungan Gerbang B (Spec §4.5): kemiripan token >= 0,7 = klaim sama,
    rumusan hasil validasi menggantikan di posisi klaim lama."""
    merged = list(script_claims)
    token_sets = [_tokens(claim) for claim in merged]
    for claim in validation_claims:
        tokens = _tokens(claim)
        replaced = False
        for index, existing in enumerate(token_sets):
            union = tokens | existing
            if union and len(tokens & existing) / len(union) >= 0.7:
                merged[index] = claim
                token_sets[index] = tokens
                replaced = True
                break
        if not replaced:
            merged.append(claim)
            token_sets.append(tokens)
    return merged


async def _load_script(session: AsyncSession, script_id: str) -> Script:
    script = await session.get(Script, script_id)
    if script is None:
        raise NotFoundError("Script tidak ditemukan.")
    return script


async def _latest_validation(
    session: AsyncSession, script_id: str
) -> ValidationResult | None:
    stmt = (
        select(ValidationResult)
        .where(ValidationResult.script_id == script_id)
        .order_by(ValidationResult.attempt.desc())
    )
    return (await session.execute(stmt)).scalars().first()


async def script_detail(session: AsyncSession, script: Script) -> ScriptDetailOut:
    project = await session.get(Project, script.project_id)
    scenes = await load_scenes(session, script.id)
    checks = await checks_for(session, project, script)
    validation = await _latest_validation(session, script.id)
    detail = ScriptDetailOut.model_validate(script)
    detail.scenes = [SceneOut.model_validate(scene) for scene in scenes]
    detail.checks = [
        CheckIssueOut(
            code=issue.code,
            severity=issue.severity,
            scene_position=issue.scene_position,
            message=issue.message,
        )
        for issue in checks
    ]
    detail.validation = (
        ValidationOut.model_validate(validation) if validation is not None else None
    )
    detail.claims = merge_claims(
        list(script.claims_to_verify or []),
        list(validation.claims_to_verify or []) if validation is not None else [],
    )
    return detail


@router.get("/projects/{project_id}/scripts", response_model=list[ScriptSummaryOut])
async def list_scripts(project_id: str, session: SessionDep):
    if await session.get(Project, project_id) is None:
        raise NotFoundError("Project tidak ditemukan.")
    stmt = (
        select(Script)
        .where(Script.project_id == project_id)
        .order_by(Script.version.desc())
    )
    return (await session.execute(stmt)).scalars().all()


@router.get("/scripts/{script_id}", response_model=ScriptDetailOut)
async def get_script(script_id: str, session: SessionDep):
    return await script_detail(session, await _load_script(session, script_id))


@router.post(
    "/projects/{project_id}/script/generate",
    status_code=202,
    response_model=JobCreatedOut,
)
async def generate_script(project_id: str, session: SessionDep):
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project tidak ditemukan.")
    if not project.selected_idea_id:
        raise AppError(
            422, "NoIdeaSelected", "Pilih ide dulu sebelum membuat script."
        )
    active = (
        await session.execute(
            select(GenerationJob).where(
                GenerationJob.project_id == project_id,
                GenerationJob.type == "script",
                GenerationJob.status.in_(("queued", "processing")),
            )
        )
    ).scalars().first()
    if active is not None:
        return JobCreatedOut(job=JobOut.model_validate(active), created=False)
    job = await queue.enqueue(
        session,
        type="script",
        input={"idea_id": project.selected_idea_id},
        project_id=project_id,
    )
    await session.commit()
    await session.refresh(job)
    return JobCreatedOut(job=JobOut.model_validate(job), created=True)


@router.post("/scripts/{script_id}/validate", status_code=202, response_model=JobCreatedOut)
async def validate_script(script_id: str, body: ValidateIn, session: SessionDep):
    script = await _load_script(session, script_id)
    job, created = await enqueue_once(
        session,
        type="validate",
        input={"script_id": script.id, "auto_revise": body.auto_revise},
        project_id=script.project_id,
    )
    await session.commit()
    await session.refresh(job)
    return JobCreatedOut(job=JobOut.model_validate(job), created=created)


@router.post("/scripts/{script_id}/approve", response_model=ScriptSummaryOut)
async def approve_script(
    script_id: str, body: ApproveIn, session: SessionDep, factory: FactoryDep
):
    script = await _load_script(session, script_id)
    if not body.claims_confirmed:
        raise AppError(
            422,
            "ClaimsNotConfirmed",
            "Semua klaim harus dicek dulu sebelum menyetujui.",
        )
    scenes = await load_scenes(session, script.id)
    if any(not s.voiceover.strip() or not s.visual_prompt.strip() for s in scenes):
        raise AppError(
            409, "EmptyScene", "Masih ada scene dengan narasi atau prompt visual kosong."
        )
    project = await session.get(Project, script.project_id)
    others = (
        await session.execute(
            select(Script).where(
                Script.project_id == script.project_id,
                Script.status == "approved",
                Script.id != script.id,
            )
        )
    ).scalars().all()
    for other in others:
        latest = await _latest_validation(session, other.id)
        other.status = (
            "validated" if latest is not None and latest.status == "PASS"
            else "needs_attention" if latest is not None
            else "draft"
        )
    script.status = "approved"
    if project is not None:
        project.active_script_id = script.id
    await session.commit()
    await session.refresh(script)
    if project is not None:
        await reconcile(project.id, factory)
    return ScriptSummaryOut.model_validate(script)


class PipelineStageOut(BaseModel):
    key: str
    label: str
    status: str
    detail: str
    job_id: str | None = None


class PipelineOut(BaseModel):
    project_id: str
    stages: list[PipelineStageOut]


@router.get("/projects/{project_id}/pipeline", response_model=PipelineOut)
async def get_pipeline(project_id: str, session: SessionDep):
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project tidak ditemukan.")
    scripts = (
        await session.execute(
            select(Script)
            .where(Script.project_id == project_id)
            .order_by(Script.version.desc())
        )
    ).scalars().all()
    active_jobs = (
        await session.execute(
            select(GenerationJob).where(
                GenerationJob.project_id == project_id,
                GenerationJob.status.in_(("queued", "processing")),
                GenerationJob.type.in_(CHAIN_JOB_TYPES),
            )
        )
    ).scalars().all()
    job_by_type = {}
    for job in active_jobs:
        job_by_type.setdefault(job.type, job)
    latest = scripts[0] if scripts else None
    active_script = next(
        (s for s in scripts if s.id == project.active_script_id), None
    )

    if not project.selected_idea_id:
        script_stage = PipelineStageOut(
            key="script", label="Script", status="blocked",
            detail="Pilih ide dulu di Gerbang A.",
        )
    elif "script" in job_by_type or "checks_fix" in job_by_type or "revise" in job_by_type:
        job = job_by_type.get("script") or job_by_type.get("checks_fix") or job_by_type.get("revise")
        script_stage = PipelineStageOut(
            key="script", label="Script", status="running",
            detail="Script sedang ditulis atau diperbaiki.", job_id=job.id,
        )
    elif active_script is not None and active_script.status in ("validated", "approved"):
        script_stage = PipelineStageOut(
            key="script", label="Script", status="done",
            detail=f"Versi {active_script.version} menjadi script aktif.",
        )
    elif latest is not None and latest.status == "needs_attention":
        script_stage = PipelineStageOut(
            key="script", label="Script", status="attention",
            detail="Versi terakhir perlu perhatian sebelum lanjut.",
        )
    elif latest is not None:
        script_stage = PipelineStageOut(
            key="script", label="Script", status="pending",
            detail=f"Versi {latest.version} menunggu validasi.",
        )
    else:
        script_stage = PipelineStageOut(
            key="script", label="Script", status="pending",
            detail="Belum ada script untuk ide terpilih.",
        )

    validation_target = active_script or latest
    if "validate" in job_by_type:
        validation_stage = PipelineStageOut(
            key="validation", label="Validasi", status="running",
            detail="Validator sedang memeriksa script.",
            job_id=job_by_type["validate"].id,
        )
    elif validation_target is not None:
        latest_val = await _latest_validation(session, validation_target.id)
        if latest_val is not None and latest_val.status == "PASS":
            validation_stage = PipelineStageOut(
                key="validation", label="Validasi", status="done",
                detail=f"Lulus dengan skor {latest_val.score}.",
            )
        elif latest_val is not None:
            validation_stage = PipelineStageOut(
                key="validation", label="Validasi", status="attention",
                detail=f"Hasil terakhir: {latest_val.status} (skor {latest_val.score}).",
            )
        else:
            validation_stage = PipelineStageOut(
                key="validation", label="Validasi", status="pending",
                detail="Script belum divalidasi.",
            )
    else:
        validation_stage = PipelineStageOut(
            key="validation", label="Validasi", status="blocked",
            detail="Menunggu script pertama.",
        )

    return PipelineOut(project_id=project_id, stages=[script_stage, validation_stage])
