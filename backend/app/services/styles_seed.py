from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import VisualStyle

DEFAULT_STYLE_NAME = "Tikus Klasik"

_STYLE_TEXT = (
    "Flat 2D hand-drawn doodle illustration with a simple drawn background "
    "that shows where the scene takes place, such as a room, kitchen, street, "
    "or outdoors, with a few contextual props, calm muted colors, on warm "
    "off-white paper texture, the same thin, even line weight in every scene"
)
_MASCOT_ANCHOR = (
    "Tikus Berdasi, a cartoon grey rat with FIXED consistent proportions in "
    "every scene: a large head about half of his total height, a long "
    "pointed snout, big round ears, a round belly, short limbs and a long "
    "segmented tail, drawn with thin even black lineart. He always wears a "
    "black suit jacket, a white shirt and a bright red necktie, and usually "
    "carries a briefcase full of cash. His face uses one of five fixed "
    "expressions: a smug sly grin with half-closed eyes (default), a gleeful "
    "laugh while counting money, shocked wide-eyed panic when caught, a "
    "fake innocent wide smile with both paws raised, or an angry defensive "
    "scowl."
)
_NEGATIVE_TEXT = (
    "photorealistic, 3d render, gradient shading, english text, watermark, "
    "logo, blurry, cluttered background, extra limbs, realistic human face, "
    "likeness of a real person, inconsistent character proportions, chibi "
    "proportions, thick bold outlines, different character design, "
    "changing face"
)


async def seed_visual_styles(session: AsyncSession) -> None:
    """Gaya visual bawaan (Spec §2.1). Idempoten berdasarkan nama."""
    named = (
        await session.execute(
            select(VisualStyle).where(VisualStyle.name == DEFAULT_STYLE_NAME)
        )
    ).scalar_one_or_none()
    has_default = (
        await session.execute(
            select(VisualStyle.id).where(VisualStyle.is_default.is_(True))
        )
    ).first() is not None
    if named is None:
        session.add(
            VisualStyle(
                name=DEFAULT_STYLE_NAME,
                version=1,
                style_text=_STYLE_TEXT,
                negative_text=_NEGATIVE_TEXT,
                mascot_anchor=_MASCOT_ANCHOR,
                image_params={"size": "1024x1792"},
                is_default=not has_default,
            )
        )
    elif not has_default:
        named.is_default = True
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
