import io
import stat

import pytest
from PIL import Image

from app.providers.base import ImageRequest
from app.providers.errors import ProviderError
from app.providers.image.muse_cli import MuseCliImage
from app.providers.router import ProviderRouter
from app.services.image_normalize import ImageNormalizeError, normalize_to_portrait


def _png_bytes(size, color=(200, 30, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_normalize_landscape_and_square_become_portrait():
    for size in ((800, 600), (1000, 1000), (1152, 2048)):
        out, original = normalize_to_portrait(_png_bytes(size))
        assert original == size
        image = Image.open(io.BytesIO(out))
        assert image.size == (1080, 1920)
        assert image.mode == "RGB"


def test_normalize_rejects_non_image():
    with pytest.raises(ImageNormalizeError):
        normalize_to_portrait(b"bukan gambar")


def _fake_cli(tmp_path, monkeypatch):
    script = tmp_path / "media-generation"
    helper = tmp_path / "make.py"
    helper.write_text(
        "import io, json, sys\n"
        "from PIL import Image\n"
        "args = sys.argv[1:]\n"
        "outdir = args[args.index('--output-dir') + 1]\n"
        "conv = json.loads(args[args.index('--conversation-json') + 1])\n"
        "assert conv[-1]['text'], 'prompt kosong'\n"
        "import pathlib\n"
        "path = pathlib.Path(outdir) / 'media-generation-uji-0-abc.jpg'\n"
        "buf = io.BytesIO(); Image.new('RGB', (1152, 2048), (10, 120, 60)).save(buf, format='JPEG')\n"
        "path.write_bytes(buf.getvalue())\n"
        "print(json.dumps({'ok': True, 'media_paths': [str(path)]}))\n",
        encoding="utf-8",
    )
    script.write_text(f"#!/bin/sh\nexec python3 {helper} \"$@\"\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


async def test_muse_cli_image_happy_path(tmp_path, monkeypatch):
    cli = _fake_cli(tmp_path, monkeypatch)
    adapter = MuseCliImage(quirks={"cli_path": cli, "timeout_s": 30})
    result = await adapter.generate_image(
        ImageRequest(prompt="seekor kucing", aspect_ratio="9:16")
    )
    assert result.width == 1152 and result.height == 2048
    assert result.usage.images == 1
    Image.open(io.BytesIO(result.image)).verify()


async def test_muse_cli_image_missing_cli_not_retryable():
    adapter = MuseCliImage(quirks={"cli_path": "/tidak/ada/media-generation"})
    with pytest.raises(ProviderError) as excinfo:
        await adapter.generate_image(ImageRequest(prompt="x"))
    assert excinfo.value.retryable is False


async def test_router_build_image_and_expected(tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.models import Base, Project, Provider

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        fake = Provider(
            name="Gambar Fake", capability="image", adapter="fake",
            enabled=True, priority=100,
        )
        session.add(fake)
        project = Project(title="P", topic="t")
        session.add(project)
        await session.commit()
        from app.config import Settings

        router = ProviderRouter(session)
        adapter = await router.build_image(fake, Settings(app_secret_key="x"))
        assert adapter is not None
        expected = await router.expected_image(project)
        assert expected.id == fake.id
        project.image_provider_id = fake.id
        assert (await router.expected_image(project)).id == fake.id
    await engine.dispose()
