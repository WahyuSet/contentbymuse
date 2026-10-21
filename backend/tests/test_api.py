import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/api.db")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    import asyncio

    asyncio.run(_setup())
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return TestClient(create_app(session_factory=factory))


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_enqueue_and_read_back(client):
    response = client.post("/api/jobs", json={"type": "provider_test", "input": {"label": "x"}})
    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "queued"
    assert job["type"] == "provider_test"

    fetched = client.get(f"/api/jobs/{job['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == job["id"]

    listed = client.get("/api/jobs")
    assert [j["id"] for j in listed.json()] == [job["id"]]


def test_unsupported_type_uses_standard_error_shape(client):
    response = client.post("/api/jobs", json={"type": "script", "input": {}})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["kind"] == "UnsupportedJobType"
    assert body["error"]["message"]


def test_missing_job_is_404_standard_shape(client):
    response = client.get("/api/jobs/01J000000000000000000000")
    assert response.status_code == 404
    assert response.json()["error"]["kind"] == "NotFound"


def test_unexpected_error_uses_standard_shape(tmp_path):
    import asyncio

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/boom.db")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_setup())
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app(session_factory=factory)

    @app.get("/api/boom")
    async def boom():
        raise RuntimeError("meledak")

    boom_client = TestClient(app, raise_server_exceptions=False)
    response = boom_client.get("/api/boom")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["kind"] == "InternalError"
    assert "detail" not in body


def test_cancel_queued_job(client):
    job = client.post("/api/jobs", json={"type": "provider_test", "input": {}}).json()
    response = client.post(f"/api/jobs/{job['id']}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
