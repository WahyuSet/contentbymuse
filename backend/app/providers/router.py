from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Provider
from app.providers.registry import ADAPTERS
from app.services.crypto import decrypt_secret


class ProviderRouter:
    """Memilih provider aktif (Spec §5.3): enabled, terurut prioritas."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def candidates(self, capability: str, project=None) -> list[Provider]:
        stmt = (
            select(Provider)
            .where(Provider.capability == capability, Provider.enabled.is_(True))
            .order_by(Provider.priority, Provider.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def build_llm(self, provider: Provider, settings: Settings):
        adapter_cls = ADAPTERS.get(("llm", provider.adapter))
        if adapter_cls is None:
            raise LookupError(f"Adapter LLM '{provider.adapter}' tidak dikenal.")
        if provider.adapter == "fake":
            return adapter_cls()
        api_key = None
        if provider.api_key_encrypted:
            api_key = decrypt_secret(
                provider.api_key_encrypted, settings.app_secret_key
            )
        return adapter_cls(
            base_url=provider.base_url or "",
            api_key=api_key,
            default_model=provider.default_model,
            quirks=provider.quirks,
        )
