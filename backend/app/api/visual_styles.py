from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.errors import NotFoundError
from app.api.jobs import SessionDep
from app.db.models import VisualStyle

router = APIRouter(prefix="/api", tags=["visual-styles"])


class VisualStyleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    version: int
    style_text: str
    negative_text: str
    mascot_anchor: str
    reference_asset_id: str | None
    image_params: dict[str, Any] = {}
    is_default: bool
    created_at: datetime
    updated_at: datetime


class VisualStylePatch(BaseModel):
    name: str | None = None
    style_text: str | None = None
    negative_text: str | None = None
    mascot_anchor: str | None = None
    reference_asset_id: str | None = None
    image_params: dict[str, Any] | None = None


@router.get("/visual-styles", response_model=list[VisualStyleOut])
async def list_visual_styles(session: SessionDep):
    rows = (
        await session.execute(
            select(VisualStyle).order_by(
                VisualStyle.is_default.desc(), VisualStyle.name
            )
        )
    ).scalars()
    return [VisualStyleOut.model_validate(row) for row in rows]


@router.get("/visual-styles/{style_id}", response_model=VisualStyleOut)
async def get_visual_style(style_id: str, session: SessionDep):
    style = await session.get(VisualStyle, style_id)
    if style is None:
        raise NotFoundError("Gaya visual tidak ditemukan.")
    return VisualStyleOut.model_validate(style)


@router.patch("/visual-styles/{style_id}", response_model=VisualStyleOut)
async def patch_visual_style(
    style_id: str, body: VisualStylePatch, session: SessionDep
):
    style = await session.get(VisualStyle, style_id)
    if style is None:
        raise NotFoundError("Gaya visual tidak ditemukan.")
    data = body.model_dump(exclude_unset=True)
    changed = False
    for field in (
        "name",
        "style_text",
        "negative_text",
        "mascot_anchor",
        "reference_asset_id",
    ):
        if field in data and data[field] is not None:
            setattr(style, field, data[field])
            changed = True
    if "image_params" in data and data["image_params"] is not None:
        merged = dict(style.image_params or {})
        merged.update(data["image_params"])
        style.image_params = merged
        changed = True
    if changed:
        style.version += 1
    await session.commit()
    await session.refresh(style)
    return VisualStyleOut.model_validate(style)
