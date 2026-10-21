import dataclasses

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.errors import AppError, NotFoundError
from app.api.jobs import SessionDep
from app.db.models import Category, Format, Provider
from app.providers.registry import ADAPTERS

router = APIRouter(prefix="/api", tags=["catalog"])


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    name: str
    description: str
    fact_check: str
    enabled: bool


class FormatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    name: str
    description: str
    enabled: bool


class ProviderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    capability: str
    adapter: str
    base_url: str | None
    default_model: str | None
    enabled: bool
    priority: int
    has_api_key: bool = False
    api_key_hint: str | None = None


class AdapterOut(BaseModel):
    capability: str
    adapter: str
    dry_run: bool
    caps: dict


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(session: SessionDep):
    stmt = select(Category).where(Category.enabled.is_(True)).order_by(Category.name)
    return (await session.execute(stmt)).scalars().all()


@router.get("/formats", response_model=list[FormatOut])
async def list_formats(session: SessionDep):
    stmt = select(Format).where(Format.enabled.is_(True)).order_by(Format.name)
    return (await session.execute(stmt)).scalars().all()


@router.get("/providers", response_model=list[ProviderOut])
async def list_providers(session: SessionDep):
    stmt = select(Provider).order_by(Provider.capability, Provider.priority)
    rows = (await session.execute(stmt)).scalars().all()
    result = []
    for provider in rows:
        out = ProviderOut.model_validate(provider)
        out.has_api_key = provider.api_key_encrypted is not None
        out.api_key_hint = provider.api_key_hint
        result.append(out)
    return result


class VoiceOut(BaseModel):
    id: str
    name: str


@router.get("/providers/{provider_id}/voices", response_model=list[VoiceOut])
async def list_provider_voices(provider_id: str, session: SessionDep):
    provider = await session.get(Provider, provider_id)
    if provider is None:
        raise NotFoundError("Provider tidak ditemukan.")
    if provider.capability != "voice":
        raise AppError(422, "NotVoiceProvider", "Provider ini bukan provider suara.")
    from app.config import get_settings
    from app.providers.router import ProviderRouter

    adapter = await ProviderRouter(session).build_voice(provider, get_settings())
    voices = await adapter.list_voices()
    return [VoiceOut(id=v.id, name=v.name) for v in voices]


@router.get("/providers/adapters", response_model=list[AdapterOut])
async def list_adapters():
    result = []
    for (capability, adapter), cls in sorted(ADAPTERS.items()):
        caps = getattr(cls, "caps", None)
        result.append(
            AdapterOut(
                capability=capability,
                adapter=adapter,
                dry_run=adapter == "fake",
                caps=dataclasses.asdict(caps) if caps is not None else {},
            )
        )
    return result
