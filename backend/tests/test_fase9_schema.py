"""Fase 9 Tugas 1: keyword_text per scene + beat impact."""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, ContentIdea, Project, Scene, Script
from app.domain.llm_outputs import SceneDraft
from app.jobs.script_chain import draft_payload
from app.main import create_app


def _scene_draft(**over) -> SceneDraft:
    base = {
        "beat": "main",
        "voiceover": "Narasi contoh yang cukup panjang",
        "subtitle": None,
        "visual_prompt": "A simple scene",
        "include_mascot": True,
        "visual_type": "character",
        "transition": "cut",
        "emphasis_words": [],
    }
    base.update(over)
    return SceneDraft(**base)


def test_scene_draft_accepts_keyword_text_and_impact_beat():
    draft = _scene_draft(beat="impact", keyword_text="IHSG -8%")
    assert draft.beat == "impact"
    assert draft.keyword_text == "IHSG -8%"


def test_scene_draft_keyword_text_defaults_to_none():
    draft = _scene_draft()
    assert draft.keyword_text is None


def test_scene_draft_rejects_bogus_beat():
    with pytest.raises(ValidationError):
        _scene_draft(beat="bogus")


def test_scene_draft_rejects_overlong_keyword_text():
    with pytest.raises(ValidationError):
        _scene_draft(keyword_text="x" * 25)


def test_scene_model_has_keyword_text_column():
    assert "keyword_text" in Scene.__table__.columns


def test_migration_0008_exists_and_adds_keyword_text():
    path = Path("alembic/versions/0008_keyword_text.py")
    assert path.exists(), "migration 0008_keyword_text.py missing"
    text = path.read_text(encoding="utf-8")
    assert 'revision = "0008"' in text
    assert 'down_revision = "0007"' in text
    assert "keyword_text" in text
    assert "scene" in text
    assert "add_column" in text
    assert "drop_column" in text


def test_draft_payload_includes_keyword_text():
    script = Script(project_id="01JP", version=1, title="Judul", hook="Hook")
    scene = Scene(
        script_id="01JS",
        position=1,
        beat="impact",
        voiceover="Narasi dampak ke dapur warga",
        visual_prompt="Visual",
        visual_type="character",
        keyword_text="HARGA NAIK",
    )
    payload = draft_payload(script, [scene])
    assert payload["scenes"][0]["keyword_text"] == "HARGA NAIK"
    assert payload["scenes"][0]["beat"] == "impact"


@pytest.fixture
def seeded(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/fase9.db")

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
                project_id=project.id, idea_id=idea.id, version=1, title="Aktif",
                hook="Hook scene satu", status="validated", job_id="01JS1",
            )
            session.add(active)
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
            project.active_script_id = active.id
            await session.commit()
            return factory, project.id, active.id, scene_ids

    factory, pid, active_id, scene_ids = asyncio.run(_setup())
    client = TestClient(create_app(session_factory=factory))
    return {
        "client": client, "factory": factory, "project_id": pid,
        "active_id": active_id, "scene_ids": scene_ids,
    }


def test_scene_api_create_patch_read_keyword_text(seeded):
    client = seeded["client"]
    created = client.post(
        f"/api/scripts/{seeded['active_id']}/scenes",
        json={
            "voiceover": "Harga pangan naik tajam minggu ini",
            "visual_prompt": "Market scene",
            "beat": "impact",
            "keyword_text": "HARGA NAIK",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["keyword_text"] == "HARGA NAIK"
    assert body["beat"] == "impact"

    scene_id = body["id"]
    patched = client.patch(
        f"/api/scenes/{scene_id}",
        json={"keyword_text": "PAKAN MAHAL"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["scene"]["keyword_text"] == "PAKAN MAHAL"

    detail = client.get(f"/api/scripts/{seeded['active_id']}").json()
    found = [s for s in detail["scenes"] if s["id"] == scene_id]
    assert found and found[0]["keyword_text"] == "PAKAN MAHAL"


def test_scene_api_patch_impact_beat_accepted_and_bogus_rejected(seeded):
    client = seeded["client"]
    scene_id = seeded["scene_ids"][1]
    ok = client.patch(f"/api/scenes/{scene_id}", json={"beat": "impact"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["scene"]["beat"] == "impact"

    bad = client.patch(f"/api/scenes/{scene_id}", json={"beat": "bogus"})
    assert bad.status_code == 422


def test_scene_api_patch_keyword_text_on_existing_scene(seeded):
    client = seeded["client"]
    scene_id = seeded["scene_ids"][0]
    response = client.patch(
        f"/api/scenes/{scene_id}", json={"keyword_text": "MSCI"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["scene"]["keyword_text"] == "MSCI"
    detail = client.get(f"/api/scripts/{seeded['active_id']}").json()
    assert detail["scenes"][0]["keyword_text"] == "MSCI"
