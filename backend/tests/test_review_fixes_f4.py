from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.models import GenerationJob, Provider
from app.providers.errors import ProviderError
from app.providers.voice.muse_cli import MuseCliVoice
from app.services import assets as asset_service
from app.services.media_probe import sanitize_tts_text
from app.services.reconcile import reconcile
from tests.test_production_reconcile import _seed


async def test_reconcile_settles_when_fallback_provider_produced_clip(tmp_path):
    factory, project_id, _sid, scene_ids, _top_provider_id = await _seed(tmp_path)
    # Provider fallback: prioritas lebih rendah dari provider utama di _seed.
    async with factory() as session:
        fallback = Provider(
            name="Suara Cadangan", capability="voice", adapter="fake",
            quirks={"default_voice": "fake-1"}, enabled=True, priority=200,
        )
        session.add(fallback)
        await session.commit()
        fallback_id = fallback.id

    # Klip scene 1 dibuat provider fallback (hash dihitung dengan provider itu).
    async with factory() as session:
        from app.db.models import Scene

        scene_one = await session.get(Scene, scene_ids[0])
        digest = asset_service.voice_input_hash(
            text=sanitize_tts_text(scene_one.voiceover),
            previous_text=None,
            next_text=None,
            provider=fallback_id,
            model=None,
            voice="fake-1",
            voice_settings={},
        )
        clip = await asset_service.create_asset(
            session,
            project_id=project_id,
            scene_id=scene_ids[0],
            kind="voice_clip",
            storage_key="assets/f.wav",
            mime="audio/wav",
            size_bytes=10,
            input_hash=digest,
            provider_id=fallback_id,
        )
        await asset_service.select_asset(session, clip)
        timings = await asset_service.create_asset(
            session,
            project_id=project_id,
            scene_id=scene_ids[0],
            kind="word_timings",
            storage_key="assets/f.wav",
            mime="application/json",
            size_bytes=0,
            data={"words": [], "method": "provider", "clip_asset_id": clip.id},
            input_hash="t1",
            provider_id=fallback_id,
        )
        await asset_service.select_asset(session, timings)
        await session.commit()

    await reconcile(project_id, factory)
    async with factory() as session:
        jobs = (
            await session.execute(
                select(GenerationJob).where(GenerationJob.type == "voice")
            )
        ).scalars().all()
    # Scene 1 dianggap selesai walau klipnya dari fallback; scene lain tetap diantrekan.
    assert {j.scene_id for j in jobs} == {scene_ids[1], scene_ids[2]}


async def test_muse_cli_errors_not_retryable():
    adapter = MuseCliVoice(quirks={"cli_path": "/tidak/ada/tts"})
    from app.providers.base import VoiceRequest

    with pytest.raises(ProviderError) as excinfo:
        await adapter.synthesize(VoiceRequest(text="Halo", voice_id="x"))
    assert excinfo.value.retryable is False


def test_migration_0004_has_postgresql_where():
    migration = Path("alembic/versions/0004_voice.py").read_text(encoding="utf-8")
    assert "postgresql_where" in migration
