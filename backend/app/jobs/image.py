from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.db.models import Asset, Project, Scene, Script, UsageRecord
from app.jobs.context import DbCallContext
from app.jobs.script_chain import ScriptInputError
from app.providers.base import ImageRequest
from app.providers.errors import ProviderError, ServerError
from app.providers.router import ProviderRouter
from app.services import assets as asset_service
from app.services.image_normalize import ImageNormalizeError, normalize_to_portrait
from app.services.prompts import compose_image_prompt
from app.services.styles_seed import expected_style
from app.storage.local import LocalStorage


class NoImageProviderError(Exception):
    kind = "NoImageProvider"
    retryable = False

    def __init__(self, message: str = "Tidak ada provider gambar aktif untuk project ini."):
        self.message_id = message
        super().__init__(self.message_id)


async def image_candidates(session, project) -> list[tuple]:
    """Urutan coba gambar (Spec §5.3): provider harapan project lebih dulu,
    lalu kandidat router lain bila project tidak mem-pin provider."""
    router = ProviderRouter(session)
    settings = get_settings()
    expected = await router.expected_image(project)
    ordered: list[tuple] = []
    seen: set[str] = set()
    if expected is not None:
        ordered.append((expected, await router.build_image(expected, settings)))
        seen.add(expected.id)
    if project.image_provider_id is None:
        for candidate in await router.candidates("image"):
            if candidate.id in seen:
                continue
            ordered.append(
                (candidate, await router.build_image(candidate, settings))
            )
            seen.add(candidate.id)
    return ordered


async def _cached_image(session, project_id: str, input_hash: str) -> Asset | None:
    return (
        await session.execute(
            select(Asset).where(
                Asset.project_id == project_id,
                Asset.kind == "image",
                Asset.input_hash == input_hash,
            )
        )
    ).scalars().first()


async def _ensure_scene_image(session, source: Asset, scene: Scene, job) -> Asset:
    if source.scene_id == scene.id:
        await asset_service.select_asset(session, source)
        return source
    clone = await asset_service.create_asset(
        session,
        project_id=source.project_id,
        scene_id=scene.id,
        kind="image",
        storage_key=source.storage_key,
        mime=source.mime,
        size_bytes=source.size_bytes,
        width=source.width,
        height=source.height,
        data=dict(source.data) if source.data else None,
        input_hash=source.input_hash,
        provider_id=source.provider_id,
        model=source.model,
        params=dict(source.params) if source.params else None,
        job_id=job.id,
    )
    await asset_service.select_asset(session, clone)
    return clone


async def run_image(job, factory: async_sessionmaker) -> dict:
    ctx = DbCallContext(job.id, factory)
    scene_id = job.input.get("scene_id")
    force = bool(job.input.get("force"))
    settings = get_settings()
    storage = LocalStorage(settings.storage_path)

    async with factory() as session:
        scene = await session.get(Scene, scene_id)
        if scene is None:
            raise ScriptInputError("Scene untuk job gambar tidak ditemukan.")
        script = await session.get(Script, scene.script_id)
        project = await session.get(Project, script.project_id) if script else None
        if script is None or project is None or project.active_script_id != script.id:
            raise ScriptInputError("Gambar hanya dibuat untuk scene script aktif.")
        style = await expected_style(session, project)
        if style is None:
            raise NoImageProviderError("Project belum punya gaya visual.")
        candidates = await image_candidates(session, project)
        if not candidates:
            raise NoImageProviderError()
        prompt = await compose_image_prompt(session, style, scene)
        params = dict(style.image_params or {})
        negative_text = style.negative_text or None

        reference_asset = None
        if style.reference_asset_id:
            reference_asset = await session.get(Asset, style.reference_asset_id)
        reference_bytes: bytes | None = None
        if reference_asset is not None:
            reference_bytes = (await storage.local_path(reference_asset.storage_key)).read_bytes()

        generated = None  # (provider, adapter, input_hash, normalized, original)
        last_error: ProviderError | None = None
        for provider, adapter in candidates:
            use_reference = (
                adapter.caps.supports_reference_image
                and scene.include_mascot
                and reference_asset is not None
            )
            input_hash = asset_service.image_input_hash(
                prompt=prompt,
                negative_text=negative_text,
                provider=provider.id,
                model=provider.default_model,
                params=params,
                reference_hash=reference_asset.input_hash if use_reference else None,
            )
            if not force:
                cached = await _cached_image(session, project.id, input_hash)
                if cached is not None:
                    image = await _ensure_scene_image(session, cached, scene, job)
                    await session.commit()
                    return {"asset_id": image.id, "cached": True}
            try:
                result = await adapter.generate_image(
                    ImageRequest(
                        prompt=prompt,
                        negative_prompt=negative_text,
                        aspect_ratio="9:16",
                        reference_images=[reference_bytes] if use_reference else [],
                        model=provider.default_model,
                        extra={
                            "label": f"{scene.position:02d} {scene.visual_type}",
                            "params": params,
                        },
                    ),
                    ctx,
                )
                normalized, original = normalize_to_portrait(result.image)
            except ProviderError as exc:
                last_error = exc
                continue
            except ImageNormalizeError as exc:
                last_error = ServerError(
                    "Hasil provider bukan gambar yang valid.", detail=str(exc)
                )
                continue
            generated = (provider, input_hash, normalized, original)
            break
        if generated is None:
            raise last_error or NoImageProviderError()

    provider, input_hash, normalized, original = generated
    async with factory() as session:
        version = await asset_service.next_version(
            session, project_id=project.id, scene_id=scene.id, kind="image"
        )
    key = f"assets/{project.id}/{scene.id}/image-v{version}.png"
    stored = await storage.put(key, normalized, "image/png")
    async with factory() as session:
        image = await asset_service.create_asset(
            session,
            project_id=project.id,
            scene_id=scene.id,
            kind="image",
            storage_key=stored.key,
            mime="image/png",
            size_bytes=stored.size_bytes,
            width=1080,
            height=1920,
            data={"prompt": prompt, "original_size": list(original)},
            input_hash=input_hash,
            provider_id=provider.id,
            model=provider.default_model,
            params=params,
            job_id=job.id,
        )
        await asset_service.select_asset(session, image)
        session.add(
            UsageRecord(
                job_id=job.id,
                project_id=project.id,
                provider_id=provider.id,
                model=provider.default_model,
                capability="image",
                images=1,
                succeeded=True,
            )
        )
        await session.commit()
        image_id = image.id
    await ctx.log("info", f"Gambar scene {scene.position} dibuat (versi {version}).")
    return {"asset_id": image_id, "cached": False}
