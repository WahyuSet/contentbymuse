import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, ContentIdea, Project, Scene, Script
from app.jobs import queue
from app.main import create_app


@pytest.fixture
def seeded(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/scenes.db")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
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
            active = Script(
                project_id=project.id, idea_id=idea.id, version=2, title="Aktif",
                hook="Hook scene satu versi aktif", status="validated", job_id="01JS2",
            )
            other = Script(
                project_id=project.id, idea_id=idea.id, version=1, title="Lama",
                hook="Hook lama", status="draft", job_id="01JS1",
            )
            session.add_all([active, other])
            await session.flush()
            scene_ids = []
            for pos in range(1, 11):
                scene = Scene(
                    script_id=active.id, position=pos,
                    beat="hook" if pos == 1 else "main",
                    voiceover=f"Narasi scene {pos} versi aktif yang rapi",
                    visual_prompt=f"Visual {pos}", visual_type="character",
                    est_duration_s=3.6,
                )
                session.add(scene)
                await session.flush()
                scene_ids.append(scene.id)
            other_scene = Scene(
                script_id=other.id, position=1, beat="hook",
                voiceover="Narasi versi lama", visual_prompt="Visual lama",
                visual_type="character", est_duration_s=3.0,
            )
            session.add(other_scene)
            project.active_script_id = active.id
            await session.commit()
            return factory, project.id, active.id, other.id, scene_ids, other_scene.id

    factory, pid, active_id, other_id, scene_ids, other_scene_id = asyncio.run(_setup())
    client = TestClient(create_app(session_factory=factory))
    return {
        "client": client, "factory": factory, "project_id": pid,
        "active_id": active_id, "other_id": other_id,
        "scene_ids": scene_ids, "other_scene_id": other_scene_id,
    }


def test_patch_scene_updates_revision_and_flag(seeded):
    client = seeded["client"]
    scene_id = seeded["scene_ids"][0]
    response = client.patch(
        f"/api/scenes/{scene_id}",
        json={"voiceover": "Hook baru yang menggantikan narasi lama"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["scene"]["voiceover"] == "Hook baru yang menggantikan narasi lama"
    assert body["scene"]["revision"] == 1
    detail = client.get(f"/api/scripts/{seeded['active_id']}").json()
    assert detail["edited_after_validation"] is True
    assert detail["hook"] == "Hook baru yang menggantikan narasi lama"


def test_patch_non_active_script_rejected(seeded):
    response = seeded["client"].patch(
        f"/api/scenes/{seeded['other_scene_id']}", json={"voiceover": "Apa pun"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["kind"] == "ScriptNotActive"


def test_patch_invalid_enum_rejected(seeded):
    response = seeded["client"].patch(
        f"/api/scenes/{seeded['scene_ids'][1]}", json={"beat": "ngawur"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "InvalidScene"


def test_patch_blocked_while_chain_job_active(seeded):
    factory = seeded["factory"]

    async def _enqueue():
        async with factory() as session:
            await queue.enqueue(
                session, type="validate",
                input={"script_id": seeded["active_id"], "auto_revise": True},
                project_id=seeded["project_id"],
            )
            await session.commit()

    asyncio.run(_enqueue())
    response = seeded["client"].patch(
        f"/api/scenes/{seeded['scene_ids'][1]}",
        json={"voiceover": "Narasi pengganti yang cukup panjang"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["kind"] == "ScriptBusy"


def test_add_delete_reorder_normalizes(seeded):
    client = seeded["client"]
    created = client.post(
        f"/api/scripts/{seeded['active_id']}/scenes",
        json={
            "voiceover": "Scene sisipan baru di tengah alur cerita",
            "visual_prompt": "Inserted visual",
            "after_position": 1,
        },
    )
    assert created.status_code == 201
    detail = client.get(f"/api/scripts/{seeded['active_id']}").json()
    assert [s["position"] for s in detail["scenes"]] == list(range(1, 12))
    assert detail["scenes"][1]["voiceover"].startswith("Scene sisipan")

    new_id = created.json()["id"]
    deleted = client.delete(f"/api/scenes/{new_id}")
    assert deleted.status_code == 200
    detail = client.get(f"/api/scripts/{seeded['active_id']}").json()
    assert [s["position"] for s in detail["scenes"]] == list(range(1, 11))

    ids = [s["id"] for s in detail["scenes"]]
    swapped = ids[1:] + ids[:1]
    reordered = client.post(
        f"/api/scripts/{seeded['active_id']}/scenes/reorder",
        json={"scene_ids": swapped},
    )
    assert reordered.status_code == 200
    detail = client.get(f"/api/scripts/{seeded['active_id']}").json()
    assert detail["scenes"][0]["id"] == swapped[0]
    # Hook mengikuti scene pertama yang baru.
    assert detail["hook"] == detail["scenes"][0]["voiceover"]

    bad = client.post(
        f"/api/scripts/{seeded['active_id']}/scenes/reorder",
        json={"scene_ids": ids[:3]},
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["kind"] == "InvalidSceneOrder"
