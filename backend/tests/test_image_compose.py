import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, Scene, VisualStyle
from app.services.prompts import compose_image_prompt, sync_prompts


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        result = await sync_prompts(session)
        await session.commit()
    yield maker, result
    await engine.dispose()


def _style(**overrides):
    base = {
        "name": "Gaya Uji",
        "style_text": "flat   doodle  style",
        "negative_text": "photo",
        "mascot_anchor": "Si Klepon, a green-headed stick figure..",
        "image_params": {},
        "is_default": True,
    }
    base.update(overrides)
    return VisualStyle(**base)


def _scene(**overrides):
    base = {
        "script_id": "s1",
        "position": 1,
        "voiceover": "teks",
        "visual_prompt": "a cat sitting on a wall",
        "visual_type": "character",
        "include_mascot": True,
    }
    base.update(overrides)
    return Scene(**base)


async def test_prompt_sync_includes_image_compose(factory):
    _maker, result = factory
    assert result["templates"] >= 21


async def test_compose_golden(factory):
    maker, _result = factory
    async with maker() as session:
        prompt = await compose_image_prompt(session, _style(), _scene())
    # style_text dirapikan spasi gandanya
    assert "flat doodle style" in prompt
    assert "flat   doodle" not in prompt
    # jangkar maskot: tepat satu titik di akhir kalimatnya
    assert "stick figure." in prompt
    assert "stick figure.." not in prompt
    assert "a cat sitting on a wall" in prompt
    # character -> kalimat garis lantai ada
    assert "ground line" in prompt
    # blok zona aman + teks selalu ada
    assert "bottom quarter" in prompt
    assert "Bahasa Indonesia" in prompt
    # Addendum anti-hewan: scene bermaskot TIDAK menerima klausa anti-hewan
    # (maskot kita tikus — klausa itu akan kontradiksi).
    assert "NO animal characters" not in prompt


async def test_compose_without_mascot_and_object_type(factory):
    maker, _result = factory
    async with maker() as session:
        prompt = await compose_image_prompt(
            session,
            _style(),
            _scene(include_mascot=False, visual_type="object"),
        )
    assert "Si Klepon" not in prompt
    assert "ground line" not in prompt
    # Addendum anti-hewan: scene tanpa maskot WAJIB memuat klausa eksplisit
    # tanpa karakter hewan — hanya manusia generik, benda, dan latar.
    assert (
        "This scene contains NO animal characters of any kind"
        " — only generic human figures, objects and scenery." in prompt
    )
