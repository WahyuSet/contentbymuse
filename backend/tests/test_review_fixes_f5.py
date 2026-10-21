import io
import stat

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.jobs.image as image_job
from app.db.models import Base, Project, Provider, Scene, Script, VisualStyle
from app.jobs.script_chain import ScriptInputError
from app.providers.base import ImageRequest
from app.providers.errors import ProviderError
from app.providers.image.muse_cli import MuseCliImage
from app.services.styles_seed import seed_visual_styles


@pytest.fixture
async def factory(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    from app.config import get_settings

    get_settings.cache_clear()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        from app.services.prompts import sync_prompts

        await sync_prompts(session)
        session.add(
            Provider(
                name="Gambar Fake", capability="image", adapter="fake",
                enabled=True, priority=100,
            )
        )
        session.add(
            VisualStyle(
                name="Gaya", style_text="flat", negative_text="",
                mascot_anchor="", image_params={}, is_default=True,
            )
        )
        project = Project(title="P", topic="t")
        session.add(project)
        await session.flush()
        script = Script(
            project_id=project.id, version=1, status="validated",
            title="N", hook="H",
        )
        session.add(script)
        await session.flush()
        project.active_script_id = script.id
        scene = Scene(
            script_id=script.id, position=1, voiceover="narasi",
            visual_prompt="visual", visual_type="character",
            est_duration_s=3.0,
        )
        session.add(scene)
        await session.commit()
        ids = (project.id, script.id, scene.id)
    yield maker, ids
    await engine.dispose()
    get_settings.cache_clear()


async def test_image_handler_rejects_unapproved_active_script(factory):
    maker, (_p, _s, scene_id) = factory
    from app.db.models import GenerationJob

    job = GenerationJob(type="image", input={"scene_id": scene_id}, status="processing")
    with pytest.raises(ScriptInputError):
        await image_job.run_image(job, maker)


async def test_voice_handler_rejects_unapproved_active_script(factory, monkeypatch):
    # Celah yang sama di handler suara Fase 4 (dicatat reviewer Fase 5).
    import app.jobs.voice as voice_job
    from app.db.models import GenerationJob, Provider

    maker, (_p, _s, scene_id) = factory
    async with maker() as session:
        session.add(
            Provider(
                name="Suara Fake", capability="voice", adapter="fake",
                quirks={"default_voice": "fake-1"}, enabled=True, priority=100,
            )
        )
        await session.commit()
    job = GenerationJob(type="voice", input={"scene_id": scene_id}, status="processing")
    with pytest.raises(ScriptInputError):
        await voice_job.run_voice(job, maker)


async def test_image_job_survives_dangling_reference(factory):
    maker, (_p, _s, scene_id) = factory
    async with maker() as session:
        style = (await session.execute(select(VisualStyle))).scalar_one()
        from app.services import assets as asset_service

        ref = await asset_service.create_asset(
            session, project_id=None, scene_id=None, kind="reference_image",
            storage_key="assets/global/reference/hilang.png", mime="image/png",
            size_bytes=10, input_hash="abc",
        )
        style.reference_asset_id = ref.id
        await session.commit()
    from app.jobs.queue import enqueue

    # Script harus approved untuk lolos gerbang; naikkan status dulu.
    async with maker() as session:
        script = (await session.execute(select(Script))).scalar_one()
        script.status = "approved"
        job = await enqueue(
            session, type="image", input={"scene_id": scene_id},
            project_id=_p, scene_id=scene_id,
        )
        await session.commit()
    result = await image_job.run_image(job, maker)
    assert result["cached"] is False  # fake tidak mendukung referensi -> tetap jalan


async def test_muse_cli_rejects_ok_false(tmp_path):
    # Helper khusus menulis file lalu melaporkan ok:false.
    helper = tmp_path / "make2.py"
    helper.write_text(
        "import io, json, pathlib, sys\n"
        "from PIL import Image\n"
        "args = sys.argv[1:]\n"
        "outdir = pathlib.Path(args[args.index('--output-dir') + 1])\n"
        "p = outdir / 'media-generation-x-0-a.jpg'\n"
        "buf = io.BytesIO(); Image.new('RGB', (10, 10)).save(buf, format='JPEG')\n"
        "p.write_bytes(buf.getvalue())\n"
        "print(json.dumps({'ok': False, 'media_paths': [str(p)]}))\n",
        encoding="utf-8",
    )
    script = tmp_path / "media-generation"
    script.write_text(f"#!/bin/sh\nexec python3 {helper} \"$@\"\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    adapter = MuseCliImage(quirks={"cli_path": str(script), "timeout_s": 30})
    with pytest.raises(ProviderError):
        await adapter.generate_image(ImageRequest(prompt="x"))


async def test_muse_cli_rejects_path_outside_output_dir(tmp_path):
    outside = tmp_path / "luar.jpg"
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buffer, format="JPEG")
    outside.write_bytes(buffer.getvalue())
    helper = tmp_path / "make3.py"
    helper.write_text(
        "import json\n"
        f"print(json.dumps({{'ok': True, 'media_paths': [{str(outside)!r}]}}))\n",
        encoding="utf-8",
    )
    script = tmp_path / "media-generation"
    script.write_text(f"#!/bin/sh\nexec python3 {helper} \"$@\"\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    adapter = MuseCliImage(quirks={"cli_path": str(script), "timeout_s": 30})
    with pytest.raises(ProviderError):
        await adapter.generate_image(ImageRequest(prompt="x"))


async def test_seed_default_singularity(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/s.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.add(
            VisualStyle(
                name="Klepon Klasik", style_text="x", negative_text="",
                mascot_anchor="", image_params={}, is_default=False,
            )
        )
        await session.commit()
        await seed_visual_styles(session)
        await session.commit()
    async with maker() as session:
        styles = (await session.execute(select(VisualStyle))).scalars().all()
    assert len(styles) == 1
    assert styles[0].is_default is True
    await engine.dispose()
