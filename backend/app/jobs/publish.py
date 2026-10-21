import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.db.models import Asset, Project, PublishRecord
from app.jobs.context import DbCallContext
from app.jobs.script_chain import ScriptInputError
from app.storage.local import LocalStorage

PLATFORMS = ("youtube", "facebook")


async def _selected(session, project_id: str, kind: str) -> Asset | None:
    return (
        await session.execute(
            select(Asset).where(
                Asset.project_id == project_id,
                Asset.kind == kind,
                Asset.is_selected.is_(True),
            )
        )
    ).scalar_one_or_none()


async def run_publish(job, factory: async_sessionmaker) -> dict:
    """Siapkan paket publish satu platform: validasi kelengkapan + tulis
    manifest untuk eksekutor upload (agen via browser). Rekor berakhir
    awaiting_upload; hasil upload dilaporkan balik lewat API publish."""
    ctx = DbCallContext(job.id, factory)
    storage = LocalStorage(get_settings().storage_path)
    publish_id = job.input.get("publish_id")
    async with factory() as session:
        record = await session.get(PublishRecord, publish_id)
        if record is None:
            raise ScriptInputError("Rekor publish untuk job ini tidak ditemukan.")
        if record.status in ("awaiting_upload", "uploading", "published"):
            return {"publish_id": record.id, "cached": True}
        project = await session.get(Project, record.project_id)
        render = await session.get(Asset, record.render_id)
        thumbnail = await _selected(session, record.project_id, "thumbnail")
        metadata = await _selected(session, record.project_id, "metadata")

        problems: list[str] = []
        video_key = None
        if render is None:
            problems.append("Render tidak ditemukan.")
        else:
            video_key = (render.data or {}).get("files", {}).get(
                "video"
            ) or render.storage_key
            if not (await storage.local_path(video_key)).exists():
                problems.append("Berkas video render tidak ada di storage.")
        if thumbnail is None:
            problems.append("Thumbnail belum tersedia.")
        elif not (await storage.local_path(thumbnail.storage_key)).exists():
            problems.append("Berkas thumbnail tidak ada di storage.")
        elif (thumbnail.data or {}).get("render_id") not in (
            None,
            record.render_id,
        ):
            problems.append("Thumbnail dibuat untuk render yang berbeda.")
        if metadata is None:
            problems.append("Metadata belum tersedia.")
        else:
            mdata = metadata.data or {}
            if mdata.get("render_id") != record.render_id:
                problems.append("Metadata tidak cocok dengan render ini.")
            if project is not None and mdata.get("script_id") != (
                project.active_script_id
            ):
                problems.append("Metadata dibuat dari script yang bukan aktif.")
            if not (mdata.get("title") or "").strip():
                problems.append("Metadata tidak memiliki judul.")
        if problems:
            record.status = "failed"
            record.error = " ".join(problems)
            await session.commit()
            raise ScriptInputError(record.error)

        mdata = metadata.data or {}
        manifest = {
            "publish_id": record.id,
            "project_id": record.project_id,
            "platform": record.platform,
            "title": mdata.get("title"),
            "description": mdata.get("description"),
            "hashtags": mdata.get("hashtags") or [],
            "fb_caption": mdata.get("fb_caption"),
            "video_path": str(await storage.local_path(video_key)),
            "thumbnail_path": str(
                await storage.local_path(thumbnail.storage_key)
            ),
        }
    key = f"publish/{publish_id}/manifest.json"
    await storage.put(
        key,
        json.dumps(manifest, ensure_ascii=False, indent=2).encode(),
        "application/json",
    )
    async with factory() as session:
        record = await session.get(PublishRecord, publish_id)
        record.status = "awaiting_upload"
        record.error = None
        await session.commit()
    await ctx.log("info", f"Paket publish {manifest['platform']} siap diupload")
    return {"publish_id": publish_id, "manifest": key}
