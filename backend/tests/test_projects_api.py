import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.models import Base, ContentIdea, Project
from app.main import create_app
from app.services.prompts import sync_prompts
from app.services.providers_seed import seed_providers


@pytest.fixture
def client(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/api.db")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await sync_prompts(session)
            await seed_providers(session, Settings(app_secret_key="test-secret"))
            await session.commit()
        return factory

    factory = asyncio.run(_setup())
    return TestClient(create_app(session_factory=factory))


def test_create_project_needs_topic_or_category(client):
    response = client.post("/api/projects", json={})
    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "ProjectNeedsTopicOrCategory"


def test_create_and_read_project(client):
    response = client.post("/api/projects", json={"topic": "cicak"})
    assert response.status_code == 201
    project = response.json()
    assert project["title"] == "cicak"
    assert project["language"] == "id-ID"
    assert project["idea_count"] == 0
    fetched = client.get(f"/api/projects/{project['id']}")
    assert fetched.status_code == 200
    listed = client.get("/api/projects")
    assert [p["id"] for p in listed.json()] == [project["id"]]


def test_create_project_with_category_marks_source_user(client):
    categories = client.get("/api/categories").json()
    health = next(c for c in categories if c["slug"] == "health")
    response = client.post("/api/projects", json={"category_id": health["id"]})
    assert response.status_code == 201
    assert response.json()["category_source"] == "user"


def test_categories_and_formats_listed(client):
    categories = client.get("/api/categories").json()
    assert len(categories) == 5
    health = next(c for c in categories if c["slug"] == "health")
    assert health["fact_check"] == "strict"
    formats = client.get("/api/formats").json()
    assert len(formats) == 3


def test_generate_ideas_dedupes_active_job(client):
    project = client.post("/api/projects", json={"topic": "cicak"}).json()
    first = client.post(f"/api/projects/{project['id']}/ideas/generate")
    assert first.status_code == 202
    assert first.json()["created"] is True
    second = client.post(f"/api/projects/{project['id']}/ideas/generate")
    assert second.status_code == 202
    assert second.json()["created"] is False
    assert second.json()["job"]["id"] == first.json()["job"]["id"]


def test_list_ideas_empty(client):
    project = client.post("/api/projects", json={"topic": "cicak"}).json()
    assert client.get(f"/api/projects/{project['id']}/ideas").json() == []


def test_select_idea_sets_project(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/sel.db")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            project = Project(title="cicak", topic="cicak")
            session.add(project)
            await session.flush()
            idea = ContentIdea(
                project_id=project.id,
                batch=1,
                position=1,
                title="Judul ide terpilih yang panjang",
                job_id="01JTEST",
            )
            session.add(idea)
            await session.commit()
            return factory, project.id, idea.id

    factory, project_id, idea_id = asyncio.run(_setup())
    client = TestClient(create_app(session_factory=factory))
    response = client.post(f"/api/ideas/{idea_id}/select")
    assert response.status_code == 200
    body = response.json()
    assert body["selected_idea_id"] == idea_id
    assert body["title"] == "Judul ide terpilih yang panjang"


def test_providers_list_hides_key(client):
    providers = client.get("/api/providers").json()
    assert providers
    for provider in providers:
        assert "api_key_encrypted" not in provider
        assert "api_key" not in provider
        assert provider["has_api_key"] is False
    adapters = client.get("/api/providers/adapters").json()
    fake = next(a for a in adapters if a["adapter"] == "fake" and a["capability"] == "llm")
    assert fake["dry_run"] is True
