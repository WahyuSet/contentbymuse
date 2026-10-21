from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError, NotFoundError
from app.api.jobs import FactoryDep, JobOut, SessionDep
from app.db.models import Category, ContentIdea, Format, GenerationJob, Project
from app.jobs import queue
from app.services.reconcile import reconcile

router = APIRouter(prefix="/api", tags=["projects"])


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    topic: str | None
    category_id: str | None
    category_source: str | None
    format_id: str | None
    language: str
    target_min_s: int
    target_max_s: int
    selected_idea_id: str | None
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    idea_batches: int = 0
    idea_count: int = 0


class IdeaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    batch: int
    position: int
    title: str
    angle: str
    hook: str
    why_it_works: str
    suggested_category_slug: str | None
    fact_risk: str | None
    fact_note: str | None
    created_at: datetime


class IdeasGenerateOut(BaseModel):
    job: JobOut
    created: bool


class ProjectIn(BaseModel):
    title: str | None = None
    topic: str | None = None
    category_id: str | None = None
    format_id: str | None = None
    language: str | None = None


class ProjectPatch(BaseModel):
    title: str | None = None
    topic: str | None = None
    category_id: str | None = None
    format_id: str | None = None
    language: str | None = None
    target_min_s: int | None = None
    target_max_s: int | None = None
    settings: dict[str, Any] | None = None


async def project_out(session: AsyncSession, project: Project) -> ProjectOut:
    counts = (
        await session.execute(
            select(
                func.count(ContentIdea.id),
                func.count(func.distinct(ContentIdea.batch)),
            ).where(ContentIdea.project_id == project.id)
        )
    ).one()
    out = ProjectOut.model_validate(project)
    out.idea_count = counts[0] or 0
    out.idea_batches = counts[1] or 0
    return out


async def _load_project(session: AsyncSession, project_id: str) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project tidak ditemukan.")
    return project


async def _check_category(session: AsyncSession, category_id: str | None) -> Category | None:
    if category_id is None:
        return None
    category = await session.get(Category, category_id)
    if category is None:
        raise AppError(422, "InvalidCategory", "Kategori tidak ditemukan.")
    return category


async def _check_format(session: AsyncSession, format_id: str | None) -> Format | None:
    if format_id is None:
        return None
    fmt = await session.get(Format, format_id)
    if fmt is None:
        raise AppError(422, "InvalidFormat", "Format tidak ditemukan.")
    return fmt


@router.post("/projects", status_code=201, response_model=ProjectOut)
async def create_project(body: ProjectIn, session: SessionDep):
    topic = (body.topic or "").strip() or None
    if topic is None and not body.category_id:
        raise AppError(
            422,
            "ProjectNeedsTopicOrCategory",
            "Isi topik atau pilih kategori dulu.",
        )
    category = await _check_category(session, body.category_id)
    await _check_format(session, body.format_id)
    title = (body.title or "").strip() or topic or (category.name if category else "")
    project = Project(
        title=title,
        topic=topic,
        category_id=body.category_id,
        category_source="user" if body.category_id else None,
        format_id=body.format_id,
        language=body.language or "id-ID",
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return await project_out(session, project)


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(session: SessionDep):
    rows = (
        await session.execute(select(Project).order_by(Project.updated_at.desc()))
    ).scalars().all()
    return [await project_out(session, project) for project in rows]


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, session: SessionDep):
    return await project_out(session, await _load_project(session, project_id))


@router.patch("/projects/{project_id}", response_model=ProjectOut)
async def patch_project(project_id: str, body: ProjectPatch, session: SessionDep):
    project = await _load_project(session, project_id)
    data = body.model_dump(exclude_unset=True)
    new_topic = data.get("topic", project.topic)
    new_category_id = data.get("category_id", project.category_id)
    if not (new_topic and str(new_topic).strip()) and not new_category_id:
        raise AppError(
            422,
            "ProjectNeedsTopicOrCategory",
            "Project harus punya topik atau kategori.",
        )
    if "category_id" in data:
        await _check_category(session, data["category_id"])
        if data["category_id"]:
            project.category_source = "user"
    if "format_id" in data:
        await _check_format(session, data["format_id"])
    target_min = data.get("target_min_s", project.target_min_s)
    target_max = data.get("target_max_s", project.target_max_s)
    if target_min >= target_max:
        raise AppError(
            422,
            "InvalidProject",
            "Durasi target minimum harus lebih kecil dari maksimum.",
        )
    for field in ("title", "topic", "category_id", "format_id", "language",
                  "target_min_s", "target_max_s"):
        if field in data:
            setattr(project, field, data[field])
    if "category_id" in data and data["category_id"] is None:
        project.category_source = None
    if "settings" in data and data["settings"] is not None:
        merged = dict(project.settings or {})
        merged.update(data["settings"])
        project.settings = merged
    await session.commit()
    await session.refresh(project)
    return await project_out(session, project)


@router.post(
    "/projects/{project_id}/ideas/generate",
    status_code=202,
    response_model=IdeasGenerateOut,
)
async def generate_ideas(project_id: str, session: SessionDep):
    project = await _load_project(session, project_id)
    active = (
        await session.execute(
            select(GenerationJob)
            .where(
                GenerationJob.project_id == project.id,
                GenerationJob.type == "ideas",
                GenerationJob.status.in_(("queued", "processing")),
            )
            .order_by(GenerationJob.created_at.desc())
        )
    ).scalars().first()
    if active is not None:
        return IdeasGenerateOut(job=JobOut.model_validate(active), created=False)
    job = await queue.enqueue(session, type="ideas", input={}, project_id=project.id)
    await session.commit()
    await session.refresh(job)
    return IdeasGenerateOut(job=JobOut.model_validate(job), created=True)


@router.get("/projects/{project_id}/ideas", response_model=list[IdeaOut])
async def list_ideas(project_id: str, session: SessionDep):
    await _load_project(session, project_id)
    stmt = (
        select(ContentIdea)
        .where(ContentIdea.project_id == project_id)
        .order_by(ContentIdea.batch, ContentIdea.position)
    )
    return (await session.execute(stmt)).scalars().all()


@router.post("/ideas/{idea_id}/select", response_model=ProjectOut)
async def select_idea(
    idea_id: str,
    session: SessionDep,
    factory: FactoryDep,
):
    idea = await session.get(ContentIdea, idea_id)
    if idea is None:
        raise NotFoundError("Ide tidak ditemukan.")
    project = await _load_project(session, idea.project_id)
    project.selected_idea_id = idea.id
    project.title = idea.title
    await session.commit()
    await session.refresh(project)
    await reconcile(project.id, factory)
    return await project_out(session, project)
