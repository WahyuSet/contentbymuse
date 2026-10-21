import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.models import Asset, Base, GenerationJob, Project, Scene, Script
from app.jobs.render import render_hash_parts
from app.main import create_app
from app.services import assets as asset_service
from app.services.render_settings import get_subtitle_style


@pytest.fixture
def world(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/api.db")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    cfg = Settings(app_secret_key="rahasia-tes", storage_path=tmp_path / "storage")
    monkeypatch.setattr("app.main.get_settings", lambda: cfg)

    async def _setup():
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
                script_id=script.id, position=1, voiceover="cicak",
                visual_prompt="v", visual_type="character", est_duration_s=3.0,
            )
            session.add(scene)
            await session.flush()
            for kind in ("voice_clip", "image"):
                created = await asset_service.create_asset(
                    session, project_id=project.id, scene_id=scene.id,
                    kind=kind, storage_key=f"k-{kind}", mime="x",
                    size_bytes=1, input_hash=f"h-{kind}", data={},
                )
                await asset_service.select_asset(session, created)
            await session.commit()
            style = await get_subtitle_style(session)
            await session.commit()
            parts, _ = await render_hash_parts(session, project, script, style)
            digest = asset_service.render_input_hash(parts)
            return {"project_id": project.id, "digest": digest}

    ids = asyncio.run(_setup())
    app = create_app(session_factory=factory)
    with TestClient(app) as client:
        yield client, ids, factory


def test_render_flow(world):
    client, ids, _factory = world
    pid = ids["project_id"]
    assert client.get(f"/api/projects/{pid}/render").json() is None
    created = client.post(f"/api/projects/{pid}/render", json={})
    assert created.status_code == 202
    assert created.json()["created"] is True
    again = client.post(f"/api/projects/{pid}/render", json={})
    assert again.json()["created"] is False


def test_render_up_to_date_and_force(world):
    client, ids, factory = world
    pid = ids["project_id"]

    async def _seed_render():
        async with factory() as session:
            job = (
                await session.execute(
                    select(GenerationJob).where(GenerationJob.type == "render")
                )
            ).scalars().first()
            if job is not None:
                job.status = "completed"
            asset = await asset_service.create_asset(
                session, project_id=pid, scene_id=None, kind="render",
                storage_key=f"assets/{pid}/render-v1/video.mp4",
                mime="video/mp4", size_bytes=10, duration_s=12.0,
                input_hash=ids["digest"],
                data={
                    "files": {"video": f"assets/{pid}/render-v1/video.mp4"},
                    "encoder": "libx264", "warnings": [],
                },
            )
            await asset_service.select_asset(session, asset)
            await session.commit()

    client.post(f"/api/projects/{pid}/render", json={})
    asyncio.run(_seed_render())
    resp = client.post(f"/api/projects/{pid}/render", json={})
    assert resp.status_code == 409
    assert resp.json()["error"]["kind"] == "RenderUpToDate"
    forced = client.post(f"/api/projects/{pid}/render", json={"force": True})
    assert forced.status_code == 202
    got = client.get(f"/api/projects/{pid}/render")
    assert got.json()["version"] == 1
    assert got.json()["files"]["video"].endswith("render-v1/video.mp4")


def test_render_not_approved(world):
    client, ids, factory = world
    pid = ids["project_id"]

    async def _unapprove():
        async with factory() as session:
            script = (await session.execute(select(Script))).scalar_one()
            script.status = "validated"
            await session.commit()

    asyncio.run(_unapprove())
    resp = client.post(f"/api/projects/{pid}/render", json={})
    assert resp.status_code == 409
    assert resp.json()["error"]["kind"] == "ScriptNotApproved"


def test_render_not_ready(world):
    client, ids, factory = world
    pid = ids["project_id"]

    async def _drop_image():
        async with factory() as session:
            image = (
                await session.execute(
                    select(Asset).where(Asset.kind == "image")
                )
            ).scalar_one()
            image.is_selected = False
            await session.commit()

    asyncio.run(_drop_image())
    resp = client.post(f"/api/projects/{pid}/render", json={})
    assert resp.status_code == 409
    assert resp.json()["error"]["kind"] == "RenderNotReady"
    assert "gambar" in resp.json()["error"]["message"]
