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
    import os

    os.environ["STORAGE_PATH"] = str(tmp_path / "storage")
    from app.config import get_settings

    get_settings.cache_clear()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/api.db")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            session.add(Project(id="01JPROJECT", title="Proyek Uji", topic="uji"))
            session.add(Asset(
                id="01JRENDER", project_id="01JPROJECT", scene_id=None,
                kind="render", storage_key="assets/x/video.mp4",
                mime="video/mp4", input_hash="rh", is_selected=True,
                version=1, data={},
            ))
            record = PublishRecord(
                project_id="01JPROJECT", render_id="01JRENDER",
                platform="youtube", status="awaiting_upload",
            )
            session.add(record)
            session.add(Asset(
                project_id="01JPROJECT", scene_id=None, kind="metadata",
                storage_key="assets/x/metadata.json",
                mime="application/json", input_hash="mh", is_selected=True,
                version=1,
                data={"render_id": "01JRENDER", "script_id": "01JSCRIPT",
                      "title": "Judul Lama — Penonton Wajib Tahu!",
                      "description": "Deskripsi lama.",
                      "hashtags": ["tikusberdasi"],
                      "fb_caption": "Caption lama."},
            ))
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


def test_publish_api_claim_stale_render_rejected(tmp_path):
    client, record_id = _api_client(tmp_path)

    async def _swap_render():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/api.db")
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            old = await session.get(Asset, "01JRENDER")
            old.is_selected = False
            session.add(Asset(
                id="01JRENDER2", project_id="01JPROJECT", scene_id=None,
                kind="render", storage_key="assets/x/video2.mp4",
                mime="video/mp4", input_hash="rh2", is_selected=True,
                version=2, data={},
            ))
            await session.commit()
        await engine.dispose()

    asyncio.run(_swap_render())
    response = client.post(f"/api/publish/{record_id}/claim")
    assert response.status_code == 409
    assert response.json()["error"]["kind"] == "PublishStale"


def test_publish_api_retry_failed_record(tmp_path):
    client, record_id = _api_client(tmp_path)

    async def _fail_record():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/api.db")
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            record = await session.get(PublishRecord, record_id)
            record.status = "failed"
            record.error = "Platform sedang gangguan"
            await session.commit()
        await engine.dispose()

    asyncio.run(_fail_record())
    retried = client.post(f"/api/publish/{record_id}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "queued"
    assert retried.json()["error"] is None
    again = client.post(f"/api/publish/{record_id}/retry")
    assert again.status_code == 409


async def test_reconcile_supersedes_old_render_and_reaps_stale_upload(factory):
    from datetime import UTC, datetime, timedelta

    import app.jobs.handlers  # noqa: F401
    from app.services.reconcile import reconcile

    pid = await _arrange_reconcile(factory)
    async with factory() as session:
        records = (await session.execute(select(PublishRecord))).scalars().all()
        yt = next(r for r in records if r.platform == "youtube")
        fb = next(r for r in records if r.platform == "facebook")
        yt.status = "awaiting_upload"
        fb.status = "uploading"
        fb.updated_at = datetime.now(UTC) - timedelta(hours=2)
        render1 = (await session.execute(
            select(Asset).where(Asset.kind == "render")
        )).scalar_one()
        render1.is_selected = False
        render2 = Asset(project_id=pid, scene_id=None, kind="render",
                        storage_key=render1.storage_key, mime="video/mp4",
                        input_hash="rh2", is_selected=True, version=2,
                        data={"files": {"video": render1.storage_key}})
        session.add(render2)
        metadata = (await session.execute(
            select(Asset).where(Asset.kind == "metadata")
        )).scalar_one()
        await session.flush()
        metadata.data = {**metadata.data, "render_id": render2.id}
        await session.commit()
        render2_id = render2.id
    await reconcile(pid, factory)
    async with factory() as session:
        records = (await session.execute(select(PublishRecord))).scalars().all()
        old = [r for r in records if r.render_id != render2_id]
        new = [r for r in records if r.render_id == render2_id]
        assert {r.status for r in old} == {"superseded"}
        assert len(new) == 2


def test_revise_metadata_updates_asset_and_manifest(tmp_path):
    client, record_id = _api_client(tmp_path)
    manifest_dir = tmp_path / "storage" / "publish" / record_id
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "manifest.json").write_text(json.dumps({
        "publish_id": record_id, "title": "Judul Lama — Penonton Wajib Tahu!",
        "description": "Deskripsi lama.", "hashtags": ["tikusberdasi"],
        "fb_caption": "Caption lama.",
    }))
    response = client.post(
        "/api/projects/01JPROJECT/metadata/revise",
        json={"title": "OJK Denda 3 Emiten, Total 2,1 T!!",
              "fb_caption": "OJK denda 3 emiten, total 2,1 T! #tikusberdasi"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "OJK Denda 3 Emiten, Total 2,1 T!!"
    assert body["manifests_updated"] == 1
    manifest = json.loads((manifest_dir / "manifest.json").read_text())
    assert manifest["title"] == "OJK Denda 3 Emiten, Total 2,1 T!!"
    assert manifest["fb_caption"].startswith("OJK denda 3 emiten")
    shown = client.get("/api/projects/01JPROJECT/metadata")
    assert shown.json()["title"] == "OJK Denda 3 Emiten, Total 2,1 T!!"
    bad = client.post("/api/projects/01JPROJECT/metadata/revise",
                      json={"title": "   "})
    assert bad.status_code == 422


async def _seed_reap_case(factory):
    """Dua project, rekor di tiap status: hanya uploading basi yang boleh
    kembali ke awaiting_upload."""
    from datetime import UTC, datetime, timedelta

    async with factory() as session:
        pids = []
        for title in ("Proyek A", "Proyek B"):
            project = Project(title=title, topic="uji")
            session.add(project)
            await session.flush()
            pids.append(project.id)
        old = datetime.now(UTC) - timedelta(hours=2)
        recs = {}
        recs["stale_a"] = PublishRecord(
            project_id=pids[0], render_id="RA", platform="youtube",
            status="uploading",
        )
        recs["stale_b"] = PublishRecord(
            project_id=pids[1], render_id="RB", platform="facebook",
            status="uploading",
        )
        recs["fresh"] = PublishRecord(
            project_id=pids[0], render_id="RC", platform="facebook",
            status="uploading",
        )
        recs["published"] = PublishRecord(
            project_id=pids[0], render_id="RD", platform="youtube",
            status="published", url="https://youtu.be/x",
        )
        recs["failed"] = PublishRecord(
            project_id=pids[1], render_id="RE", platform="youtube",
            status="failed", error="x",
        )
        recs["awaiting"] = PublishRecord(
            project_id=pids[0], render_id="RF", platform="youtube",
            status="awaiting_upload",
        )
        for rec in recs.values():
            session.add(rec)
        await session.flush()
        for key in ("stale_a", "stale_b"):
            recs[key].updated_at = old
        ids = {k: r.id for k, r in recs.items()}
        await session.commit()
    return ids


async def test_reap_stale_uploads_service_cross_project(factory):
    from app.services.reconcile import reap_stale_uploads

    ids = await _seed_reap_case(factory)
    async with factory() as session:
        reaped = await reap_stale_uploads(session)
    assert reaped == 2
    async with factory() as session:
        got = {
            k: (await session.get(PublishRecord, rid)).status
            for k, rid in ids.items()
        }
    assert got["stale_a"] == "awaiting_upload"
    assert got["stale_b"] == "awaiting_upload"
    assert got["fresh"] == "uploading"
    assert got["published"] == "published"
    assert got["failed"] == "failed"
    assert got["awaiting"] == "awaiting_upload"


def test_reap_stale_endpoint(tmp_path):
    import os

    os.environ["STORAGE_PATH"] = str(tmp_path / "storage")
    from app.config import get_settings

    get_settings.cache_clear()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/reap.db")
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_setup())

    async def _seed():
        async with maker() as session:
            from datetime import UTC, datetime, timedelta

            project = Project(title="Proyek Reap", topic="uji")
            session.add(project)
            await session.flush()
            stale = PublishRecord(
                project_id=project.id, render_id="R1", platform="facebook",
                status="uploading",
            )
            fresh = PublishRecord(
                project_id=project.id, render_id="R1", platform="youtube",
                status="uploading",
            )
            session.add_all([stale, fresh])
            await session.flush()
            stale.updated_at = datetime.now(UTC) - timedelta(hours=1)
            await session.commit()
            return stale.id, fresh.id

    stale_id, fresh_id = asyncio.run(_seed())
    client = TestClient(create_app(session_factory=maker))
    resp = client.post("/api/publish/reap-stale")
    assert resp.status_code == 200
    assert resp.json() == {"reaped": 1}

    async def _check():
        async with maker() as session:
            s = await session.get(PublishRecord, stale_id)
            f = await session.get(PublishRecord, fresh_id)
            return s.status, f.status

    assert asyncio.run(_check()) == ("awaiting_upload", "uploading")
    # Kosong berikutnya: tidak ada yang dilepas lagi.
    assert client.post("/api/publish/reap-stale").json() == {"reaped": 0}


@pytest.mark.asyncio
async def test_reconcile_reprepares_after_upload_failure_retry(factory):
    """Regresi: retry atas rekor yang gagal di tahap UPLOAD (job penyiapan
    pertamanya completed) harus mengantrekan job penyiapan segar — dedup
    enqueue_once dulu mengembalikan job completed itu dan retry macet."""
    from app.services.reconcile import reconcile

    pid = await _arrange_reconcile(factory)
    async with factory() as session:
        record = (
            await session.execute(
                select(PublishRecord).where(PublishRecord.platform == "facebook")
            )
        ).scalar_one()
        jobs = (
            await session.execute(
                select(GenerationJob).where(GenerationJob.type == "publish")
            )
        ).scalars().all()
        job = next(
            j for j in jobs if (j.input or {}).get("publish_id") == record.id
        )
        job.status = "completed"  # penyiapan pertama berhasil…
        record.status = "failed"  # …tapi upload oleh eksekutor gagal
        await session.commit()
        record.status = "queued"  # retry_publish membalik ke queued
        await session.commit()
        record_id = record.id
    await reconcile(pid, factory)
    async with factory() as session:
        jobs = (
            await session.execute(
                select(GenerationJob).where(GenerationJob.type == "publish")
            )
        ).scalars().all()
        mine = [
            j for j in jobs if (j.input or {}).get("publish_id") == record_id
        ]
        assert len(mine) == 2
        assert sum(1 for j in mine if j.status == "queued") == 1
