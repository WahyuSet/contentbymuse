from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AppSetting


async def get_setting(session: AsyncSession, key: str, default=None):
    row = await session.get(AppSetting, key)
    return row.value if row is not None else default


async def set_setting(session: AsyncSession, key: str, value) -> None:
    row = await session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=value))
    else:
        row.value = value
    await session.flush()
