from sqlalchemy import select

from app.config import Settings
from app.db.models import Provider
from app.providers.llm.openai_compatible import OpenAICompatibleLLM
from app.providers.router import ProviderRouter
from app.services.crypto import decrypt_secret, encrypt_secret
from app.services.providers_seed import seed_providers


def test_crypto_roundtrip():
    encrypted = encrypt_secret("rahasia-panjang", "app-secret-key")
    assert encrypted != b"rahasia-panjang"
    assert decrypt_secret(encrypted, "app-secret-key") == "rahasia-panjang"


async def test_seed_creates_fake_and_env_router(session):
    settings = Settings(
        app_secret_key="x" * 32,
        llm_base_url="http://llm.test/v1",
        llm_model="m1",
        llm_api_key="kunci-api-1234",
    )
    await seed_providers(session, settings)
    await session.commit()
    await seed_providers(session, settings)
    await session.commit()

    router = ProviderRouter(session)
    candidates = await router.candidates("llm")
    assert [p.name for p in candidates] == ["Router LLM", "LLM Fake (dry-run)"]
    router_provider = candidates[0]
    assert router_provider.api_key_hint == "1234"
    assert (
        decrypt_secret(router_provider.api_key_encrypted, settings.app_secret_key)
        == "kunci-api-1234"
    )
    built = await router.build_llm(router_provider, settings)
    assert isinstance(built, OpenAICompatibleLLM)

    all_providers = (await session.execute(select(Provider))).scalars().all()
    # Sejak Fase 4 seed juga menambah provider suara; yang diuji di sini baris LLM.
    assert len([p for p in all_providers if p.capability == "llm"]) == 2


async def test_seed_without_env_llm_only_fake(session):
    settings = Settings(app_secret_key="x" * 32)
    await seed_providers(session, settings)
    await session.commit()
    candidates = await ProviderRouter(session).candidates("llm")
    assert [p.adapter for p in candidates] == ["fake"]
