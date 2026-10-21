from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.db.models import (
    Asset,
    GenerationJob,
    Project,
    Scene,
    Script,
    UsageRecord,
)
from app.jobs import queue
from app.jobs.context import DbCallContext
from app.jobs.script_chain import ScriptInputError, load_scenes
from app.providers.base import VoiceRequest
from app.providers.errors import ProviderError
from app.providers.router import ProviderRouter
from app.services import assets as asset_service
from app.services.media_probe import detect_trim, probe_duration_s, sanitize_tts_text
from app.storage.local import LocalStorage


class NoVoiceProviderError(Exception):
    kind = "NoVoiceProvider"
    retryable = False

    def __init__(self):
        self.message_id = "Tidak ada provider suara aktif untuk project ini."
        super().__init__(self.message_id)


async def voice_candidates(session, project) -> list[tuple]:
    """Urutan coba suara (Spec §5.3): suara harapan project lebih dulu, lalu
    kandidat router lain dengan suara bawaannya masing-masing."""
    router = ProviderRouter(session)
    settings = get_settings()
    expected = await router.expected_voice(project)
    ordered: list[tuple] = []
    seen: set[str] = set()
    if expected is not None:
        provider, voice_id = expected
        ordered.append((provider, voice_id, await router.build_voice(provider, settings)))
        seen.add(provider.id)
    if project.voice_provider_id is None:
        for candidate in await router.candidates("voice"):
            if candidate.id in seen:
                continue
            ordered.append(
                (
                    candidate,
                    candidate.quirks.get("default_voice") or "default",
                    await router.build_voice(candidate, settings),
                )
            )
            seen.add(candidate.id)
    return ordered


async def _cached_clip(session, project_id: str, input_hash: str) -> Asset | None:
    return (
        await session.execute(
            select(Asset).where(
                Asset.project_id == project_id,
                Asset.kind == "voice_clip",
                Asset.input_hash == input_hash,
            )
        )
    ).scalars().first()


async def _ensure_scene_clip(session, source: Asset, scene: Scene, job) -> Asset:
    if source.scene_id == scene.id:
        await asset_service.select_asset(session, source)
        return source
    clone = await asset_service.create_asset(
        session,
        project_id=source.project_id,
        scene_id=scene.id,
        kind="voice_clip",
        storage_key=source.storage_key,
        mime=source.mime,
        size_bytes=source.size_bytes,
        duration_s=source.duration_s,
        data=dict(source.data) if source.data else None,
        input_hash=source.input_hash,
        provider_id=source.provider_id,
        model=source.model,
        params=dict(source.params) if source.params else None,
        job_id=job.id,
    )
    await asset_service.select_asset(session, clone)
    return clone


async def _selected_timings(session, scene_id: str, clip_id: str) -> Asset | None:
    timings = (
        await session.execute(
            select(Asset).where(
                Asset.scene_id == scene_id,
                Asset.kind == "word_timings",
                Asset.is_selected.is_(True),
            )
        )
    ).scalar_one_or_none()
    if timings is not None and (timings.data or {}).get("clip_asset_id") == clip_id:
        return timings
    return None


async def _enqueue_align(session, *, project: Project, scene: Scene, clip: Asset, provider_id):
    active = (
        await session.execute(
            select(GenerationJob).where(
                GenerationJob.scene_id == scene.id,
                GenerationJob.type == "align",
                GenerationJob.status.in_(("queued", "processing")),
            )
        )
    ).scalars().first()
    if active is not None:
        return
    # Cek di atas tidak atomik: indeks dedup aktif adalah penjaga sebenarnya,
    # jadi tabrakan balapan di sini jinak — job align kembar sudah ada.
    from sqlalchemy.exc import IntegrityError

    try:
        async with session.begin_nested():
            await queue.enqueue(
                session,
                type="align",
                input={"scene_id": scene.id, "clip_asset_id": clip.id},
                project_id=project.id,
                scene_id=scene.id,
                resource_key=f"voice:{provider_id}",
            )
    except IntegrityError:
        pass


async def run_voice(job, factory: async_sessionmaker) -> dict:
    ctx = DbCallContext(job.id, factory)
    scene_id = job.input.get("scene_id")
    force = bool(job.input.get("force"))
    settings = get_settings()
    storage = LocalStorage(settings.storage_path)

    async with factory() as session:
        scene = await session.get(Scene, scene_id)
        if scene is None:
            raise ScriptInputError("Scene untuk job suara tidak ditemukan.")
        script = await session.get(Script, scene.script_id)
        project = await session.get(Project, script.project_id) if script else None
        if script is None or project is None or project.active_script_id != script.id:
            raise ScriptInputError("Suara hanya dibuat untuk scene script aktif.")
        scenes = await load_scenes(session, script.id)
        candidates = await voice_candidates(session, project)
        if not candidates:
            raise NoVoiceProviderError()

        text = sanitize_tts_text(scene.voiceover)
        position = scene.position
        previous_text = None
        next_text = None
        for neighbor in scenes:
            if neighbor.position == position - 1:
                previous_text = sanitize_tts_text(neighbor.voiceover)
            if neighbor.position == position + 1:
                next_text = sanitize_tts_text(neighbor.voiceover)

        clip: Asset | None = None
        synth = None  # (provider, voice_id, adapter, result, input_hash)
        last_error: ProviderError | None = None
        for provider, voice_id, adapter in candidates:
            use_prev = previous_text if adapter.caps.supports_context else None
            use_next = next_text if adapter.caps.supports_context else None
            input_hash = asset_service.voice_input_hash(
                text=text,
                previous_text=use_prev,
                next_text=use_next,
                provider=provider.id,
                model=provider.default_model,
                voice=voice_id,
                voice_settings=project.voice_settings or {},
            )
            if not force:
                cached = await _cached_clip(session, project.id, input_hash)
                if cached is not None:
                    clip = await _ensure_scene_clip(session, cached, scene, job)
                    await session.commit()
                    break
            try:
                result = await adapter.synthesize(
                    VoiceRequest(
                        text=text,
                        voice_id=voice_id,
                        model=provider.default_model,
                        previous_text=use_prev,
                        next_text=use_next,
                        voice_settings=project.voice_settings or {},
                    ),
                    ctx,
                )
            except ProviderError as exc:
                last_error = exc
                continue
            synth = (provider, voice_id, input_hash, result)
            break
        if clip is None and synth is None:
            raise last_error or NoVoiceProviderError()

    if synth is not None:
        provider, voice_id, input_hash, result = synth
        ext = "wav" if result.mime == "audio/wav" else "mp3"
        async with factory() as session:
            version = await asset_service.next_version(
                session, project_id=project.id, scene_id=scene.id, kind="voice_clip"
            )
        key = f"assets/{project.id}/{scene.id}/voice_clip-v{version}.{ext}"
        stored = await storage.put(key, result.audio, result.mime)
        path = await storage.local_path(key)
        duration = await probe_duration_s(path)
        trim = await detect_trim(path, duration)
        async with factory() as session:
            clip = await asset_service.create_asset(
                session,
                project_id=project.id,
                scene_id=scene.id,
                kind="voice_clip",
                storage_key=stored.key,
                mime=result.mime,
                size_bytes=stored.size_bytes,
                duration_s=duration,
                data={"trim": trim} if trim else None,
                input_hash=input_hash,
                provider_id=provider.id,
                model=provider.default_model,
                job_id=job.id,
            )
            await asset_service.select_asset(session, clip)
            session.add(
                UsageRecord(
                    job_id=job.id,
                    project_id=project.id,
                    provider_id=provider.id,
                    model=provider.default_model,
                    capability="voice",
                    characters=len(text),
                    seconds=duration,
                    succeeded=True,
                )
            )
            span = (trim["end_s"] - trim["start_s"]) if trim else duration
            await asset_service.update_calibration(
                session,
                provider_id=provider.id,
                voice_id=voice_id,
                words=len(text.split()),
                span_s=span,
            )
            await session.commit()
            clip_id = clip.id

        if result.word_timings:
            async with factory() as session:
                timings = await asset_service.create_asset(
                    session,
                    project_id=project.id,
                    scene_id=scene.id,
                    kind="word_timings",
                    storage_key=key,
                    mime="application/json",
                    size_bytes=0,
                    data={
                        "words": [
                            {"word": w.word, "start": w.start, "end": w.end}
                            for w in result.word_timings
                        ],
                        "method": "provider",
                        "clip_asset_id": clip_id,
                    },
                    input_hash=asset_service.timings_input_hash(
                        clip_input_hash=input_hash, text=text, method="provider"
                    ),
                    provider_id=provider.id,
                    model=provider.default_model,
                    job_id=job.id,
                )
                await asset_service.select_asset(session, timings)
                await session.commit()
            return {"asset_id": clip_id, "cached": False}

    # Klip dari cache atau tanpa timestamp provider: pastikan timing ada.
    async with factory() as session:
        clip_row = await session.get(Asset, clip.id)
        timings = await _selected_timings(session, scene.id, clip_row.id)
        if timings is None:
            await _enqueue_align(
                session,
                project=project,
                scene=scene,
                clip=clip_row,
                provider_id=clip_row.provider_id,
            )
            await session.commit()
    return {"asset_id": clip.id, "cached": synth is None}
