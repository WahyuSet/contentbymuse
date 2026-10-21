import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import (
    Asset,
    Base,
    ContentIdea,
    GenerationJob,
    Project,
    Provider,
    PublishRecord,
    Scene,
    Script,
    VisualStyle,
)
from app.jobs.publish import run_publish
from app.main import create_app
from app.services.prompts import sync_prompts


@pytest.fixture
async def factory(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    from app.config import get_settings

    get_settings.cache_clear()
    storage = tmp_path / "storage"
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        await sync_prompts(session)
        session.add_all([
            Provider(name="Gambar Fake", capability="image", adapter="fake",
                     enabled=True, priority=100),
            Provider(name="LLM Fake", capability="llm", adapter="fake",
                     enabled=True, priority=100),
            VisualStyle(name="Gaya", style_text="flat doodle",
                        negative_text="photo",
                        mascot_anchor="Tikus Berdasi, a cartoon rat.",
                        image_params={}, is_default=True),
        ])
        project = Project(title="MSCI Turun Kelas", topic="MSCI")
        session.add(project)
        await session.flush()
        idea = ContentIdea(project_id=project.id, batch=1, position=1,
                           title="Ide uji yang cukup panjang", angle="a",
                           hook="h", why_it_works="w", fact_risk="low",
                           job_id="01JJOBIDEA")
        session.add(idea)
        await session.flush()
        project.selected_idea_id = idea.id
        script = Script(project_id=project.id, idea_id=idea.id, version=1,
                        status="approved", source="generated",
                        title="MSCI Turun Kelas", hook="Kabar panas!")
        session.add(script)
        await session.flush()
        project.active_script_id = script.id
        session.add(Scene(script_id=script.id, position=1,
                          voiceover="Kabar panas dari pasar",
                          visual_prompt="a cartoon rat reading a newspaper"))
        video_key = f"assets/{project.id}/render-v1/video.mp4"
        (storage / video_key).parent.mkdir(parents=True, exist_ok=True)
        (storage / video_key).write_bytes(b"video")
        render = Asset(project_id=project.id, scene_id=None, kind="render",
                       storage_key=video_key, mime="video/mp4",
                       input_hash="rh", is_selected=True, version=1,
                       data={"files": {"video": video_key}})
        thumb_key = f"assets/{project.id}/thumbnail-v1.png"
        (storage / thumb_key).write_bytes(b"png")
        thumbnail = Asset(project_id=project.id, scene_id=None,
                          kind="thumbnail", storage_key=thumb_key,
                          mime="image/png", input_hash="th",
                          is_selected=True, version=1, data={})
        metadata = Asset(
            project_id=project.id, scene_id=None, kind="metadata",
            storage_key=f"assets/{project.id}/metadata-v1.json",
            mime="application/json", input_hash="mh", is_selected=True,
            version=1,
            data={"render_id": None, "script_id": script.id,
                  "title": "Judul Publish", "description": "Deskripsi.",
                  "hashtags": ["tikusberdasi"], "fb_caption": "Caption."},
        )
        session.add_all([render, thumbnail, metadata])
        await session.flush()
        metadata.data = {**metadata.data, "render_id": render.id}
        await session.commit()
    yield maker
    await engine.dispose()


async def _arrange_reconcile(factory):
    import app.jobs.handlers  # noqa: F401
    from app.services.reconcile import reconcile

    async with factory() as session:
        pid = (await session.execute(select(Project.id))).scalar_one()
    await reconcile(pid, factory)
    return pid


async def test_reconcile_creates_records_and_publish_jobs(factory):
    pid = await _arrange_reconcile(factory)
    async with factory() as session:
        records = (await session.execute(select(PublishRecord))).scalars().all()
        assert {r.platform for r in records} == {"youtube", "facebook"}
        assert all(r.status == "queued" for r in records)
        jobs = (await session.execute(
            select(GenerationJob).where(GenerationJob.type == "publish")
        )).scalars().all()
        assert len(jobs) == 2
        assert {j.input["publish_id"] for j in jobs} == {r.id for r in records}
        assert pid


async def test_publish_handler_prepares_manifest(factory):
    await _arrange_reconcile(factory)
    async with factory() as session:
        job = (await session.execute(
            select(GenerationJob).where(GenerationJob.type == "publish")
        )).scalars().first()
    result = await run_publish(job, factory)
    async with factory() as session:
        record = await session.get(PublishRecord, result["publish_id"])
        assert record.status == "awaiting_upload"
    from app.config import get_settings

    manifest_path = (
        get_settings().storage_path / "publish" / record.id / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text())
    assert manifest["title"] == "Judul Publish"
    assert manifest["video_path"].endswith("video.mp4")
    assert manifest["thumbnail_path"].endswith("thumbnail-v1.png")


async def test_publish_handler_fails_on_script_mismatch(factory):
    await _arrange_reconcile(factory)
    async with factory() as session:
        metadata = (await session.execute(
            select(Asset).where(Asset.kind == "metadata")
        )).scalar_one()
        metadata.data = {**metadata.data, "script_id": "BUKANSCRIPT"}
        job = (await session.execute(
            select(GenerationJob).where(GenerationJob.type == "publish")
        )).scalars().first()
        await session.commit()
    from app.jobs.script_chain import ScriptInputError

    with pytest.raises(ScriptInputError):
        await run_publish(job, factory)
    async with factory() as session:
        record = await session.get(PublishRecord, job.input["publish_id"])
        assert record.status == "failed"
        assert "bukan aktif" in record.error


def _api_client(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/api.db")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            record = PublishRecord(
                project_id="01JPROJECT", render_id="01JRENDER",
                platform="youtube", status="awaiting_upload",
            )
            session.add(record)
            await session.commit()
            return maker, record.id

    maker, record_id = asyncio.run(_setup())
    return TestClient(create_app(session_factory=maker)), record_id


def test_publish_api_claim_and_result(tmp_path):
    client, record_id = _api_client(tmp_path)
    bad = client.post(f"/api/publish/{record_id}/result",
                      json={"status": "published"})
    assert bad.status_code == 422  # published tanpa url/external_id
    claimed = client.post(f"/api/publish/{record_id}/claim")
    assert claimed.status_code == 200
    assert claimed.json()["status"] == "uploading"
    assert claimed.json()["attempts"] == 1
    again = client.post(f"/api/publish/{record_id}/claim")
    assert again.status_code == 409
    done = client.post(
        f"/api/publish/{record_id}/result",
        json={"status": "published", "url": "https://youtu.be/abc",
              "external_id": "abc"},
    )
    assert done.status_code == 200
    assert done.json()["url"] == "https://youtu.be/abc"
    listed = client.get("/api/projects/01JPROJECT/publish")
    assert listed.json()[0]["status"] == "published"
    awaiting = client.get("/api/publish/awaiting")
    assert awaiting.json() == []
