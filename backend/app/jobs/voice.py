import asyncio

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
from app.services import lang_qc
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


async def _store_synth_clip(
    factory,
    storage: LocalStorage,
    *,
    job,
    project: Project,
    scene: Scene,
    provider,
    voice_id: str,
    input_hash: str,
    result,
    text: str,
) -> dict:
    """Simpan satu hasil sintesis sebagai aset voice_clip versi baru.

    Hanya membuat aset + UsageRecord: pemilihan aset dan kalibrasi ditunda
    ke finalisasi job, karena QC bahasa (Fase 11 D.2) dapat mengganti klip
    pemenang sesudah sintesis — kalibrasi hanya untuk pemenang akhir.
    """
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
        await session.commit()
        clip_id = clip.id
    return {
        "clip_id": clip_id,
        "key": key,
        "duration": duration,
        "trim": trim,
        "provider": provider,
        "voice_id": voice_id,
        "input_hash": input_hash,
        "result": result,
    }


async def _write_lang_qc(factory, clip_id: str, record: dict) -> None:
    """Tulis hasil QC ke data aset, menggabung dengan kunci lama (mis. trim)."""
    async with factory() as session:
        row = await session.get(Asset, clip_id)
        if row is None:
            return
        data = dict(row.data or {})
        data["lang_qc"] = record
        row.data = data
        await session.commit()


async def _run_lang_qc(
    factory,
    storage: LocalStorage,
    *,
    ctx: DbCallContext,
    job,
    project: Project,
    scene: Scene,
    text: str,
    previous_text: str | None,
    next_text: str | None,
    initial: dict,
    synth_by_clip: dict,
) -> dict:
    """Deteksi bahasa klip terpilih; regenerasi terbatas bila gagal (R2/R6).

    Mengembalikan {"winner_clip_id", "record", "warnings"}. Tidak pernah
    melempar karena QC: detektor rusak -> klip ditandai unavailable dan
    dipakai apa adanya; sintesis ulang gagal -> berhenti dengan klip terbaik
    yang sudah dinilai.
    """
    entries: list[dict] = []
    regenerations = 0
    unavailable: dict | None = None
    current = initial
    while True:
        path = await storage.local_path(current["storage_key"])
        try:
            language, probability = await asyncio.to_thread(
                lang_qc.detect_language, path
            )
        except Exception as exc:  # noqa: BLE001 - QC tak boleh menggagalkan job
            unavailable = {"status": "unavailable", "error": str(exc)}
            await _write_lang_qc(factory, current["clip_id"], unavailable)
            break
        passed = lang_qc.evaluate_qc(language, probability)
        record = {
            "language": language,
            "probability": probability,
            "attempts": regenerations,
            "passed": passed,
        }
        await _write_lang_qc(factory, current["clip_id"], record)
        entries.append({"clip_id": current["clip_id"], **record})
        if passed or regenerations >= lang_qc.MAX_REGENERATIONS:
            break
        async with factory() as session:
            candidates = await voice_candidates(session, project)
        chosen = next(
            (c for c in candidates if c[0].id == current["provider_id"]),
            candidates[0] if candidates else None,
        )
        if chosen is None:
            break
        provider, voice_id, adapter = chosen
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
        except ProviderError:
            break
        regenerations += 1
        info = await _store_synth_clip(
            factory,
            storage,
            job=job,
            project=project,
            scene=scene,
            provider=provider,
            voice_id=voice_id,
            input_hash=input_hash,
            result=result,
            text=text,
        )
        synth_by_clip[info["clip_id"]] = info
        current = {
            "clip_id": info["clip_id"],
            "storage_key": info["key"],
            "provider_id": provider.id,
        }

    if not entries:
        # Detektor gagal pada klip pertama: tidak ada yang bisa diperingkat.
        return {
            "winner_clip_id": initial["clip_id"],
            "record": unavailable,
            "warnings": [],
        }
    winner = entries[0]
    for entry in entries[1:]:
        if lang_qc.rank_key(entry["language"], entry["probability"]) > lang_qc.rank_key(
            winner["language"], winner["probability"]
        ):
            winner = entry
    # attempts pemenang = total regenerasi job ini, bukan saat ia dinilai.
    record = {
        "language": winner["language"],
        "probability": winner["probability"],
        "attempts": regenerations,
        "passed": winner["passed"],
    }
    if record["attempts"] != winner["attempts"]:
        await _write_lang_qc(factory, winner["clip_id"], record)
    warnings: list[str] = []
    if not record["passed"]:
        message = (
            "QC bahasa: klip suara terdeteksi sebagai "
            f"'{record['language']}' (probabilitas {record['probability']:.2f}), "
            "bukan Bahasa Indonesia, "
            f"setelah {regenerations} regenerasi; klip terbaik tetap dipakai."
        )
        warnings.append(message)
        await ctx.log("warning", message)
    return {"winner_clip_id": winner["clip_id"], "record": record, "warnings": warnings}


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
        if script.status != "approved":
            raise ScriptInputError(
                "Suara hanya dibuat untuk script yang sudah disetujui."
            )
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

    # Info sintesis job ini per clip_id: sumber timings provider + kalibrasi
    # pemenang akhir. Klip cache tidak masuk peta ini.
    synth_by_clip: dict[str, dict] = {}
    if synth is not None:
        provider, voice_id, input_hash, result = synth
        info = await _store_synth_clip(
            factory,
            storage,
            job=job,
            project=project,
            scene=scene,
            provider=provider,
            voice_id=voice_id,
            input_hash=input_hash,
            result=result,
            text=text,
        )
        synth_by_clip[info["clip_id"]] = info
        winner_id = info["clip_id"]
        initial = {
            "clip_id": info["clip_id"],
            "storage_key": info["key"],
            "provider_id": provider.id,
        }
    else:
        winner_id = clip.id
        initial = {
            "clip_id": clip.id,
            "storage_key": clip.storage_key,
            "provider_id": clip.provider_id,
        }

    # QC bahasa (Fase 11 D.2): sesudah klip final ditentukan, sebelum return
    # mana pun. Tanpa WHISPER_MODEL, QC dilewati dan perilaku lama utuh.
    qc_record: dict | None = None
    warnings: list[str] = []
    if not lang_qc.qc_enabled():
        await ctx.log(
            "info", "QC bahasa dilewati: WHISPER_MODEL tidak terpasang."
        )
    else:
        qc = await _run_lang_qc(
            factory,
            storage,
            ctx=ctx,
            job=job,
            project=project,
            scene=scene,
            text=text,
            previous_text=previous_text,
            next_text=next_text,
            initial=initial,
            synth_by_clip=synth_by_clip,
        )
        winner_id = qc["winner_clip_id"]
        qc_record = qc["record"]
        warnings = qc["warnings"]

    # Finalisasi: pemenang terpilih; kalibrasi hanya untuk pemenang sintesis.
    winner_synth = synth_by_clip.get(winner_id)
    async with factory() as session:
        clip_row = await session.get(Asset, winner_id)
        await asset_service.select_asset(session, clip_row)
        if winner_synth is not None:
            trim = winner_synth["trim"]
            duration = winner_synth["duration"]
            span = (trim["end_s"] - trim["start_s"]) if trim else duration
            await asset_service.update_calibration(
                session,
                provider_id=winner_synth["provider"].id,
                voice_id=winner_synth["voice_id"],
                words=len(text.split()),
                span_s=span,
            )
        await session.commit()

    result_out: dict = {"asset_id": winner_id, "cached": winner_synth is None}
    if winner_synth is not None and winner_synth["result"].word_timings:
        result = winner_synth["result"]
        provider = winner_synth["provider"]
        async with factory() as session:
            timings = await asset_service.create_asset(
                session,
                project_id=project.id,
                scene_id=scene.id,
                kind="word_timings",
                storage_key=winner_synth["key"],
                mime="application/json",
                size_bytes=0,
                data={
                    "words": [
                        {"word": w.word, "start": w.start, "end": w.end}
                        for w in result.word_timings
                    ],
                    "method": "provider",
                    "clip_asset_id": winner_id,
                },
                input_hash=asset_service.timings_input_hash(
                    clip_input_hash=winner_synth["input_hash"],
                    text=text,
                    method="provider",
                ),
                provider_id=provider.id,
                model=provider.default_model,
                job_id=job.id,
            )
            await asset_service.select_asset(session, timings)
            await session.commit()
    else:
        # Klip dari cache atau tanpa timestamp provider: pastikan timing ada.
        async with factory() as session:
            clip_row = await session.get(Asset, winner_id)
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

    if qc_record is not None:
        result_out["lang_qc"] = qc_record
    if warnings:
        result_out["warnings"] = warnings
    return result_out
