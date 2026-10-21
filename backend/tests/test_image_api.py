import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.models import (
    Base,
    ContentIdea,
    Project,
    Provider,
    Scene,
    Script,
    VisualStyle,
)
from app.main import create_app


@pytest.fixture
def world(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/api.db")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    cfg = Settings(app_secret_key="rahasia-tes", storage_path=tmp_path / "storage")
    monkeypatch.setattr("app.main.get_settings", lambda: cfg)

    async def _setup():
        async with factory() as session:
            conn = await session.connection()
            await conn.run_sync(Base.metadata.create_all)
            await session.commit()
        async with factory() as session:
            image = Provider(
                name="Gambar Fake", capability="image", adapter="fake",
                enabled=True, priority=100,
            )
            llm = Provider(
                name="LLM", capability="llm", adapter="fake", enabled=True,
                priority=10,
            )
            style = VisualStyle(
                name="Klepon Klasik", style_text="flat", negative_text="photo",
                mascot_anchor="Si Klepon, a green-headed stick figure.",
                image_params={}, is_default=True,
            )
            other = VisualStyle(
                name="Gaya Lain", style_text="bold", negative_text="",
                mascot_anchor="", image_params={}, is_default=False,
            )
            session.add_all([image, llm, style, other])
            project = Project(title="Cicak", topic="cicak")
            session.add(project)
            await session.flush()
            idea = ContentIdea(
                project_id=project.id, batch=1, position=1, title="Judul",
                job_id="01JI",
            )
            session.add(idea)
            await session.flush()
            script = Script(
                project_id=project.id, idea_id=idea.id, version=1, title="N",
                hook="H", status="approved", job_id="01JS",
            )
            session.add(script)
            await session.flush()
            scene = Scene(
                script_id=script.id, position=1, voiceover="narasi",
                visual_prompt="visual", visual_type="character",
                est_duration_s=3.0,
            )
            session.add(scene)
            project.selected_idea_id = idea.id
            project.active_script_id = script.id
            await session.commit()
            return {
                "project": project.id, "scene": scene.id,
                "image_provider": image.id, "llm": llm.id,
                "style": style.id, "other_style": other.id,
            }

    import asyncio

    ids = asyncio.run(_setup())
    app = create_app(session_factory=factory)
    with TestClient(app) as client:
        yield client, ids


def test_visual_styles_list_and_patch(world):
    client, ids = world
    styles = client.get("/api/visual-styles").json()
    assert styles[0]["name"] == "Klepon Klasik"  # default lebih dulu
    assert styles[0]["is_default"] is True
    patched = client.patch(
        f"/api/visual-styles/{ids['other_style']}",
        json={"style_text": "berani dan datar"},
    )
    assert patched.status_code == 200
    assert patched.json()["style_text"] == "berani dan datar"
    assert patched.json()["version"] == 2


def test_project_patch_image_pins(world):
    client, ids = world
    ok = client.patch(
        f"/api/projects/{ids['project']}",
        json={
            "image_provider_id": ids["image_provider"],
            "visual_style_id": ids["style"],
        },
    )
    assert ok.status_code == 200
    assert ok.json()["image_provider_id"] == ids["image_provider"]
    assert ok.json()["visual_style_id"] == ids["style"]
    bad_provider = client.patch(
        f"/api/projects/{ids['project']}", json={"image_provider_id": ids["llm"]}
    )
    assert bad_provider.status_code == 422
    assert bad_provider.json()["error"]["kind"] == "InvalidProvider"
    bad_style = client.patch(
        f"/api/projects/{ids['project']}",
        json={"visual_style_id": "01TIDAKADA000000000000000"},
    )
    assert bad_style.status_code == 422
    assert bad_style.json()["error"]["kind"] == "InvalidVisualStyle"


def test_regenerate_image(world):
    client, ids = world
    created = client.post(f"/api/scenes/{ids['scene']}/image/regenerate")
    assert created.status_code == 202
    assert created.json()["created"] is True
    again = client.post(f"/api/scenes/{ids['scene']}/image/regenerate")
    assert again.json()["created"] is False
