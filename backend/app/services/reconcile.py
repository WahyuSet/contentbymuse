import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import Asset, Project, Script

logger = logging.getLogger(__name__)


async def reconcile(project_id: str | None, factory: async_sessionmaker | None = None) -> None:
    """Menghubungkan keadaan project ke job berikutnya (Spec §4.12).

    Gerbang A: ide terpilih yang belum punya script mengantrekan job script.
    Cabang produksi sesudah Gerbang B diisi Fase 4-6.
    """
    if project_id is None or factory is None:
        return
    from app.db.models import GenerationJob
    from app.jobs.handlers import HANDLERS
    from app.jobs.queue import enqueue_once

    if "script" not in HANDLERS:
        return
    async with factory() as session:
        project = await session.get(Project, project_id)
        if project is None or project.selected_idea_id is None:
            return
        existing = (
            await session.execute(
                select(Script.id).where(Script.idea_id == project.selected_idea_id)
            )
        ).first()
        if existing is not None:
            if project.active_script_id is None:
                # Rantai bisa berhenti tanpa keputusan (job gagal final/dibatalkan):
                # tetapkan versi terbaik yang ada sebagai aktif (Spec §4.4/§4.12).
                active_jobs = (
                    await session.execute(
                        select(GenerationJob.id).where(
                            GenerationJob.project_id == project.id,
                            GenerationJob.type.in_(
                                ("script", "checks_fix", "validate", "revise")
                            ),
                            GenerationJob.status.in_(("queued", "processing")),
                        )
                    )
                ).first()
                if active_jobs is None:
                    from app.services.finalize import finalize_best

                    await finalize_best(session, project)
                    await session.commit()
            await _reconcile_voice_production(session, project)
            await _reconcile_image_production(session, project)
            return
        _job, created = await enqueue_once(
            session,
            type="script",
            input={"idea_id": project.selected_idea_id},
            project_id=project.id,
        )
        await session.commit()
        if created:
            logger.info("reconcile: job script diantrekan untuk project %s", project_id)


async def _active_job_exists(session, *, scene_id: str, type_: str) -> bool:
    from app.db.models import GenerationJob

    row = (
        await session.execute(
            select(GenerationJob.id).where(
                GenerationJob.scene_id == scene_id,
                GenerationJob.type == type_,
                GenerationJob.status.in_(("queued", "processing")),
            )
        )
    ).first()
    return row is not None


async def _reconcile_voice_production(session, project) -> None:
    """Produksi suara pasca-Gerbang B (Spec §4.12): script aktif yang approved
    mengantrekan job voice per scene yang klip terpilihnya belum cocok dengan
    hash keadaan sekarang, dan job align untuk klip tanpa timing."""
    from sqlalchemy.exc import IntegrityError

    from app.db.models import Script
    from app.jobs import queue
    from app.jobs.script_chain import load_scenes
    from app.providers.registry import ADAPTERS
    from app.providers.router import ProviderRouter
    from app.services import assets as asset_service
    from app.services.media_probe import sanitize_tts_text

    if project.active_script_id is None:
        return
    script = await session.get(Script, project.active_script_id)
    if script is None or script.status != "approved":
        return
    router = ProviderRouter(session)
    expected = await router.expected_voice(project)
    if expected is None:
        return
    provider, voice_id = expected
    # Klip sah bisa berasal dari kandidat fallback mana pun (rantai §5.3 di
    # handler mencobanya berurutan); scene dianggap selesai bila hash klip
    # terpilih cocok dengan digest salah satu kandidat, bukan hanya yang utama.
    candidates: list[tuple] = [(provider, voice_id)]
    if project.voice_provider_id is None:
        for other in await router.candidates("voice"):
            if other.id != provider.id:
                candidates.append(
                    (other, other.quirks.get("default_voice") or "default")
                )
    scenes = await load_scenes(session, script.id)
    texts = {s.id: sanitize_tts_text(s.voiceover) for s in scenes}
    changed = False
    for index, scene in enumerate(scenes):
        previous_text = texts[scenes[index - 1].id] if index > 0 else None
        next_text = texts[scenes[index + 1].id] if index + 1 < len(scenes) else None
        digests = set()
        for cand_provider, cand_voice in candidates:
            cand_cls = ADAPTERS.get(("voice", cand_provider.adapter))
            cand_context = bool(cand_cls and cand_cls.caps.supports_context)
            digests.add(
                asset_service.voice_input_hash(
                    text=texts[scene.id],
                    previous_text=previous_text if cand_context else None,
                    next_text=next_text if cand_context else None,
                    provider=cand_provider.id,
                    model=cand_provider.default_model,
                    voice=cand_voice,
                    voice_settings=project.voice_settings or {},
                )
            )
        clip = await asset_service.selected_asset(
            session, project_id=project.id, scene_id=scene.id, kind="voice_clip"
        )
        if clip is None or clip.input_hash not in digests:
            if not await _active_job_exists(session, scene_id=scene.id, type_="voice"):
                # Indeks dedup aktif menjaga balapan cek-lalu-sisip; tabrakan jinak.
                try:
                    async with session.begin_nested():
                        await queue.enqueue(
                            session,
                            type="voice",
                            input={"scene_id": scene.id},
                            project_id=project.id,
                            scene_id=scene.id,
                            resource_key=f"voice:{provider.id}",
                        )
                    changed = True
                except IntegrityError:
                    pass
            continue
        timings = (
            await session.execute(
                select(Asset).where(
                    Asset.scene_id == scene.id,
                    Asset.kind == "word_timings",
                    Asset.is_selected.is_(True),
                )
            )
        ).scalar_one_or_none()
        missing_timings = timings is None or (timings.data or {}).get(
            "clip_asset_id"
        ) != clip.id
        if missing_timings and not await _active_job_exists(
            session, scene_id=scene.id, type_="align"
        ):
            try:
                async with session.begin_nested():
                    await queue.enqueue(
                        session,
                        type="align",
                        input={"scene_id": scene.id, "clip_asset_id": clip.id},
                        project_id=project.id,
                        scene_id=scene.id,
                        resource_key=f"voice:{provider.id}",
                    )
                changed = True
            except IntegrityError:
                pass
    if changed:
        await session.commit()


async def _reconcile_image_production(session, project) -> None:
    """Produksi gambar pasca-Gerbang B (Spec §4.12): script aktif approved
    mengantrekan job image per scene yang gambar terpilihnya belum cocok
    dengan digest salah satu kandidat gambar."""
    from sqlalchemy.exc import IntegrityError

    from app.db.models import Asset as AssetModel
    from app.db.models import Script as ScriptModel
    from app.jobs import queue
    from app.jobs.image import image_candidates, image_digest_set
    from app.jobs.script_chain import load_scenes
    from app.providers.router import ProviderRouter
    from app.services import assets as asset_service
    from app.services.styles_seed import expected_style

    if project.active_script_id is None:
        return
    script = await session.get(ScriptModel, project.active_script_id)
    if script is None or script.status != "approved":
        return
    style = await expected_style(session, project)
    if style is None:
        return
    expected_provider = await ProviderRouter(session).expected_image(project)
    if expected_provider is None:
        return
    candidates = await image_candidates(session, project)
    if not candidates:
        return
    reference_asset = None
    if style.reference_asset_id:
        reference_asset = await session.get(AssetModel, style.reference_asset_id)
    max_attempts = (
        1 if expected_provider.quirks.get("retry_safe") is False else 3
    )
    scenes = await load_scenes(session, script.id)
    changed = False
    for scene in scenes:
        digests = await image_digest_set(
            session, project, style, scene, candidates, reference_asset
        )
        image = await asset_service.selected_asset(
            session, project_id=project.id, scene_id=scene.id, kind="image"
        )
        if image is not None and image.input_hash in digests:
            continue
        if await _active_job_exists(session, scene_id=scene.id, type_="image"):
            continue
        try:
            async with session.begin_nested():
                await queue.enqueue(
                    session,
                    type="image",
                    input={"scene_id": scene.id},
                    project_id=project.id,
                    scene_id=scene.id,
                    resource_key=f"image:{expected_provider.id}",
                    max_attempts=max_attempts,
                )
            changed = True
        except IntegrityError:
            pass
    if changed:
        await session.commit()
