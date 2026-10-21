import asyncio
import shutil
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.models import Asset, GenerationJob, Project, Scene, Script
from app.jobs.context import DbCallContext
from app.jobs.script_chain import ScriptInputError
from app.services import assets as asset_service
from app.services.ffmpeg_render import run_render
from app.services.render_plan import SceneInput, WordTiming, build_render_plan
from app.services.render_settings import get_subtitle_style
from app.services.subtitles import proportional_words
from app.storage.local import LocalStorage


async def _selected(session: AsyncSession, scene_id: str, kind: str) -> Asset | None:
    return (
        await session.execute(
            select(Asset).where(
                Asset.scene_id == scene_id,
                Asset.kind == kind,
                Asset.is_selected.is_(True),
            )
        )
    ).scalar_one_or_none()


async def render_hash_parts(
    session: AsyncSession, project: Project, script: Script, style: dict
) -> tuple[dict, list[tuple[Scene, Asset, Asset, Asset | None]]]:
    scenes = (
        await session.execute(
            select(Scene).where(Scene.script_id == script.id).order_by(Scene.position)
        )
    ).scalars().all()
    per_scene = []
    parts: dict = {"style": style, "scenes": []}
    for scene in scenes:
        voice = await _selected(session, scene.id, "voice_clip")
        image = await _selected(session, scene.id, "image")
        timings = await _selected(session, scene.id, "word_timings")
        per_scene.append((scene, voice, image, timings))
        parts["scenes"].append(
            {
                "scene_id": scene.id,
                "revision": scene.revision,
                "visual_type": scene.visual_type,
                "transition": scene.transition,
                "subtitle_override": scene.subtitle_override,
                "emphasis_words": scene.emphasis_words,
                "voice": [voice.id, voice.version] if voice else None,
                "image": [image.id, image.version] if image else None,
                "timings": [timings.id, timings.version] if timings else None,
            }
        )
    return parts, per_scene


async def run_render_job(
    job: GenerationJob, factory: async_sessionmaker
) -> dict:
    storage = LocalStorage(get_settings().storage_path)
    ctx = DbCallContext(job.id, factory)
    async with factory() as session:
        project = await session.get(Project, job.project_id)
        script = (
            await session.get(Script, project.active_script_id)
            if project and project.active_script_id
            else None
        )
        if project is None or script is None:
            raise ScriptInputError("Render butuh project dengan script aktif.")
        if script.status != "approved":
            raise ScriptInputError(
                "Render hanya dibuat untuk script yang sudah disetujui."
            )
        style = await get_subtitle_style(session)
        await session.commit()
        parts, per_scene = await render_hash_parts(session, project, script, style)
        missing = []
        for scene, voice, image, _timings in per_scene:
            if voice is None:
                missing.append(f"scene {scene.position} belum punya suara")
            if image is None:
                missing.append(f"scene {scene.position} belum punya gambar")
        if missing:
            raise ScriptInputError("Render belum siap: " + "; ".join(missing) + ".")
        digest = asset_service.render_input_hash(parts)
        force = bool((job.input or {}).get("force"))
        existing = (
            await session.execute(
                select(Asset).where(
                    Asset.project_id == project.id,
                    Asset.kind == "render",
                    Asset.input_hash == digest,
                )
            )
        ).scalars().first()
        if existing is not None and not force:
            video_file = await storage.local_path(existing.storage_key)
            if video_file.exists():
                if not existing.is_selected:
                    await asset_service.select_asset(session, existing)
                    await session.commit()
                return {"asset_id": existing.id, "cached": True}

        scene_inputs: list[SceneInput] = []
        for scene, voice, image, timings in per_scene:
            trim = None
            if voice.data and voice.data.get("trim"):
                trim = (
                    float(voice.data["trim"]["start"]),
                    float(voice.data["trim"]["end"]),
                )
            if timings is not None and timings.data and timings.data.get("words"):
                words = [
                    WordTiming(
                        word=w["word"],
                        start=float(w["start"]),
                        end=float(w["end"]),
                    )
                    for w in timings.data["words"]
                ]
            else:
                start = trim[0] if trim else 0.0
                end = trim[1] if trim else float(voice.duration_s or 0.0)
                words = proportional_words(scene.voiceover, start, end)
            scene_inputs.append(
                SceneInput(
                    id=scene.id,
                    position=scene.position,
                    image_path=str(await storage.local_path(image.storage_key)),
                    audio_path=str(await storage.local_path(voice.storage_key)),
                    trim=trim,
                    clip_duration_s=float(voice.duration_s or 0.0),
                    words=words,
                    visual_type=scene.visual_type,
                    transition=scene.transition or "cut",
                    subtitle_override=scene.subtitle_override,
                    voiceover=scene.voiceover,
                    emphasis_words=list(scene.emphasis_words or []),
                )
            )

    plan = build_render_plan(scenes=scene_inputs, subtitle_style=style)
    workdir = Path(tempfile.mkdtemp(prefix=f"render-{job.id}-"))
    progress_state = {"fraction": 0.0}

    def _on_progress(fraction: float) -> None:
        progress_state["fraction"] = max(progress_state["fraction"], fraction)

    async def _flush_progress() -> None:
        while True:
            await asyncio.sleep(5)
            try:
                await ctx.progress(
                    int(progress_state["fraction"] * 100), "Merender video…"
                )
            except Exception:  # noqa: BLE001, S110 - progres gagal tulis tidak menghentikan render
                pass

    flush_task = asyncio.create_task(_flush_progress())
    try:
        result = await run_render(plan, workdir=workdir, progress_cb=_on_progress)
        asset_id = await _save_result(
            factory, storage, project, result, digest, workdir
        )
    finally:
        flush_task.cancel()
        try:
            await flush_task
        except asyncio.CancelledError:
            pass
        shutil.rmtree(workdir, ignore_errors=True)
    await ctx.log(
        "info",
        f"Render selesai: {result.duration_s:.1f} detik, encoder "
        f"{result.encoder}, {result.render_seconds:.1f} detik proses.",
    )
    return {"asset_id": asset_id, "cached": False, "warnings": result.warnings}


async def _save_result(factory, storage, project, result, digest, workdir) -> str:
    async with factory() as session:
        next_version = await asset_service.next_version(
            session, project_id=project.id, scene_id=None, kind="render"
        )
        base_key = f"assets/{project.id}/render-v{next_version}"
        keys = {
            "video": f"{base_key}/video.mp4",
            "srt": f"{base_key}/subtitles.srt",
            "ass": f"{base_key}/subtitles.ass",
            "thumbnail": f"{base_key}/thumbnail.jpg",
        }
        sources = {
            "video": result.video_path,
            "srt": result.srt_path,
            "ass": result.ass_path,
            "thumbnail": result.thumbnail_path,
        }
        for name, key in keys.items():
            target = await storage.local_path(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(sources[name], target)
        data = {
            "files": keys,
            "encoder": result.encoder,
            "duration_s": result.duration_s,
            "render_seconds": round(result.render_seconds, 2),
            "warnings": result.warnings,
        }
        asset = await asset_service.create_asset(
            session,
            project_id=project.id,
            scene_id=None,
            kind="render",
            storage_key=keys["video"],
            mime="video/mp4",
            size_bytes=(await storage.local_path(keys["video"])).stat().st_size,
            duration_s=result.duration_s,
            input_hash=digest,
            data=data,
        )
        await asset_service.select_asset(session, asset)
        await session.commit()
        return asset.id
