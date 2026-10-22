import hashlib
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.db.models import Asset, Project, Script, UsageRecord
from app.jobs.context import DbCallContext
from app.jobs.image import image_candidates
from app.jobs.script_chain import ScriptInputError
from app.providers.base import ImageRequest
from app.providers.errors import ProviderError, ServerError
from app.services import assets as asset_service
from app.services.image_normalize import ImageNormalizeError, normalize_to_portrait
from app.services.styles_seed import expected_style
from app.storage.local import LocalStorage

_QUESTION_OPENERS = {"kenapa", "mengapa", "apa", "bagaimana", "kapan", "siapa"}
_WEAK_TAIL = {"di", "ke", "dari", "yang", "dan", "itu", "ini", "kok", "sih", "pada"}


def _short_title(title: str, max_words: int = 5) -> str:
    """Teks thumbnail cadangan dari judul: buang kata tanya pembuka dan kata
    lemah di ujung supaya frasanya terasa utuh, bukan potongan kalimat.
    Teks utama tetap yang ditulis agen produksi lewat endpoint revise."""
    words = title.replace(":", " ").replace(",", " ").split()
    while words and words[0].lower().strip("?") in _QUESTION_OPENERS:
        words.pop(0)
    words = words[:max_words]
    while words and words[-1].lower() in _WEAK_TAIL:
        words.pop()
    return " ".join(words).upper()


def build_thumbnail_prompt(style, hook_visual: str, title_text: str) -> str:
    """Konsep thumbnail dari AI; teks judul dikomposit lokal sesudahnya karena
    generator gambar menolak menggambar teks tertentu (cek integritas)."""
    parts = [
        style.style_text.rstrip(". ") + ".",
        f"Mascot anchor: {style.mascot_anchor}",
        (
            f"Thumbnail scene: {hook_visual} Make the mascot's expression "
            "exaggerated and instantly readable at small size, with strong "
            "contrast against the background."
        ),
        (
            "Draw no text at all in the image. Leave the top third of the "
            "frame as calm, uncluttered background space for a title."
        ),
        (
            "Compose for a vertical 9:16 frame; keep the bottom quarter "
            "free of important details."
        ),
    ]
    return " ".join(parts)


class NoRenderError(ScriptInputError):
    pass


async def run_thumbnail(job, factory: async_sessionmaker) -> dict:
    """Thumbnail AI untuk render terpilih (Fase 7)."""
    ctx = DbCallContext(job.id, factory)
    storage = LocalStorage(get_settings().storage_path)
    async with factory() as session:
        project = await session.get(Project, job.project_id)
        if project is None or project.active_script_id is None:
            raise ScriptInputError("Project atau script aktif tidak ditemukan.")
        script = await session.get(Script, project.active_script_id)
        if script is None or script.status != "approved":
            raise ScriptInputError("Thumbnail hanya dibuat untuk script yang disetujui.")
        render = (
            await session.execute(
                select(Asset).where(
                    Asset.project_id == project.id,
                    Asset.kind == "render",
                    Asset.is_selected.is_(True),
                )
            )
        ).scalar_one_or_none()
        if render is None:
            raise NoRenderError("Thumbnail menunggu render tersedia.")
        style = await expected_style(session, project)
        if style is None:
            raise ScriptInputError("Project belum punya gaya visual.")
        from app.jobs.script_chain import load_scenes

        scenes = await load_scenes(session, script.id)
        hook_visual = scenes[0].visual_prompt if scenes else project.title
        title_text = _short_title(script.title or project.title)
        digest = hashlib.sha256(
            json.dumps(
                {
                    "render": render.id,
                    "style": [style.id, style.version],
                    "title_text": title_text,
                    "hook_visual": hook_visual,
                    "prompt": build_thumbnail_prompt(style, hook_visual, title_text),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        existing = (
            await session.execute(
                select(Asset).where(
                    Asset.project_id == project.id,
                    Asset.kind == "thumbnail",
                    Asset.input_hash == digest,
                )
            )
        ).scalars().first()
        # Cache hanya sah bila berkasnya benar-benar masih ada di storage.
        if existing is not None and (
            await storage.local_path(existing.storage_key)
        ).exists():
            if not existing.is_selected:
                await asset_service.select_asset(session, existing)
                await session.commit()
            return {"asset_id": existing.id, "cached": True}
        candidates = await image_candidates(session, project)
        if not candidates:
            raise ScriptInputError("Tidak ada provider gambar yang aktif.")
        reference_asset = None
        if style.reference_asset_id:
            reference_asset = await session.get(Asset, style.reference_asset_id)
        prompt = build_thumbnail_prompt(style, hook_visual, title_text)
        params = dict(style.image_params or {})

    generated = None
    last_error: ProviderError | None = None
    for provider, adapter in candidates:
        use_reference = (
            adapter.caps.supports_reference_image and reference_asset is not None
        )
        reference_bytes = None
        if use_reference:
            reference_bytes = (
                await storage.local_path(reference_asset.storage_key)
            ).read_bytes()
        try:
            result = await adapter.generate_image(
                ImageRequest(
                    prompt=prompt,
                    negative_prompt=style.negative_text or None,
                    aspect_ratio="9:16",
                    reference_images=[reference_bytes] if reference_bytes else [],
                    model=provider.default_model,
                    extra={"label": "thumbnail", "params": params},
                ),
                ctx,
            )
            normalized, original = normalize_to_portrait(result.image)
        except ProviderError as exc:
            await ctx.log("warning", f"Provider {provider.name} gagal: {exc}")
            last_error = exc
            continue
        except ImageNormalizeError as exc:
            last_error = ServerError(
                "Hasil provider bukan gambar yang valid.", detail=str(exc)
            )
            continue
        generated = (provider, normalized, original)
        break
    if generated is None:
        raise last_error or ScriptInputError("Provider gambar gagal.")

    provider, normalized, original = generated
    from app.services.thumbnail_text import draw_title_text

    final = draw_title_text(normalized, title_text)
    async with factory() as session:
        version = await asset_service.next_version(
            session, project_id=project.id, scene_id=None, kind="thumbnail"
        )
    raw_key = f"assets/{project.id}/thumbnail-raw-v{version}.png"
    await storage.put(raw_key, normalized, "image/png")
    key = f"assets/{project.id}/thumbnail-v{version}.png"
    stored = await storage.put(key, final, "image/png")
    async with factory() as session:
        asset = await asset_service.create_asset(
            session,
            project_id=project.id,
            scene_id=None,
            kind="thumbnail",
            storage_key=stored.key,
            mime="image/png",
            size_bytes=stored.size_bytes,
            width=1080,
            height=1920,
            data={
                "render_id": render.id,
                "prompt": prompt,
                "title_text": title_text,
                "raw_key": raw_key,
                "original_size": list(original),
            },
            input_hash=digest,
            provider_id=provider.id,
            model=provider.default_model,
            params=params,
            job_id=job.id,
        )
        await asset_service.select_asset(session, asset)
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
        return {"asset_id": asset.id, "cached": False}
