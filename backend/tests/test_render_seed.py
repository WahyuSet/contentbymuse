import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import AppSetting, Base
from app.services.render_settings import (
    DEFAULT_SUBTITLE_STYLE,
    FONT_FILE,
    get_subtitle_style,
)


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_subtitle_style_seeded_and_idempotent(factory):
    async with factory() as session:
        style = await get_subtitle_style(session)
        await session.commit()
    assert style["size"] == 78
    assert style["outline"] == 6
    assert style["margin_v"] == 400
    async with factory() as session:
        again = await get_subtitle_style(session)
        row = await session.get(AppSetting, "subtitle_style")
    assert again == style
    assert row.value == DEFAULT_SUBTITLE_STYLE


def test_bundled_font_is_extrabold():
    from fontTools.ttLib import TTFont

    assert FONT_FILE.exists()
    font = TTFont(FONT_FILE)
    assert font["OS/2"].usWeightClass == 800
    names = {
        font["name"].getDebugName(nid) for nid in (1, 2, 4, 16, 17)
    }
    assert any("Jakarta" in (name or "") for name in names)
