from pathlib import Path

import pytest

from app.config import Settings
from app.db.models import Project, Provider
from app.providers.base import VoiceRequest
from app.providers.errors import ProviderError
from app.providers.router import ProviderRouter
from app.providers.voice.muse_cli import MuseCliVoice


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        app_secret_key="rahasia-tes",
        storage_path=tmp_path / "storage",
        database_url=f"sqlite+aiosqlite:///{tmp_path}/providers.db",
    )


async def test_build_voice_and_expected_voice(session, tmp_path):
    fake = Provider(
        name="Suara Fake", capability="voice", adapter="fake",
        quirks={"default_voice": "fake-1"}, enabled=True, priority=100,
    )
    muse = Provider(
        name="Suara Muse", capability="voice", adapter="muse_cli",
        quirks={"default_voice": "avocado_v2:MAI_03"}, enabled=True, priority=20,
    )
    session.add_all([fake, muse])
    await session.commit()
    router = ProviderRouter(session)
    adapter = await router.build_voice(fake, _settings(tmp_path))
    assert type(adapter).__name__ == "FakeVoice"
    voices = await adapter.list_voices()
    assert [v.id for v in voices] == ["fake-1"]

    project = Project(title="Cicak", topic="cicak")
    session.add(project)
    await session.commit()
    provider, voice_id = await router.expected_voice(project)
    # Tanpa pin: kandidat prioritas terkecil yang menang.
    assert provider.id == muse.id
    assert voice_id == "avocado_v2:MAI_03"

    project.voice_provider_id = fake.id
    project.voice_id = None
    provider, voice_id = await router.expected_voice(project)
    assert provider.id == fake.id
    assert voice_id == "fake-1"

    project.voice_id = "suara-pilihan"
    _provider, voice_id = await router.expected_voice(project)
    assert voice_id == "suara-pilihan"


async def test_expected_voice_none_without_candidates(session):
    router = ProviderRouter(session)
    project = Project(title="Cicak", topic="cicak")
    session.add(project)
    await session.commit()
    assert await router.expected_voice(project) is None


async def test_muse_cli_synthesize_with_fake_binary(tmp_path):
    cli = tmp_path / "tts"
    cli.write_text(
        "#!/bin/sh\n"
        "out=''\n"
        "prev=''\n"
        "for a in \"$@\"; do if [ \"$prev\" = '--output' ]; then out=\"$a\"; fi; prev=\"$a\"; done\n"
        "cat > /dev/null\n"
        "printf 'ID3PALSU' > \"$out\"\n"
    )
    cli.chmod(0o755)
    adapter = MuseCliVoice(quirks={"cli_path": str(cli)})
    result = await adapter.synthesize(
        VoiceRequest(text="Halo cicak", voice_id="avocado_v2:MAI_03", language="id-ID")
    )
    assert result.audio == b"ID3PALSU"
    assert result.word_timings is None
    assert adapter.caps.returns_timestamps is False
    voices = await adapter.list_voices()
    assert voices[0].id == "avocado_v2:MAI_03"


async def test_muse_cli_missing_binary_raises():
    adapter = MuseCliVoice(quirks={"cli_path": "/tidak/ada/tts"})
    with pytest.raises(ProviderError):
        await adapter.synthesize(VoiceRequest(text="Halo", voice_id="x"))
