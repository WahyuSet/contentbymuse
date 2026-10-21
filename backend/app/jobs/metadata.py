import hashlib
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.db.models import Asset, Project, Script
from app.domain.llm_outputs import MetadataOutput
from app.jobs.context import DbCallContext
from app.jobs.script_chain import ScriptInputError, llm_pairs, load_scenes
from app.services import assets as asset_service
from app.services.prompts import PromptService
from app.services.structured_llm import StructuredLLM
from app.storage.local import LocalStorage


async def run_metadata(job, factory: async_sessionmaker) -> dict:
    """Metadata publish (judul/deskripsi/tagar) dari naskah final (Fase 7)."""
    ctx = DbCallContext(job.id, factory)
    storage = LocalStorage(get_settings().storage_path)
    async with factory() as session:
        project = await session.get(Project, job.project_id)
        if project is None or project.active_script_id is None:
            raise ScriptInputError("Project atau script aktif tidak ditemukan.")
        script = await session.get(Script, project.active_script_id)
        if script is None or script.status != "approved":
            raise ScriptInputError("Metadata hanya dibuat untuk script yang disetujui.")
        scenes = await load_scenes(session, script.id)
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
            raise ScriptInputError("Metadata menunggu render tersedia.")
        digest = hashlib.sha256(
            json.dumps(
                {
                    "render": render.id,
                    "script": script.id,
                    "revisions": [s.revision for s in scenes],
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        existing = (
            await session.execute(
                select(Asset).where(
                    Asset.project_id == project.id,
                    Asset.kind == "metadata",
                    Asset.input_hash == digest,
                )
            )
        ).scalars().first()
        if existing is not None:
            if not existing.is_selected:
                await asset_service.select_asset(session, existing)
                await session.commit()
            return {"asset_id": existing.id, "cached": True}
        category_name = ""
        if project.category_id:
            from app.db.models import Category

            category = await session.get(Category, project.category_id)
            category_name = category.name if category else ""
        inputs = {
            "title": project.title,
            "script_text": "\n".join(
                f"{s.position}. {s.voiceover}" for s in scenes
            ),
            "category": category_name,
        }
        pairs = await llm_pairs(session)
        prompts = PromptService(session)

    await ctx.progress(30, "Menulis metadata publish")
    result = await StructuredLLM(pairs, prompts).generate(
        task="metadata.generate",
        inputs=inputs,
        output_model=MetadataOutput,
        ctx=ctx,
    )
    payload = result.data.model_dump()
    async with factory() as session:
        version = await asset_service.next_version(
            session, project_id=job.project_id, scene_id=None, kind="metadata"
        )
    key = f"assets/{job.project_id}/metadata-v{version}.json"
    stored = await storage.put(
        key, json.dumps(payload, ensure_ascii=False, indent=2).encode(), "application/json"
    )
    async with factory() as session:
        asset = await asset_service.create_asset(
            session,
            project_id=job.project_id,
            scene_id=None,
            kind="metadata",
            storage_key=stored.key,
            mime="application/json",
            size_bytes=stored.size_bytes,
            data={"render_id": render.id, "script_id": script.id, **payload},
            input_hash=digest,
            job_id=job.id,
        )
        await asset_service.select_asset(session, asset)
        await session.commit()
        return {"asset_id": asset.id, "cached": False}
