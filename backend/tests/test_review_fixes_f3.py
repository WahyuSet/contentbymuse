import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, ContentIdea, Project, Scene, Script
from app.jobs import queue
from app.main import create_app
from app.services.reconcile import reconcile


@pytest.fixture
def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/fix.db")
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed(factory, *, scene_count=3):
    async with factory() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)
        await session.commit()
    async with factory() as session:
        project = Project(title="Cicak", topic="cicak")
        session.add(project)
        await session.flush()
        idea = ContentIdea(
            project_id=project.id, batch=1, position=1, title="Judul ide", job_id="01JI"
        )
        session.add(idea)
        await session.flush()
        project.selected_idea_id = idea.id
        script = Script(
            project_id=project.id, idea_id=idea.id, version=1, title="Naskah",
            hook="Hook scene pertama yang asli", status="validated", job_id="01JS",
        )
        session.add(script)
        await session.flush()
        scene_ids = []
        for pos in range(1, scene_count + 1):
            scene = Scene(
                script_id=script.id, position=pos,
                beat="hook" if pos == 1 else "main",
                voiceover=f"Narasi scene {pos} yang cukup panjang",
                visual_prompt=f"Visual {pos}", visual_type="character",
                est_duration_s=3.6,
            )
            session.add(scene)
            await session.flush()
            scene_ids.append(scene.id)
        project.active_script_id = script.id
        await session.commit()
        return project.id, script.id, scene_ids


async def test_reconcile_finalizes_when_chain_dead(factory):
    project_id, script_id, _scenes = await _seed(factory)
    async with factory() as session:
        project = await session.get(Project, project_id)
        project.active_script_id = None
        await session.commit()
    await reconcile(project_id, factory)
    async with factory() as session:
        project = await session.get(Project, project_id)
        assert project.active_script_id == script_id


async def test_reconcile_does_not_finalize_while_chain_active(factory):
    project_id, script_id, _scenes = await _seed(factory)
    async with factory() as session:
        project = await session.get(Project, project_id)
        project.active_script_id = None
        await queue.enqueue(
            session, type="validate",
            input={"script_id": script_id, "auto_revise": True}, project_id=project_id,
        )
        await session.commit()
    await reconcile(project_id, factory)
    async with factory() as session:
        project = await session.get(Project, project_id)
        assert project.active_script_id is None


def _client(factory):
    return TestClient(create_app(session_factory=factory))


async def test_approve_rejects_script_without_scenes(factory):
    _project_id, script_id, _scenes = await _seed(factory, scene_count=0)
    client = _client(factory)
    response = client.post(
        f"/api/scripts/{script_id}/approve", json={"claims_confirmed": True}
    )
    assert response.status_code == 409
    assert response.json()["error"]["kind"] == "EmptyScene"


async def test_delete_last_scene_clears_hook(factory):
    _pid, script_id, scene_ids = await _seed(factory, scene_count=1)
    client = _client(factory)
    response = client.delete(f"/api/scenes/{scene_ids[0]}")
    assert response.status_code == 200
    detail = client.get(f"/api/scripts/{script_id}").json()
    assert detail["scenes"] == []
    assert detail["hook"] == ""
    assert detail["estimated_duration_s"] == 0
