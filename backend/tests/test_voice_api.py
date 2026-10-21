import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.models import (
    Base,
    ContentIdea,
    GenerationJob,
    Project,
    Provider,
    Scene,
    Script,
)
from app.main import create_app
from app.services import assets as asset_service
from app.storage.local import LocalStorage


@pytest.fixture
def world(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/api.db")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    cfg = Settings(app_secret_key="rahasia-tes", storage_path=tmp_path / "storage")
    monkeypatch.setattr("app.api.assets.get_settings", lambda: cfg)

    async def _setup():
        async with factory() as session:
            conn = await session.connection()
            await conn.run_sync(Base.metadata.create_all)
            await session.commit()
        storage = LocalStorage(cfg.storage_path)
        await storage.put("assets/p/scene/voice_clip-v1.wav", b"RIFF-dummy", "audio/wav")
        async with factory() as session:
            voice = Provider(
                name="Suara Fake", capability="voice", adapter="fake",
                quirks={"default_voice": "fake-1"}, enabled=True, priority=100,
            )
            llm = Provider(
                name="LLM", capability="llm", adapter="fake", enabled=True, priority=10
            )
            session.add_all([voice, llm])
            project = Project(title="Cicak", topic="cicak")
            session.add(project)
            await session.flush()
            idea = ContentIdea(
                project_id=project.id, batch=1, position=1, title="Judul", job_id="01JI"
            )
            session.add(idea)
            await session.flush()
            script = Script(
                project_id=project.id, idea_id=idea.id, version=1, title="Naskah",
                hook="Hook", status="approved", job_id="01JS",
            )
            session.add(script)
            await session.flush()
            scene = Scene(
                script_id=script.id, position=1, beat="hook",
                voiceover="Narasi satu", visual_prompt="Visual",
                visual_type="character", est_duration_s=3.0,
            )
            session.add(scene)
            await session.flush()
            clip = await asset_service.create_asset(
                session,
                project_id=project.id,
                scene_id=scene.id,
                kind="voice_clip",
                storage_key="assets/p/scene/voice_clip-v1.wav",
                mime="audio/wav",
                size_bytes=10,
                duration_s=2.0,
                input_hash="h1",
                provider_id=voice.id,
            )
            await asset_service.select_asset(session, clip)
            project.selected_idea_id = idea.id
            project.active_script_id = script.id
            await session.commit()
            return {
                "project_id": project.id,
                "scene_id": scene.id,
                "voice_provider_id": voice.id,
                "llm_provider_id": llm.id,
            }

    ids = asyncio.run(_setup())
    client = TestClient(create_app(session_factory=factory))
    return {"client": client, "factory": factory, **ids}


def test_file_endpoint_serves_bytes(world):
    response = world["client"].get("/api/files/assets/p/scene/voice_clip-v1.wav")
    assert response.status_code == 200
    assert response.content == b"RIFF-dummy"
    assert response.headers["content-type"].startswith("audio/")


def test_file_endpoint_blocks_traversal(world):
    response = world["client"].get("/api/files/../secret.txt")
    assert response.status_code == 404


def test_scene_assets_list(world):
    response = world["client"].get(f"/api/scenes/{world['scene_id']}/assets")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["kind"] == "voice_clip"
    assert rows[0]["is_selected"] is True
    assert rows[0]["url"] == "/api/files/assets/p/scene/voice_clip-v1.wav"


def test_provider_voices(world):
    response = world["client"].get(
        f"/api/providers/{world['voice_provider_id']}/voices"
    )
    assert response.status_code == 200
    assert response.json() == [{"id": "fake-1", "name": "Suara Fake (2,5 kata/detik)"}]
    wrong = world["client"].get(f"/api/providers/{world['llm_provider_id']}/voices")
    assert wrong.status_code == 422
    assert wrong.json()["error"]["kind"] == "NotVoiceProvider"


def test_patch_project_voice_pin(world):
    client = world["client"]
    response = client.patch(
        f"/api/projects/{world['project_id']}",
        json={
            "voice_provider_id": world["voice_provider_id"],
            "voice_id": "fake-1",
            "voice_settings": {"speed": 110},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["voice_provider_id"] == world["voice_provider_id"]
    assert body["voice_id"] == "fake-1"
    assert body["voice_settings"] == {"speed": 110}

    bad = client.patch(
        f"/api/projects/{world['project_id']}",
        json={"voice_provider_id": world["llm_provider_id"]},
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["kind"] == "InvalidProvider"


def test_regenerate_voice(world):
    client = world["client"]
    response = client.post(f"/api/scenes/{world['scene_id']}/voice/regenerate")
    assert response.status_code == 202
    assert response.json()["created"] is True
    again = client.post(f"/api/scenes/{world['scene_id']}/voice/regenerate")
    assert again.json()["created"] is False

    async def _jobs():
        async with world["factory"]() as session:
            return (
                await session.execute(
                    select(GenerationJob).where(GenerationJob.type == "voice")
                )
            ).scalars().all()

    jobs = asyncio.run(_jobs())
    assert len(jobs) == 1
    assert jobs[0].input["force"] is True
    assert jobs[0].resource_key.startswith("voice:")
