import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import Asset, Project, VoiceCalibration


async def test_asset_persists_with_selection(session):
    project = Project(title="Cicak", topic="cicak")
    session.add(project)
    await session.flush()
    asset = Asset(
        project_id=project.id,
        scene_id="01JSCENE",
        kind="voice_clip",
        version=1,
        storage_key="assets/x.mp3",
        mime="audio/mpeg",
        size_bytes=123,
        input_hash="abc",
        is_selected=True,
    )
    session.add(asset)
    await session.commit()
    assert asset.duration_s is None
    assert asset.data is None


async def test_only_one_selected_asset_per_group(session):
    project = Project(title="Cicak", topic="cicak")
    session.add(project)
    await session.flush()
    for version in (1, 2):
        session.add(
            Asset(
                project_id=project.id,
                scene_id="01JSCENE",
                kind="voice_clip",
                version=version,
                storage_key=f"assets/v{version}.mp3",
                mime="audio/mpeg",
                size_bytes=1,
                input_hash=f"h{version}",
                is_selected=True,
            )
        )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_project_level_selected_unique_with_null_scene(session):
    project = Project(title="Cicak", topic="cicak")
    session.add(project)
    await session.flush()
    for version in (1, 2):
        session.add(
            Asset(
                project_id=project.id,
                scene_id=None,
                kind="image",
                version=version,
                storage_key=f"assets/i{version}.png",
                mime="image/png",
                size_bytes=1,
                input_hash=f"i{version}",
                is_selected=True,
            )
        )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_voice_calibration_upsert(session):
    session.add(
        VoiceCalibration(provider_id="01JP", voice_id="fake-1", words_per_second=2.5, samples=1)
    )
    await session.commit()
    row = await session.get(VoiceCalibration, ("01JP", "fake-1"))
    assert row.words_per_second == 2.5
    row.words_per_second = 2.4
    row.samples = 2
    await session.commit()
    assert (await session.get(VoiceCalibration, ("01JP", "fake-1"))).samples == 2


async def test_project_voice_columns(session):
    project = Project(
        title="Cicak", topic="cicak", voice_id="fake-1", voice_settings={"speed": 110}
    )
    session.add(project)
    await session.commit()
    assert project.voice_settings == {"speed": 110}
    assert project.voice_provider_id is None
