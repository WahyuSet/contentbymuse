import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.models import Base, Project, Provider, VisualStyle
from app.services.providers_seed import seed_providers
from app.services.styles_seed import seed_visual_styles


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_image_provider_seed_rows(factory):
    async with factory() as session:
        await seed_providers(session, Settings(app_secret_key="x"))
        await session.commit()
    async with factory() as session:
        rows = (
            await session.execute(
                select(Provider).where(Provider.capability == "image")
            )
        ).scalars().all()
    by_name = {r.name: r for r in rows}
    assert by_name["Gambar Fake (dry-run)"].priority == 100
    # CLI media-generation ada di VM ini, jadi baris muse_cli ikut tertanam.
    assert by_name["Gambar Muse (CLI)"].priority == 20
    assert by_name["Gambar Muse (CLI)"].adapter == "muse_cli"


async def test_default_visual_style_seeded_once(factory):
    async with factory() as session:
        await seed_visual_styles(session)
        await seed_visual_styles(session)
        await session.commit()
    async with factory() as session:
        styles = (await session.execute(select(VisualStyle))).scalars().all()
    assert len(styles) == 1
    style = styles[0]
    assert style.is_default is True
    assert style.reference_asset_id is None
    assert "rat" in style.mascot_anchor and "red necktie" in style.mascot_anchor
    assert style.mascot_anchor.endswith(".")


async def test_project_image_columns_default_none(factory):
    async with factory() as session:
        session.add(Project(title="P", topic="t"))
        await session.commit()
    async with factory() as session:
        project = (await session.execute(select(Project))).scalar_one()
    assert project.image_provider_id is None
    assert project.visual_style_id is None
