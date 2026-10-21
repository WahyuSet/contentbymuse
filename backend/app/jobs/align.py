from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.db.models import Asset, Scene
from app.jobs.context import DbCallContext
from app.jobs.script_chain import ScriptInputError
from app.services import assets as asset_service
from app.services.aligner import align_words
from app.services.media_probe import sanitize_tts_text
from app.storage.local import LocalStorage


async def run_align(job, factory: async_sessionmaker) -> dict:
    ctx = DbCallContext(job.id, factory)
    scene_id = job.input.get("scene_id")
    clip_id = job.input.get("clip_asset_id")
    settings = get_settings()
    storage = LocalStorage(settings.storage_path)

    async with factory() as session:
        scene = await session.get(Scene, scene_id)
        clip = await session.get(Asset, clip_id)
        if scene is None or clip is None:
            raise ScriptInputError("Scene atau klip untuk alignment tidak ditemukan.")
        existing = (
            await session.execute(
                select(Asset).where(
                    Asset.scene_id == scene.id,
                    Asset.kind == "word_timings",
                    Asset.is_selected.is_(True),
                )
            )
        ).scalar_one_or_none()
        if existing is not None and (existing.data or {}).get("clip_asset_id") == clip.id:
            return {"asset_id": existing.id, "cached": True}
        text = sanitize_tts_text(scene.voiceover)
        trim = (clip.data or {}).get("trim") if clip.data else None
        bounds = (
            (trim["start_s"], trim["end_s"])
            if trim
            else (0.0, clip.duration_s or 0.0)
        )
        storage_key = clip.storage_key
        project_id = clip.project_id

    path = await storage.local_path(storage_key)
    result = await align_words(path, text, bounds=bounds, ctx=ctx)
    if result.method == "proportional":
        await ctx.log(
            "info",
            "Alignment proporsional dipakai (Whisper tidak menghasilkan kecocokan cukup).",
        )

    async with factory() as session:
        timings = await asset_service.create_asset(
            session,
            project_id=project_id,
            scene_id=scene_id,
            kind="word_timings",
            storage_key=storage_key,
            mime="application/json",
            size_bytes=0,
            data={
                "words": [
                    {"word": w.word, "start": w.start, "end": w.end} for w in result.words
                ],
                "method": result.method,
                "match_ratio": result.match_ratio,
                "clip_asset_id": clip_id,
            },
            input_hash=asset_service.timings_input_hash(
                clip_input_hash=clip.input_hash, text=text, method=result.method
            ),
            job_id=job.id,
        )
        await asset_service.select_asset(session, timings)
        await session.commit()
        return {"asset_id": timings.id, "method": result.method, "cached": False}
