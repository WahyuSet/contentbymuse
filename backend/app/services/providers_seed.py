import shutil

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Provider
from app.services.crypto import encrypt_secret

ROUTER_LLM_QUIRKS = {
    "system_role": False,
    "structured": "json_object",
    "strips_think": True,
    "max_concurrency": 4,
}


async def _find(session: AsyncSession, name: str) -> Provider | None:
    return (
        await session.execute(select(Provider).where(Provider.name == name))
    ).scalar_one_or_none()


async def seed_providers(session: AsyncSession, settings: Settings) -> None:
    """Seed provider awal dari .env (Spec §5.4). Idempoten berdasarkan nama."""
    if await _find(session, "LLM Fake (dry-run)") is None:
        session.add(
            Provider(
                name="LLM Fake (dry-run)",
                capability="llm",
                adapter="fake",
                enabled=True,
                priority=100,
            )
        )
    if settings.llm_base_url and await _find(session, "Router LLM") is None:
        encrypted = None
        hint = None
        if settings.llm_api_key:
            encrypted = encrypt_secret(settings.llm_api_key, settings.app_secret_key)
            hint = settings.llm_api_key[-4:]
        session.add(
            Provider(
                name="Router LLM",
                capability="llm",
                adapter="openai_compatible",
                base_url=settings.llm_base_url,
                api_key_encrypted=encrypted,
                api_key_hint=hint,
                default_model=settings.llm_model,
                quirks=dict(ROUTER_LLM_QUIRKS),
                enabled=True,
                priority=10,
            )
        )
    if await _find(session, "Suara Fake (dry-run)") is None:
        session.add(
            Provider(
                name="Suara Fake (dry-run)",
                capability="voice",
                adapter="fake",
                quirks={"default_voice": "fake-1"},
                enabled=True,
                priority=100,
            )
        )
    # Adapter muse_cli hanya berguna di VM Muse tempat CLI tts tersedia.
    if shutil.which("tts") and await _find(session, "Suara Muse (CLI)") is None:
        session.add(
            Provider(
                name="Suara Muse (CLI)",
                capability="voice",
                adapter="muse_cli",
                quirks={"default_voice": "avocado_v2:MAI_03"},
                enabled=True,
                priority=20,
            )
        )
    if await _find(session, "Gambar Fake (dry-run)") is None:
        session.add(
            Provider(
                name="Gambar Fake (dry-run)",
                capability="image",
                adapter="fake",
                enabled=True,
                priority=100,
            )
        )
    if (
        shutil.which("media-generation")
        and await _find(session, "Gambar Muse (CLI)") is None
    ):
        session.add(
            Provider(
                name="Gambar Muse (CLI)",
                capability="image",
                adapter="muse_cli",
                quirks={"timeout_s": 600},
                enabled=True,
                priority=20,
            )
        )
    await session.flush()
