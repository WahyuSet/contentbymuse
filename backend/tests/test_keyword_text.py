"""Fase 9 Tugas 4: draw_keyword_text + render hash memuat keyword_text.

Keyword text di-composite lokal di pita atas gambar scene saat render
(font sama dengan thumbnail, putih + outline hitam), supaya pemirsa
mute tetap menangkap kata kunci scene. Generator gambar tidak pernah
disuruh menggambar teks.
"""

import io

import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, Project, Scene, Script
from app.jobs.render import render_hash_parts
from app.services.thumbnail_text import draw_keyword_text


def _white_png(width: int = 1080, height: int = 1920) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


def test_draw_keyword_text_draws_in_top_band_only():
    source = _white_png()
    out = draw_keyword_text(source, "MSCI")
    result = Image.open(io.BytesIO(out))
    assert result.size == (1080, 1920)

    original = Image.open(io.BytesIO(source))
    # Pita atas (tempat teks kata kunci digambar) berubah.
    top_in = original.crop((0, 100, 1080, 300)).tobytes()
    top_out = result.crop((0, 100, 1080, 300)).tobytes()
    assert top_out != top_in
    # Setengah bawah gambar tidak tersentuh.
    bottom_in = original.crop((0, 960, 1080, 1920)).tobytes()
    bottom_out = result.crop((0, 960, 1080, 1920)).tobytes()
    assert bottom_out == bottom_in


def test_draw_keyword_text_empty_returns_input_unchanged():
    source = _white_png()
    assert draw_keyword_text(source, "") == source
    assert draw_keyword_text(source, "   \n ") == source


def test_draw_keyword_text_uppercases_text():
    source = _white_png()
    # Masukan huruf kecil dan huruf besar harus menghasilkan gambar yang
    # identik — bukti teks dinormalkan ke HURUF BESAR sebelum digambar.
    assert draw_keyword_text(source, "msci turun") == draw_keyword_text(
        source, "MSCI TURUN"
    )


def test_draw_keyword_text_long_text_shrinks_to_fit():
    source = _white_png()
    out = draw_keyword_text(source, "KATA KUNCI YANG SANGAT PANJANG SEKALI")
    result = Image.open(io.BytesIO(out))
    assert result.size == (1080, 1920)


@pytest.fixture
async def hash_world(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/hash.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        project = Project(title="P", topic="t")
        session.add(project)
        await session.flush()
        script = Script(
            project_id=project.id, version=1, status="approved",
            title="N", hook="H",
        )
        session.add(script)
        await session.flush()
        project.active_script_id = script.id
        scene = Scene(
            script_id=script.id, position=1, voiceover="ihsg turun",
            visual_prompt="v", visual_type="character", est_duration_s=3.0,
            keyword_text="MSCI",
        )
        session.add(scene)
        await session.commit()
        ids = (project.id, script.id, scene.id)
    yield factory, ids
    await engine.dispose()


async def test_render_hash_parts_includes_keyword_text(hash_world):
    factory, (project_id, script_id, _scene_id) = hash_world
    async with factory() as session:
        project = await session.get(Project, project_id)
        script = await session.get(Script, script_id)
        parts, _per_scene = await render_hash_parts(session, project, script, {})
    assert parts["scenes"][0]["keyword_text"] == "MSCI"


async def test_render_job_composites_keyword_before_ffmpeg(tmp_path, monkeypatch):
    """run_render_job: scene ber-keyword_text masuk plan dengan image_path
    file komposit di direktori keyword-*; isi file-nya PNG yang pita
    atasnya sudah berubah."""
    from pathlib import Path

    import app.jobs.render as render_job
    from app.config import Settings
    from app.db.models import GenerationJob
    from app.jobs.queue import enqueue
    from app.services import assets as asset_service
    from app.services.ffmpeg_render import RenderResult

    cfg = Settings(app_secret_key="rahasia-tes", storage_path=tmp_path / "storage")
    monkeypatch.setattr("app.jobs.render.get_settings", lambda: cfg)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/job.db")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            project = Project(title="P", topic="t")
            session.add(project)
            await session.flush()
            script = Script(
                project_id=project.id, version=1, status="approved",
                title="N", hook="H",
            )
            session.add(script)
            await session.flush()
            project.active_script_id = script.id
            scene = Scene(
                script_id=script.id, position=1, voiceover="ihsg turun",
                visual_prompt="v", visual_type="character", est_duration_s=3.0,
                keyword_text="MSCI",
            )
            session.add(scene)
            await session.flush()
            source_png = _white_png()
            for kind, key, mime, payload in (
                ("voice_clip", f"assets/{project.id}/{scene.id}/voice.mp3",
                 "audio/mpeg", b"x" * 16),
                ("image", f"assets/{project.id}/{scene.id}/image.png",
                 "image/png", source_png),
            ):
                path = cfg.storage_path / key
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
                created = await asset_service.create_asset(
                    session, project_id=project.id, scene_id=scene.id,
                    kind=kind, storage_key=key, mime=mime,
                    size_bytes=len(payload),
                    duration_s=3.0 if kind == "voice_clip" else None,
                    input_hash=f"hash-{kind}", data={},
                )
                await asset_service.select_asset(session, created)
            job = await enqueue(
                session, type="render", input={}, project_id=project.id
            )
            await session.commit()
            job_id = job.id

        captured = {}

        async def fake_run_render(plan, *, workdir, **kwargs):
            captured["image_path"] = plan.scenes[0].image_path
            captured["image_bytes"] = Path(plan.scenes[0].image_path).read_bytes()
            video = workdir / "video.mp4"
            video.write_bytes(b"\x00" * 2048)
            (workdir / "subtitles.srt").write_text("1\n", encoding="utf-8")
            (workdir / "subtitles.ass").write_text(
                "[Script Info]\n", encoding="utf-8"
            )
            (workdir / "thumbnail.jpg").write_bytes(b"\xff\xd8" * 32)
            return RenderResult(
                video_path=video,
                srt_path=workdir / "subtitles.srt",
                ass_path=workdir / "subtitles.ass",
                thumbnail_path=workdir / "thumbnail.jpg",
                duration_s=plan.total_duration_s,
                encoder="libx264",
                render_seconds=1.5,
                warnings=[],
            )

        monkeypatch.setattr(render_job, "run_render", fake_run_render)
        async with factory() as session:
            job = await session.get(GenerationJob, job_id)
        result = await render_job.run_render_job(job, factory)
        assert result["cached"] is False
    finally:
        await engine.dispose()

    assert captured["image_path"].endswith("scene-1.png")
    assert "keyword-" in captured["image_path"]
    composited = Image.open(io.BytesIO(captured["image_bytes"]))
    assert composited.size == (1080, 1920)
    original = Image.open(io.BytesIO(source_png))
    assert composited.crop((0, 100, 1080, 300)).tobytes() != original.crop(
        (0, 100, 1080, 300)
    ).tobytes()


async def test_render_hash_changes_when_keyword_text_changes(hash_world):
    factory, (project_id, script_id, scene_id) = hash_world
    async with factory() as session:
        project = await session.get(Project, project_id)
        script = await session.get(Script, script_id)
        parts_before, _ = await render_hash_parts(session, project, script, {})
        scene = await session.get(Scene, scene_id)
        scene.keyword_text = "DIJUAL"
        await session.flush()
        parts_after, _ = await render_hash_parts(session, project, script, {})
    assert parts_before["scenes"][0]["keyword_text"] == "MSCI"
    assert parts_after["scenes"][0]["keyword_text"] == "DIJUAL"
    assert parts_before != parts_after
