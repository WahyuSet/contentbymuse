import json

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.errors import AppError, NotFoundError
from app.api.jobs import SessionDep
from app.config import get_settings
from app.db.models import PublishRecord
from app.storage.local import LocalStorage

router = APIRouter(prefix="/api", tags=["publish"])


class PublishOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    render_id: str
    platform: str
    status: str
    external_id: str | None
    url: str | None
    error: str | None
    attempts: int


class PublishResultIn(BaseModel):
    status: str  # published | failed
    url: str | None = None
    external_id: str | None = None
    error: str | None = None


@router.get("/projects/{project_id}/publish", response_model=list[PublishOut])
async def list_project_publish(project_id: str, session: SessionDep):
    rows = (
        await session.execute(
            select(PublishRecord)
            .where(PublishRecord.project_id == project_id)
            .order_by(PublishRecord.created_at.desc())
        )
    ).scalars().all()
    return rows


@router.get("/publish/awaiting")
async def list_awaiting(session: SessionDep):
    """Antrean untuk eksekutor upload (agen): rekor awaiting_upload + manifest."""
    storage = LocalStorage(get_settings().storage_path)
    rows = (
        await session.execute(
            select(PublishRecord).where(
                PublishRecord.status == "awaiting_upload"
            )
        )
    ).scalars().all()
    out = []
    for record in rows:
        manifest = None
        key = f"publish/{record.id}/manifest.json"
        path = await storage.local_path(key)
        if path.exists():
            manifest = json.loads(path.read_text())
        out.append(
            {
                "publish_id": record.id,
                "project_id": record.project_id,
                "platform": record.platform,
                "manifest": manifest,
            }
        )
    return out


async def _load_record(session, record_id: str) -> PublishRecord:
    record = await session.get(PublishRecord, record_id)
    if record is None:
        raise NotFoundError("Rekor publish tidak ditemukan.")
    return record


@router.post("/publish/{record_id}/claim", response_model=PublishOut)
async def claim_publish(record_id: str, session: SessionDep):
    record = await _load_record(session, record_id)
    if record.status != "awaiting_upload":
        raise AppError(
            409,
            "PublishState",
            f"Rekor berstatus {record.status}, bukan awaiting_upload.",
        )
    record.status = "uploading"
    record.attempts += 1
    await session.commit()
    await session.refresh(record)
    return record


@router.post("/publish/{record_id}/result", response_model=PublishOut)
async def report_publish_result(
    record_id: str, body: PublishResultIn, session: SessionDep
):
    record = await _load_record(session, record_id)
    if body.status not in ("published", "failed"):
        raise AppError(
            422, "PublishResult", "Status hasil harus published atau failed."
        )
    if record.status not in ("awaiting_upload", "uploading"):
        raise AppError(
            409,
            "PublishState",
            f"Rekor berstatus {record.status}; hasil tidak bisa dicatat.",
        )
    if body.status == "published" and not (body.url or body.external_id):
        raise AppError(
            422,
            "PublishResult",
            "Hasil published wajib menyertakan url atau external_id.",
        )
    record.status = body.status
    record.url = body.url
    record.external_id = body.external_id
    record.error = body.error if body.status == "failed" else None
    await session.commit()
    await session.refresh(record)
    return record
