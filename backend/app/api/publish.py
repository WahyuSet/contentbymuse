import json

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, update

from app.api.errors import AppError, NotFoundError
from app.api.jobs import FactoryDep, SessionDep
from app.config import get_settings
from app.db.models import Asset, PublishRecord
from app.services.reconcile import reap_stale_uploads, reconcile
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
            select(PublishRecord)
            .where(PublishRecord.status == "awaiting_upload")
            .order_by(PublishRecord.created_at)
        )
    ).scalars().all()
    out = []
    for record in rows:
        manifest = None
        path = await storage.local_path(f"publish/{record.id}/manifest.json")
        if path.exists():
            try:
                manifest = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                manifest = None  # satu manifest rusak tak boleh memblokir antrean
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


class ReapStaleOut(BaseModel):
    reaped: int


@router.post("/publish/reap-stale", response_model=ReapStaleOut)
async def reap_stale_uploads_endpoint(session: SessionDep):
    """Pelepas klaim upload basi secara berkala, dipanggil eksekutor setiap
    lari: rekor 'uploading' yang ditinggal eksekutor mati (lease
    UPLOAD_LEASE_MINUTES habis) kembali ke awaiting_upload — tanpa menunggu
    ada job worker yang selesai (celah 2026-10-22: antrean job kosong membuat
    rekor basi macet selamanya)."""
    reaped = await reap_stale_uploads(session)
    return ReapStaleOut(reaped=reaped)


@router.post("/publish/{record_id}/claim", response_model=PublishOut)
async def claim_publish(record_id: str, session: SessionDep):
    record = await _load_record(session, record_id)
    # Render basi tidak boleh naik: rekor harus milik render terpilih saat ini.
    selected_render = (
        await session.execute(
            select(Asset.id).where(
                Asset.project_id == record.project_id,
                Asset.kind == "render",
                Asset.is_selected.is_(True),
            )
        )
    ).scalar_one_or_none()
    if selected_render != record.render_id:
        raise AppError(
            409,
            "PublishStale",
            "Render rekor ini sudah digantikan render yang lebih baru.",
        )
    # Klaim atomik: UPDATE bersyarat status — dua eksekutor balapan tidak bisa
    # sama-sama menang (yang kalah mendapat rowcount 0).
    result = await session.execute(
        update(PublishRecord)
        .where(
            PublishRecord.id == record_id,
            PublishRecord.status == "awaiting_upload",
        )
        .values(status="uploading", attempts=PublishRecord.attempts + 1)
    )
    if result.rowcount != 1:
        await session.rollback()
        current = await _load_record(session, record_id)
        raise AppError(
            409,
            "PublishState",
            f"Rekor berstatus {current.status}, bukan awaiting_upload.",
        )
    await session.commit()
    await session.refresh(record)
    return record


@router.post("/publish/{record_id}/retry", response_model=PublishOut)
async def retry_publish(
    record_id: str, session: SessionDep, factory: FactoryDep
):
    """Jalan pemulihan rekor failed: kembali ke queued; reconcile mengantrekan
    ulang job penyiapan paket (yang akan memvalidasi ulang dari nol)."""
    record = await _load_record(session, record_id)
    if record.status != "failed":
        raise AppError(
            409,
            "PublishState",
            f"Hanya rekor failed yang bisa dicoba lagi (status kini {record.status}).",
        )
    record.status = "queued"
    record.error = None
    project_id = record.project_id
    await session.commit()
    await reconcile(project_id, factory)
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
