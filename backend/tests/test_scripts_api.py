import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, ContentIdea, Project, Scene, Script, ValidationResult
from app.main import create_app


@pytest.fixture
def seeded(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/api.db")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            project = Project(title="Cicak", topic="cicak")
            session.add(project)
            await session.flush()
            idea = ContentIdea(
                project_id=project.id, batch=1, position=1,
                title="Kenapa cicak bisa menempel di dinding dan tidak jatuh",
                job_id="01JIDEA",
            )
            session.add(idea)
            await session.flush()
            project.selected_idea_id = idea.id
            script = Script(
                project_id=project.id, idea_id=idea.id, version=1,
                title=idea.title, hook="Rahasia besar di balik cicak bisa menempel",
                claims_to_verify=[
                    "Cicak punya rambut mikroskopis di telapak kakinya",
                    "Klaim lama yang akan diganti validator",
                ],
                job_id="01JSCRIPT",
            )
            session.add(script)
            await session.flush()
            for pos in range(1, 11):
                session.add(Scene(
                    script_id=script.id, position=pos,
                    beat="hook" if pos == 1 else "main",
                    voiceover=f"Isi narasi scene nomor {pos} yang cukup panjang",
                    visual_prompt=f"Visual {pos}", visual_type="character",
                    est_duration_s=3.6,
                ))
            script.estimated_duration_s = 36.0
            session.add(ValidationResult(
                script_id=script.id, attempt=1, status="PASS", score=88,
                summary="Bagus", job_id="01JVAL",
                claims_to_verify=[
                    "Cicak punya rambut mikroskopis di telapak kaki",
                    "Klaim baru dari validator",
                ],
            ))
            project.active_script_id = script.id
            await session.commit()
            return factory, project.id, script.id

    factory, project_id, script_id = asyncio.run(_setup())
    client = TestClient(create_app(session_factory=factory))
    return client, project_id, script_id


def test_list_and_detail(seeded):
    client, project_id, script_id = seeded
    listed = client.get(f"/api/projects/{project_id}/scripts").json()
    assert len(listed) == 1 and listed[0]["version"] == 1
    detail = client.get(f"/api/scripts/{script_id}").json()
    assert len(detail["scenes"]) == 10
    assert detail["validation"]["status"] == "PASS"
    assert isinstance(detail["checks"], list)


def test_claims_merged_with_replacement(seeded):
    client, _pid, script_id = seeded
    claims = client.get(f"/api/scripts/{script_id}").json()["claims"]
    # Klaim validator yang mirip menggantikan klaim script di posisinya,
    # klaim baru validator ditambahkan di akhir.
    assert claims[0] == "Cicak punya rambut mikroskopis di telapak kaki"
    assert claims[1] == "Klaim lama yang akan diganti validator"
    assert claims[2] == "Klaim baru dari validator"


def test_approve_requires_claims_confirmation(seeded):
    client, _pid, script_id = seeded
    response = client.post(
        f"/api/scripts/{script_id}/approve", json={"claims_confirmed": False}
    )
    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "ClaimsNotConfirmed"


def test_approve_sets_active(seeded):
    client, project_id, script_id = seeded
    response = client.post(
        f"/api/scripts/{script_id}/approve", json={"claims_confirmed": True}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    project = client.get(f"/api/projects/{project_id}").json()
    assert project["active_script_id"] == script_id


def test_generate_without_selected_idea(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/g.db")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            project = Project(title="Kosong", topic="bebas")
            session.add(project)
            await session.commit()
            return factory, project.id

    factory, project_id = asyncio.run(_setup())
    client = TestClient(create_app(session_factory=factory))
    response = client.post(f"/api/projects/{project_id}/script/generate")
    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "NoIdeaSelected"


def test_generate_and_manual_validate_enqueue(seeded):
    client, project_id, script_id = seeded
    response = client.post(f"/api/projects/{project_id}/script/generate")
    assert response.status_code == 202
    assert response.json()["created"] is True
    again = client.post(f"/api/projects/{project_id}/script/generate")
    assert again.json()["created"] is False
    manual = client.post(f"/api/scripts/{script_id}/validate", json={})
    assert manual.status_code == 202
    assert manual.json()["job"]["input"]["auto_revise"] is False
    manual2 = client.post(f"/api/scripts/{script_id}/validate", json={})
    assert manual2.json()["created"] is False


def test_pipeline_shape(seeded):
    client, project_id, _sid = seeded
    body = client.get(f"/api/projects/{project_id}/pipeline").json()
    keys = [stage["key"] for stage in body["stages"]]
    assert keys == ["script", "validation"]
    assert body["stages"][0]["status"] in {"done", "pending", "running", "attention", "blocked"}
