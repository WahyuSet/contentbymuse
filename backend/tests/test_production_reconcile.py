from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import (
    Base,
    ContentIdea,
    GenerationJob,
    Project,
    Provider,
    Scene,
    Script,
    VoiceCalibration,
)
from app.services import assets as asset_service
from app.services.media_probe import sanitize_tts_text
from app.services.reconcile import reconcile


def _factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/prod.db")
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed(tmp_path, *, status="approved"):
    factory = _factory(tmp_path)
    async with factory() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)
        await session.commit()
    async with factory() as session:
        provider = Provider(
            name="Suara Fake", capability="voice", adapter="fake",
            quirks={"default_voice": "fake-1"}, enabled=True, priority=100,
        )
        session.add(provider)
        # Project warisan: klip fixture di-hash dengan voice_settings {} (dibuat
        # sebelum bawaan speed 110), jadi seed harus menetapkannya eksplisit.
        project = Project(title="Cicak", topic="cicak", voice_settings={})
        session.add(project)
        await session.flush()
        idea = ContentIdea(
            project_id=project.id, batch=1, position=1, title="Judul ide", job_id="01JI"
        )
        session.add(idea)
        await session.flush()
        script = Script(
            project_id=project.id, idea_id=idea.id, version=1, title="Naskah",
            hook="Hook", status=status, job_id="01JS",
        )
        session.add(script)
        await session.flush()
        scene_ids = []
        for pos in range(1, 4):
            scene = Scene(
                script_id=script.id, position=pos,
                beat="hook" if pos == 1 else "main",
                voiceover=(
                    f"Narasi scene nomor {pos} yang cukup panjang dan berisi banyak kata "
                    "supaya total durasi naskah berada di rentang target tiga puluh "
                    "sampai empat puluh detik"
                ),
                visual_prompt=f"Visual {pos}", visual_type="character",
                est_duration_s=3.6,
            )
            session.add(scene)
            await session.flush()
            scene_ids.append(scene.id)
        project.selected_idea_id = idea.id
        project.active_script_id = script.id
        await session.commit()
        return factory, project.id, script.id, scene_ids, provider.id


async def _voice_jobs(factory):
    async with factory() as session:
        return (
            await session.execute(
                select(GenerationJob).where(GenerationJob.type == "voice")
            )
        ).scalars().all()


async def test_reconcile_enqueues_voice_for_approved_script(tmp_path):
    factory, project_id, _sid, scene_ids, provider_id = await _seed(tmp_path)
    await reconcile(project_id, factory)
    jobs = await _voice_jobs(factory)
    assert len(jobs) == 3
    assert {j.scene_id for j in jobs} == set(scene_ids)
    assert all(j.resource_key == f"voice:{provider_id}" for j in jobs)
    # Panggilan kedua saat job masih antre: tidak dobel.
    await reconcile(project_id, factory)
    assert len(await _voice_jobs(factory)) == 3


async def test_reconcile_skips_scenes_with_matching_clip(tmp_path):
    factory, project_id, _sid, scene_ids, provider_id = await _seed(tmp_path)
    async with factory() as session:
        scene_one = await session.get(Scene, scene_ids[0])
        digest = asset_service.voice_input_hash(
            text=sanitize_tts_text(scene_one.voiceover),
            previous_text=None,
            next_text=None,
            provider=provider_id,
            model=None,
            voice="fake-1",
            voice_settings={},
        )
        clip = await asset_service.create_asset(
            session,
            project_id=project_id,
            scene_id=scene_ids[0],
            kind="voice_clip",
            storage_key="assets/x.wav",
            mime="audio/wav",
            size_bytes=10,
            input_hash=digest,
            provider_id=provider_id,
        )
        await asset_service.select_asset(session, clip)
        # Timing untuk klip ini juga sudah ada.
        timings = await asset_service.create_asset(
            session,
            project_id=project_id,
            scene_id=scene_ids[0],
            kind="word_timings",
            storage_key="assets/x.wav",
            mime="application/json",
            size_bytes=0,
            data={"words": [], "method": "provider", "clip_asset_id": clip.id},
            input_hash="t1",
            provider_id=provider_id,
        )
        await asset_service.select_asset(session, timings)
        await session.commit()
    await reconcile(project_id, factory)
    jobs = await _voice_jobs(factory)
    assert {j.scene_id for j in jobs} == {scene_ids[1], scene_ids[2]}


async def test_reconcile_no_production_before_approval(tmp_path):
    factory, project_id, _sid, _scenes, _pid = await _seed(tmp_path, status="validated")
    await reconcile(project_id, factory)
    assert await _voice_jobs(factory) == []


async def test_calibrated_wps_changes_checks(tmp_path):
    from app.jobs.script_chain import checks_for

    factory, project_id, script_id, _scenes, provider_id = await _seed(tmp_path)
    async with factory() as session:
        project = await session.get(Project, project_id)
        project.target_min_s = 30
        script = await session.get(Script, script_id)
        clean = await checks_for(session, project, script)
        assert all(i.code != "duration_range" for i in clean)
        session.add(
            VoiceCalibration(
                provider_id=provider_id, voice_id="fake-1",
                words_per_second=4.5, samples=10,
            )
        )
        await session.commit()
        sped = await checks_for(session, project, script)
        # Pada 4,5 kata/dtk estimasi jauh di bawah target min 30 dtk:
        # semantik baru = warning duration_short, bukan error duration_range.
        assert any(
            i.code == "duration_short" and i.severity == "warning" for i in sped
        )
        assert all(i.code != "duration_range" for i in sped)
