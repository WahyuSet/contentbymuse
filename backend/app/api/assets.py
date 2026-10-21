from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.errors import AppError, NotFoundError
from app.api.jobs import JobOut, SessionDep
from app.config import get_settings
from app.db.models import Asset, GenerationJob, Project, Scene, Script
from app.jobs import queue
from app.providers.router import ProviderRouter
from app.storage.local import LocalStorage

router = APIRouter(prefix="/api", tags=["assets"])


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str | None
    scene_id: str | None
    kind: str
    version: int
    mime: str
    size_bytes: int
    duration_s: float | None
    data: dict | None
    input_hash: str
    provider_id: str | None
    model: str | None
    is_selected: bool
    created_at: datetime
    url: str = ""

    @classmethod
    def of(cls, asset: Asset) -> "AssetOut":
        out = cls.model_validate(asset)
        out.url = f"/api/files/{asset.storage_key}"
        return out


@router.get("/files/{key:path}")
async def get_file(key: str, session: SessionDep):
    settings = get_settings()
    storage = LocalStorage(settings.storage_path)
    try:
        path = await storage.local_path(key)
    except ValueError:
        raise NotFoundError("File tidak ditemukan.") from None
    if not path.exists():
        raise NotFoundError("File tidak ditemukan.")
    matches = (
        await session.execute(select(Asset).where(Asset.storage_key == key))
    ).scalars().all()
    # Baris word_timings berbagi storage_key klipnya; mime file adalah mime klip.
    asset = next((a for a in matches if a.kind != "word_timings"), None)
    media_type = asset.mime if asset else "application/octet-stream"
    return StreamingResponse(storage.open(key), media_type=media_type)


@router.get("/scenes/{scene_id}/assets", response_model=list[AssetOut])
async def list_scene_assets(scene_id: str, session: SessionDep):
    scene = await session.get(Scene, scene_id)
    if scene is None:
        raise NotFoundError("Scene tidak ditemukan.")
    rows = (
        await session.execute(
            select(Asset)
            .where(Asset.scene_id == scene_id)
            .order_by(Asset.kind, Asset.version.desc())
        )
    ).scalars().all()
    return [AssetOut.of(row) for row in rows]


@router.post("/scenes/{scene_id}/voice/regenerate", status_code=202)
async def regenerate_voice(scene_id: str, session: SessionDep):
    scene = await session.get(Scene, scene_id)
    if scene is None:
        raise NotFoundError("Scene tidak ditemukan.")
    script = await session.get(Script, scene.script_id)
    project = await session.get(Project, script.project_id) if script else None
    if script is None or project is None or project.active_script_id != script.id:
        raise AppError(
            409, "ScriptNotActive", "Suara hanya dibuat ulang untuk script aktif."
        )
    active = (
        await session.execute(
            select(GenerationJob).where(
                GenerationJob.scene_id == scene.id,
                GenerationJob.type == "voice",
                GenerationJob.status.in_(("queued", "processing")),
            )
        )
    ).scalars().first()
    if active is not None:
        return {"job": JobOut.model_validate(active), "created": False}
    expected = await ProviderRouter(session).expected_voice(project)
    resource_key = f"voice:{expected[0].id}" if expected else "local"
    job = await queue.enqueue(
        session,
        type="voice",
        input={"scene_id": scene.id, "force": True},
        project_id=project.id,
        scene_id=scene.id,
        resource_key=resource_key,
    )
    await session.commit()
    await session.refresh(job)
    return {"job": JobOut.model_validate(job), "created": True}


@router.post("/scenes/{scene_id}/image/regenerate", status_code=202)
async def regenerate_image(scene_id: str, session: SessionDep):
    from sqlalchemy.exc import IntegrityError

    scene = await session.get(Scene, scene_id)
    if scene is None:
        raise NotFoundError("Scene tidak ditemukan.")
    script = await session.get(Script, scene.script_id)
    project = await session.get(Project, script.project_id) if script else None
    if script is None or project is None or project.active_script_id != script.id:
        raise AppError(
            409, "ScriptNotActive", "Gambar hanya dibuat ulang untuk script aktif."
        )
    active = (
        await session.execute(
            select(GenerationJob).where(
                GenerationJob.scene_id == scene.id,
                GenerationJob.type == "image",
                GenerationJob.status.in_(("queued", "processing")),
            )
        )
    ).scalars().first()
    if active is not None:
        return {"job": JobOut.model_validate(active), "created": False}
    expected = await ProviderRouter(session).expected_image(project)
    resource_key = f"image:{expected.id}" if expected else "local"
    max_attempts = (
        1 if expected is not None and expected.quirks.get("retry_safe") is False else 3
    )
    try:
        async with session.begin_nested():
            job = await queue.enqueue(
                session,
                type="image",
                input={"scene_id": scene.id, "force": True},
                project_id=project.id,
                scene_id=scene.id,
                resource_key=resource_key,
                max_attempts=max_attempts,
            )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        active = (
            await session.execute(
                select(GenerationJob).where(
                    GenerationJob.scene_id == scene.id,
                    GenerationJob.type == "image",
                    GenerationJob.status.in_(("queued", "processing")),
                )
            )
        ).scalars().first()
        if active is None:
            raise
        return {"job": JobOut.model_validate(active), "created": False}
    await session.refresh(job)
    return {"job": JobOut.model_validate(job), "created": True}
