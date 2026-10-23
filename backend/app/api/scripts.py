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
    keyword_text: str | None = None
    sfx_cues: list
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
    if not scenes or any(
        not s.voiceover.strip() or not s.visual_prompt.strip() for s in scenes
    ):
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


BEATS = {"hook", "setup", "main", "impact", "payoff", "cta", "loop"}
VISUAL_TYPES = {"character", "object", "process", "environment", "diagram", "closeup"}
TRANSITIONS = {"cut", "crossfade", "punch_in"}


class ScenePatch(BaseModel):
    voiceover: str | None = None
    subtitle_override: str | None = None
    visual_prompt: str | None = None
    include_mascot: bool | None = None
    visual_type: str | None = None
    transition: str | None = None
    beat: str | None = None
    emphasis_words: list[str] | None = None
    keyword_text: str | None = None
    sfx_cues: list[dict] | None = None


class SceneCreate(BaseModel):
    voiceover: str
    visual_prompt: str
    beat: str = "main"
    subtitle_override: str | None = None
    include_mascot: bool = True
    visual_type: str = "character"
    transition: str = "cut"
    emphasis_words: list[str] = []
    keyword_text: str | None = None
    sfx_cues: list[dict] = []
    after_position: int | None = None


class ReorderIn(BaseModel):
    scene_ids: list[str]


class ScenePatchOut(BaseModel):
    scene: SceneOut
    checks: list[CheckIssueOut]


def _validate_scene_enums(data: dict) -> None:
    checks = (
        ("beat", BEATS, "Beat tidak dikenal."),
        ("visual_type", VISUAL_TYPES, "Jenis visual tidak dikenal."),
        ("transition", TRANSITIONS, "Transisi tidak dikenal."),
    )
    for field, allowed, message in checks:
        if field in data and data[field] is not None and data[field] not in allowed:
            raise AppError(422, "InvalidScene", f"{message} (field {field})")


async def _editable_guard(session: AsyncSession, script: Script) -> Project:
    project = await session.get(Project, script.project_id)
    if project is None or project.active_script_id != script.id:
        raise AppError(
            409, "ScriptNotActive", "Hanya versi script aktif yang bisa diedit."
        )
    busy = (
        await session.execute(
            select(GenerationJob).where(
                GenerationJob.project_id == script.project_id,
                GenerationJob.type.in_(CHAIN_JOB_TYPES),
                GenerationJob.status.in_(("queued", "processing")),
            )
        )
    ).scalars().first()
    if busy is not None:
        raise AppError(
            409, "ScriptBusy", "Tunggu job script selesai dulu sebelum mengedit."
        )
    return project


async def _renumber(session: AsyncSession, scenes: list) -> None:
    # Dua tahap agar constraint unik (script_id, position) tidak tabrakan di tengah flush.
    for scene in scenes:
        scene.position = -scene.position
    await session.flush()
    for index, scene in enumerate(scenes, start=1):
        scene.position = index
    await session.flush()


async def _recount(
    session: AsyncSession, script: Script, scenes: list, project: Project
) -> None:
    from app.domain.script_rules import estimate_scene_s
    from app.jobs.script_chain import calibrated_wps

    wps = await calibrated_wps(session, project)
    total = 0.0
    for scene in scenes:
        scene.est_duration_s = estimate_scene_s(scene.voiceover, wps)
        total += scene.est_duration_s
    script.estimated_duration_s = total
    script.hook = scenes[0].voiceover if scenes else ""
    await session.flush()


def _checks_out(issues) -> list[CheckIssueOut]:
    return [
        CheckIssueOut(
            code=issue.code,
            severity=issue.severity,
            scene_position=issue.scene_position,
            message=issue.message,
        )
        for issue in issues
    ]


def _validate_sfx_cues(data: dict, voiceover: str) -> None:
    from app.services import sfx_catalog

    cues = data.get("sfx_cues")
    if cues is None:
        return
    cleaned = sfx_catalog.sanitize_sfx_cues(cues, voiceover)
    if len(cleaned) != len(cues):
        raise AppError(
            422,
            "InvalidSfx",
            "Cue SFX tidak sah: id harus dari katalog dan kata pemicu harus "
            "ada di narasi (maksimal 2 per scene).",
        )
    data["sfx_cues"] = cleaned


@router.patch("/scenes/{scene_id}", response_model=ScenePatchOut)
async def patch_scene(scene_id: str, body: ScenePatch, session: SessionDep):
    from app.db.models import Scene

    scene = await session.get(Scene, scene_id)
    if scene is None:
        raise NotFoundError("Scene tidak ditemukan.")
    script = await _load_script(session, scene.script_id)
    project = await _editable_guard(session, script)
    data = body.model_dump(exclude_unset=True)
    _validate_scene_enums(data)
    # Cue divalidasi terhadap narasi SESUDAH patch bila voiceover ikut berubah.
    _validate_sfx_cues(data, data.get("voiceover", scene.voiceover))
    for field, value in data.items():
        setattr(scene, field, value)
    scene.revision += 1
    if script.status in ("validated", "approved"):
        script.edited_after_validation = True
    scenes = await load_scenes(session, script.id)
    await _recount(session, script, scenes, project)
    await session.commit()
    await session.refresh(scene)
    issues = await checks_for(session, project, script)
    return ScenePatchOut(scene=SceneOut.model_validate(scene), checks=_checks_out(issues))


@router.post("/scripts/{script_id}/scenes", status_code=201, response_model=SceneOut)
async def create_scene(script_id: str, body: SceneCreate, session: SessionDep):
    from app.db.models import Scene
    from app.domain.script_rules import estimate_scene_s
    from app.jobs.script_chain import WPS_DEFAULT

    script = await _load_script(session, script_id)
    project = await _editable_guard(session, script)
    data = body.model_dump()
    _validate_scene_enums(data)
    _validate_sfx_cues(data, body.voiceover)
    scenes = await load_scenes(session, script.id)
    insert_at = (
        body.after_position if body.after_position is not None else len(scenes)
    )
    insert_at = max(0, min(insert_at, len(scenes)))
    scene = Scene(
        script_id=script.id,
        position=len(scenes) + 1000,
        beat=body.beat,
        voiceover=body.voiceover,
        subtitle_override=body.subtitle_override,
        visual_prompt=body.visual_prompt,
        include_mascot=body.include_mascot,
        visual_type=body.visual_type,
        transition=body.transition,
        emphasis_words=body.emphasis_words,
        keyword_text=body.keyword_text,
        sfx_cues=data.get("sfx_cues") or [],
        est_duration_s=estimate_scene_s(body.voiceover, WPS_DEFAULT),
    )
    session.add(scene)
    await session.flush()
    ordered = scenes[:insert_at] + [scene] + scenes[insert_at:]
    await _renumber(session, ordered)
    if script.status in ("validated", "approved"):
        script.edited_after_validation = True
    await _recount(session, script, ordered, project)
    await session.commit()
    await session.refresh(scene)
    return SceneOut.model_validate(scene)


@router.delete("/scenes/{scene_id}")
async def delete_scene(scene_id: str, session: SessionDep):
    from app.db.models import Scene

    scene = await session.get(Scene, scene_id)
    if scene is None:
        raise NotFoundError("Scene tidak ditemukan.")
    script = await _load_script(session, scene.script_id)
    project = await _editable_guard(session, script)
    await session.delete(scene)
    await session.flush()
    scenes = await load_scenes(session, script.id)
    await _renumber(session, scenes)
    if script.status in ("validated", "approved"):
        script.edited_after_validation = True
    await _recount(session, script, scenes, project)
    await session.commit()
    return {"deleted": scene_id}


@router.post("/scripts/{script_id}/scenes/reorder", response_model=ScriptDetailOut)
async def reorder_scenes(script_id: str, body: ReorderIn, session: SessionDep):
    script = await _load_script(session, script_id)
    project = await _editable_guard(session, script)
    scenes = await load_scenes(session, script.id)
    by_id = {scene.id: scene for scene in scenes}
    if len(body.scene_ids) != len(scenes) or set(body.scene_ids) != set(by_id):
        raise AppError(
            422,
            "InvalidSceneOrder",
            "Urutan harus memuat tepat semua scene milik script ini.",
        )
    ordered = [by_id[scene_id] for scene_id in body.scene_ids]
    await _renumber(session, ordered)
    if script.status in ("validated", "approved"):
        script.edited_after_validation = True
    await _recount(session, script, ordered, project)
    await session.commit()
    await session.refresh(script)
    return await script_detail(session, script)
