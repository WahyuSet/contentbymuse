from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AppSetting

FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FONT_FILE = FONTS_DIR / "PlusJakartaSans-ExtraBold.ttf"

# Gaya subtitle bawaan (Spec §8.5): Plus Jakarta Sans ExtraBold 78px, putih
# outline hitam 6px, rata tengah, garis dasar y=1520 -> marginV 1920-1520=400.
# Posisi lebih rendah sesuai vonis pemilik Fase 11; tetap di atas zona UI
# ±15% terbawah.
DEFAULT_SUBTITLE_STYLE: dict = {
    "font": "Plus Jakarta Sans",
    "font_file": "PlusJakartaSans-ExtraBold.ttf",
    "size": 78,
    "outline": 6,
    "margin_v": 400,
    "max_width_px": 940,
    "max_chars": 28,
    "emphasis_color": "#FFD84D",
    "primary_color": "#FFFFFF",
}


async def get_subtitle_style(session: AsyncSession) -> dict:
    """Gaya subtitle dari app_setting; baris ditanam bawaan bila belum ada."""
    row = await session.get(AppSetting, "subtitle_style")
    if row is None:
        row = AppSetting(key="subtitle_style", value=dict(DEFAULT_SUBTITLE_STYLE))
        session.add(row)
        await session.flush()
        return dict(DEFAULT_SUBTITLE_STYLE)
    merged = dict(DEFAULT_SUBTITLE_STYLE)
    if isinstance(row.value, dict):
        merged.update(row.value)
    return merged
