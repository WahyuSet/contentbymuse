from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Asset
from app.jobs.queue import sha256_of_json


async def next_version(
    session: AsyncSession, *, project_id: str | None, scene_id: str | None, kind: str
) -> int:
    current = (
        await session.execute(
            select(func.max(Asset.version)).where(
                Asset.project_id.is_(project_id)
                if project_id is None
                else Asset.project_id == project_id,
                Asset.scene_id.is_(scene_id)
                if scene_id is None
                else Asset.scene_id == scene_id,
                Asset.kind == kind,
            )
        )
    ).scalar()
    return (current or 0) + 1


async def create_asset(session: AsyncSession, **fields) -> Asset:
    version = await next_version(
        session,
        project_id=fields.get("project_id"),
        scene_id=fields.get("scene_id"),
        kind=fields["kind"],
    )
    asset = Asset(version=version, is_selected=False, **fields)
    session.add(asset)
    await session.flush()
    return asset


async def select_asset(session: AsyncSession, asset: Asset) -> None:
    # Turunkan pilihan lama lebih dulu dan flush: indeks parsial menjaga tepat
    # satu aset terpilih per (project, scene, kind) di setiap pernyataan SQL.
    group = (
        await session.execute(
            select(Asset).where(
                Asset.project_id.is_(asset.project_id)
                if asset.project_id is None
                else Asset.project_id == asset.project_id,
                Asset.scene_id.is_(asset.scene_id)
                if asset.scene_id is None
                else Asset.scene_id == asset.scene_id,
                Asset.kind == asset.kind,
                Asset.is_selected.is_(True),
                Asset.id != asset.id,
            )
        )
    ).scalars().all()
    for other in group:
        other.is_selected = False
    await session.flush()
    asset.is_selected = True
    await session.flush()


async def selected_asset(
    session: AsyncSession, *, project_id: str | None, scene_id: str | None, kind: str
) -> Asset | None:
    return (
        await session.execute(
            select(Asset).where(
                Asset.project_id.is_(project_id)
                if project_id is None
                else Asset.project_id == project_id,
                Asset.scene_id.is_(scene_id)
                if scene_id is None
                else Asset.scene_id == scene_id,
                Asset.kind == kind,
                Asset.is_selected.is_(True),
            )
        )
    ).scalar_one_or_none()


def voice_input_hash(
    *,
    text: str,
    previous_text: str | None,
    next_text: str | None,
    provider: str,
    model: str | None,
    voice: str,
    voice_settings: dict,
) -> str:
    return sha256_of_json(
        {
            "text": text,
            "previous_text": previous_text,
            "next_text": next_text,
            "provider": provider,
            "model": model,
            "voice": voice,
            "voice_settings": voice_settings,
        }
    )


def image_input_hash(
    *,
    prompt: str,
    negative_text: str | None,
    provider: str,
    model: str | None,
    params: dict,
    reference_hash: str | None,
) -> str:
    return sha256_of_json(
        {
            "prompt": prompt,
            "negative_text": negative_text,
            "provider": provider,
            "model": model,
            "params": params,
            "reference_hash": reference_hash,
        }
    )


def timings_input_hash(*, clip_input_hash: str, text: str, method: str) -> str:
    return sha256_of_json(
        {"clip_input_hash": clip_input_hash, "text": text, "method": method}
    )


async def update_calibration(
    session: AsyncSession, *, provider_id: str, voice_id: str, words: int, span_s: float
) -> None:
    """Rata-rata bergerak 20 sampel (Spec §4.6); sampel tak layak diabaikan."""
    from app.db.models import VoiceCalibration

    if words < 3 or span_s <= 0:
        return
    wps = words / span_s
    if wps < 1.0 or wps > 5.0:
        return
    row = await session.get(VoiceCalibration, (provider_id, voice_id))
    if row is None:
        row = VoiceCalibration(
            provider_id=provider_id, voice_id=voice_id, words_per_second=wps, samples=1
        )
        session.add(row)
    else:
        if row.samples < 20:
            row.words_per_second = (
                row.words_per_second * row.samples + wps
            ) / (row.samples + 1)
        else:
            row.words_per_second = row.words_per_second + (wps - row.words_per_second) / 20
        row.samples += 1
    await session.flush()


def render_input_hash(parts: dict) -> str:
    import hashlib
    import json

    return hashlib.sha256(
        json.dumps(parts, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
