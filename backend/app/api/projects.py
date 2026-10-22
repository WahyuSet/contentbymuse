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
    active_script_id: str | None = None
    voice_provider_id: str | None = None
    voice_id: str | None = None
    voice_settings: dict[str, Any] = {}
    image_provider_id: str | None = None
    visual_style_id: str | None = None
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
    voice_provider_id: str | None = None
    voice_id: str | None = None
    voice_settings: dict[str, Any] | None = None
    image_provider_id: str | None = None
    visual_style_id: str | None = None


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


async def _check_voice_provider(session: AsyncSession, provider_id: str | None) -> None:
    if provider_id is None:
        return
    from app.db.models import Provider

    provider = await session.get(Provider, provider_id)
    if provider is None or provider.capability != "voice":
        raise AppError(422, "InvalidProvider", "Provider suara tidak ditemukan.")


async def _check_image_provider(session: AsyncSession, provider_id: str | None) -> None:
    if provider_id is None:
        return
    from app.db.models import Provider

    provider = await session.get(Provider, provider_id)
    if provider is None or provider.capability != "image":
        raise AppError(422, "InvalidProvider", "Provider gambar tidak ditemukan.")


async def _check_visual_style(session: AsyncSession, style_id: str | None) -> None:
    if style_id is None:
        return
    from app.db.models import VisualStyle

    style = await session.get(VisualStyle, style_id)
    if style is None:
        raise AppError(422, "InvalidVisualStyle", "Gaya visual tidak ditemukan.")


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
                  "target_min_s", "target_max_s", "voice_id"):
        if field in data:
            setattr(project, field, data[field])
    if "category_id" in data and data["category_id"] is None:
        project.category_source = None
    if "voice_provider_id" in data:
        await _check_voice_provider(session, data["voice_provider_id"])
        project.voice_provider_id = data["voice_provider_id"]
    if "image_provider_id" in data:
        await _check_image_provider(session, data["image_provider_id"])
        project.image_provider_id = data["image_provider_id"]
    if "visual_style_id" in data:
        await _check_visual_style(session, data["visual_style_id"])
        project.visual_style_id = data["visual_style_id"]
    if "settings" in data and data["settings"] is not None:
        merged = dict(project.settings or {})
        merged.update(data["settings"])
        project.settings = merged
    if "voice_settings" in data and data["voice_settings"] is not None:
        merged_voice = dict(project.voice_settings or {})
        merged_voice.update(data["voice_settings"])
        project.voice_settings = merged_voice
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


class RenderRequest(BaseModel):
    force: bool = False


class RenderOut(BaseModel):
    version: int
    duration_s: float | None
    encoder: str | None
    warnings: list[str] = []
    files: dict[str, str] = {}
    created_at: datetime


@router.get("/projects/{project_id}/render", response_model=RenderOut | None)
async def get_render(project_id: str, session: SessionDep):
    from app.db.models import Asset

    await _load_project(session, project_id)
    asset = (
        await session.execute(
            select(Asset).where(
                Asset.project_id == project_id,
                Asset.kind == "render",
                Asset.is_selected.is_(True),
            )
        )
    ).scalar_one_or_none()
    if asset is None:
        return None
    files = {
        name: f"/api/files/{key}"
        for name, key in (asset.data or {}).get("files", {}).items()
    }
    return RenderOut(
        version=asset.version,
        duration_s=asset.duration_s,
        encoder=(asset.data or {}).get("encoder"),
        warnings=(asset.data or {}).get("warnings", []),
        files=files,
        created_at=asset.created_at,
    )


@router.get("/projects/{project_id}/thumbnail")
async def get_thumbnail(project_id: str, session: SessionDep):
    from app.db.models import Asset

    asset = (
        await session.execute(
            select(Asset).where(
                Asset.project_id == project_id,
                Asset.kind == "thumbnail",
                Asset.is_selected.is_(True),
            )
        )
    ).scalar_one_or_none()
    if asset is None:
        return None
    return {
        "version": asset.version,
        "url": f"/api/files/{asset.storage_key}",
        "title_text": (asset.data or {}).get("title_text"),
    }


@router.get("/projects/{project_id}/metadata")
async def get_metadata(project_id: str, session: SessionDep):
    from app.db.models import Asset

    asset = (
        await session.execute(
            select(Asset).where(
                Asset.project_id == project_id,
                Asset.kind == "metadata",
                Asset.is_selected.is_(True),
            )
        )
    ).scalar_one_or_none()
    if asset is None:
        return None
    data = asset.data or {}
    return {
        "title": data.get("title"),
        "description": data.get("description"),
        "hashtags": data.get("hashtags"),
        "fb_caption": data.get("fb_caption"),
    }


class MetadataReviseIn(BaseModel):
    title: str
    description: str | None = None
    hashtags: list[str] | None = None
    fb_caption: str | None = None
    thumbnail_text: str | None = None


@router.post("/projects/{project_id}/metadata/revise")
async def revise_metadata(
    project_id: str, body: MetadataReviseIn, session: SessionDep
):
    """Timpa teks metadata terpilih (judul dkk.) — dipakai agen produksi untuk
    memperbaiki judul hasil generator menjadi hook yang kuat sebelum terbit.
    Manifest rekor yang belum naik (queued/awaiting) ikut diperbarui;
    render_id/script_id di data aset tidak disentuh."""
    import json as json_mod

    from app.config import get_settings
    from app.db.models import Asset, PublishRecord
    from app.storage.local import LocalStorage

    title = body.title.strip()
    if not title or len(title) > 100:
        raise AppError(
            422, "MetadataTitle", "Judul wajib 1–100 karakter."
        )
    thumb_text = None
    if body.thumbnail_text is not None:
        thumb_text = body.thumbnail_text.strip()
        if not thumb_text or len(thumb_text) > 60:
            raise AppError(
                422, "ThumbnailText", "Teks thumbnail wajib 1–60 karakter."
            )
    asset = (
        await session.execute(
            select(Asset).where(
                Asset.project_id == project_id,
                Asset.kind == "metadata",
                Asset.is_selected.is_(True),
            )
        )
    ).scalar_one_or_none()
    if asset is None:
        raise NotFoundError("Metadata terpilih tidak ditemukan.")
    data = dict(asset.data or {})
    data["title"] = title
    if body.description is not None:
        data["description"] = body.description
    if body.hashtags is not None:
        data["hashtags"] = body.hashtags
    if body.fb_caption is not None:
        data["fb_caption"] = body.fb_caption
    asset.data = data
    await session.commit()

    storage = LocalStorage(get_settings().storage_path)
    records = (
        await session.execute(
            select(PublishRecord).where(
                PublishRecord.project_id == project_id,
                PublishRecord.status.in_(("queued", "awaiting_upload")),
            )
        )
    ).scalars().all()
    touched = 0
    for record in records:
        path = await storage.local_path(f"publish/{record.id}/manifest.json")
        if not path.exists():
            continue
        try:
            manifest = json_mod.loads(path.read_text())
        except (OSError, json_mod.JSONDecodeError):
            continue
        manifest["title"] = data["title"]
        manifest["description"] = data.get("description")
        manifest["hashtags"] = data.get("hashtags")
        manifest["fb_caption"] = data.get("fb_caption")
        path.write_text(json_mod.dumps(manifest, indent=2))
        touched += 1

    thumbnail_updated = False
    if thumb_text is not None:
        # Komposit ulang teks thumbnail dari gambar mentah (tanpa teks) milik
        # aset thumbnail terpilih; berkas tujuan sama agar manifest tetap sah.
        thumb = (
            await session.execute(
                select(Asset).where(
                    Asset.project_id == project_id,
                    Asset.kind == "thumbnail",
                    Asset.is_selected.is_(True),
                )
            )
        ).scalar_one_or_none()
        if thumb is not None:
            tdata = dict(thumb.data or {})
            raw_key = tdata.get("raw_key")
            if raw_key:
                raw_path = await storage.local_path(raw_key)
                if raw_path.exists():
                    from app.services.thumbnail_text import draw_title_text

                    final_path = await storage.local_path(thumb.storage_key)
                    final_path.write_bytes(
                        draw_title_text(raw_path.read_bytes(), thumb_text)
                    )
                    tdata["title_text"] = thumb_text.upper()
                    thumb.data = tdata
                    await session.commit()
                    thumbnail_updated = True
    return {
        "title": data["title"],
        "description": data.get("description"),
        "hashtags": data.get("hashtags"),
        "fb_caption": data.get("fb_caption"),
        "manifests_updated": touched,
        "thumbnail_updated": thumbnail_updated,
    }


@router.post("/projects/{project_id}/render", status_code=202)
async def request_render(
    project_id: str, body: RenderRequest, session: SessionDep
):
    from app.db.models import Asset, Script
    from app.jobs.render import render_hash_parts
    from app.services import assets as asset_service
    from app.services.render_settings import get_subtitle_style

    project = await _load_project(session, project_id)
    script = (
        await session.get(Script, project.active_script_id)
        if project.active_script_id
        else None
    )
    if script is None or script.status != "approved":
        raise AppError(
            409,
            "ScriptNotApproved",
            "Render hanya dibuat untuk script yang sudah disetujui.",
        )
    style = await get_subtitle_style(session)
    parts, per_scene = await render_hash_parts(session, project, script, style)
    missing = []
    for scene, voice, image, _t in per_scene:
        if voice is None:
            missing.append(f"scene {scene.position} belum punya suara")
        if image is None:
            missing.append(f"scene {scene.position} belum punya gambar")
    if missing:
        raise AppError(
            409,
            "RenderNotReady",
            "Render belum siap: " + "; ".join(missing) + ".",
        )
    active = (
        await session.execute(
            select(GenerationJob).where(
                GenerationJob.project_id == project.id,
                GenerationJob.type == "render",
                GenerationJob.status.in_(("queued", "processing")),
            )
        )
    ).scalars().first()
    if active is not None:
        return {"job": JobOut.model_validate(active), "created": False}
    digest = asset_service.render_input_hash(parts)
    current = (
        await session.execute(
            select(Asset).where(
                Asset.project_id == project.id,
                Asset.kind == "render",
                Asset.is_selected.is_(True),
            )
        )
    ).scalar_one_or_none()
    if current is not None and current.input_hash == digest and not body.force:
        raise AppError(
            409,
            "RenderUpToDate",
            "Video sudah sesuai keadaan terbaru; pakai force untuk membuat ulang.",
        )
    from sqlalchemy.exc import IntegrityError

    try:
        async with session.begin_nested():
            job = await queue.enqueue(
                session,
                type="render",
                input={"force": body.force},
                project_id=project.id,
                resource_key="render",
            )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        active = (
            await session.execute(
                select(GenerationJob).where(
                    GenerationJob.project_id == project.id,
                    GenerationJob.type == "render",
                    GenerationJob.status.in_(("queued", "processing")),
                )
            )
        ).scalars().first()
        if active is None:
            raise
        return {"job": JobOut.model_validate(active), "created": False}
    await session.refresh(job)
    return {"job": JobOut.model_validate(job), "created": True}
