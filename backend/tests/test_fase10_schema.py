"""Fase 10 Tugas 1: beat twist di enumerasi scene."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, ContentIdea, Project, Scene, Script
from app.domain.llm_outputs import SceneDraft
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


def test_scene_draft_accepts_twist_beat():
    draft = _scene_draft(beat="twist")
    assert draft.beat == "twist"


def test_scene_draft_rejects_twistx_beat():
    with pytest.raises(ValidationError):
        _scene_draft(beat="twistx")


@pytest.fixture
def seeded(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/fase10.db")

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


def test_scene_api_patch_twist_beat_accepted_and_bogus_rejected(seeded):
    client = seeded["client"]
    scene_id = seeded["scene_ids"][1]
    ok = client.patch(f"/api/scenes/{scene_id}", json={"beat": "twist"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["scene"]["beat"] == "twist"

    bad = client.patch(f"/api/scenes/{scene_id}", json={"beat": "twistx"})
    assert bad.status_code == 422
    assert "Beat tidak dikenal." in bad.text
