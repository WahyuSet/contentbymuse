from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import VisualStyle

DEFAULT_STYLE_NAME = "Klepon Klasik"

_STYLE_TEXT = (
    "flat 2D hand-drawn doodle illustration, thin black ink outlines, "
    "muted colors on warm off-white paper texture, simple shapes, "
    "lots of empty space, cozy Indonesian everyday-life mood"
)
_MASCOT_ANCHOR = (
    "Si Klepon, a stick figure mascot with a big round bright-green head, "
    "a thin black stick body, and simple dot eyes with a cheerful expression."
)
_NEGATIVE_TEXT = (
    "photorealistic, 3d render, gradient shading, english text, watermark, "
    "logo, blurry, cluttered background, extra limbs"
)


async def seed_visual_styles(session: AsyncSession) -> None:
    """Gaya visual bawaan (Spec §2.1). Idempoten berdasarkan nama."""
    existing = (
        await session.execute(
            select(VisualStyle).where(VisualStyle.name == DEFAULT_STYLE_NAME)
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            VisualStyle(
                name=DEFAULT_STYLE_NAME,
                version=1,
                style_text=_STYLE_TEXT,
                negative_text=_NEGATIVE_TEXT,
                mascot_anchor=_MASCOT_ANCHOR,
                image_params={"size": "1024x1792"},
                is_default=True,
            )
        )
    await session.flush()


async def expected_style(session: AsyncSession, project) -> VisualStyle | None:
    """Gaya project: pin project, lalu gaya bawaan, lalu gaya pertama."""
    if project.visual_style_id:
        style = await session.get(VisualStyle, project.visual_style_id)
        if style is not None:
            return style
    style = (
        await session.execute(
            select(VisualStyle)
            .where(VisualStyle.is_default.is_(True))
            .order_by(VisualStyle.name)
        )
    ).scalars().first()
    if style is not None:
        return style
    return (
        await session.execute(select(VisualStyle).order_by(VisualStyle.name))
    ).scalars().first()
