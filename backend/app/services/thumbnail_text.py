import io

from PIL import Image, ImageDraw, ImageFont

from app.services.render_settings import FONT_FILE

MAX_WIDTH_PX = 940
MAX_LINES = 3


def _wrap(draw: ImageDraw.ImageDraw, text: str, font) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= MAX_WIDTH_PX or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit_lines(draw: ImageDraw.ImageDraw, text: str, size_start: int,
               max_lines: int) -> tuple[list[str], object]:
    """Pilih ukuran font + pecah baris agar teks muat max_lines baris."""
    size = size_start
    lines: list[str] = []
    font = ImageFont.truetype(str(FONT_FILE), size)
    while size > 60:
        font = ImageFont.truetype(str(FONT_FILE), size)
        lines = _wrap(draw, text.upper(), font)
        if len(lines) <= max_lines:
            break
        size -= 14
    return lines[:max_lines], font


def _draw_lines(draw: ImageDraw.ImageDraw, image_width: int, lines, font,
                y: int, size: int) -> None:
    line_height = int(size * 1.12)
    for line in lines:
        x = (image_width - draw.textlength(line, font=font)) / 2
        draw.text(
            (x, y),
            line,
            font=font,
            fill=(255, 255, 255),
            stroke_width=max(6, size // 14),
            stroke_fill=(20, 18, 16),
        )
        y += line_height


def _draw_top_text(
    image_bytes: bytes,
    text: str,
    *,
    size_start: int,
    y: int,
    max_lines: int,
) -> bytes:
    """Gambar teks besar rata tengah di area atas gambar (font subtitle yang
    sama, putih bergaris tepi hitam tebal, ukuran menyusut sampai muat
    `max_lines` baris). Generator gambar menolak menggambar teks tertentu,
    jadi teks selalu dirender lokal agar ejaannya persis."""
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    draw = ImageDraw.Draw(image)
    lines, font = _fit_lines(draw, text, size_start, max_lines)
    size = font.size
    _draw_lines(draw, image.width, lines, font, y, size)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def draw_title_text(image_bytes: bytes, title_text: str) -> bytes:
    """Komposit teks judul besar di sepertiga atas gambar thumbnail."""
    return _draw_top_text(
        image_bytes, title_text, size_start=170, y=110, max_lines=MAX_LINES
    )


def draw_keyword_text(image_bytes: bytes, text: str) -> bytes:
    """Komposit kata kunci scene (1–3 kata, HURUF BESAR) di pita atas gambar
    scene saat render, supaya pemirsa mute tetap menangkap inti scene.
    Teks kosong mengembalikan gambar apa adanya."""
    keyword = (text or "").strip()
    if not keyword:
        return image_bytes
    return _draw_top_text(
        image_bytes, keyword.upper(), size_start=150, y=90, max_lines=2
    )


def draw_keyword_overlay(text: str) -> bytes:
    """Fase 13: PNG transparan 1080×1920 berisi teks keyword saja (gaya sama
    dengan draw_keyword_text), untuk di-overlay ANIMASI di ffmpeg — teks
    meluncur + fade-in tiap awal scene, bukan ditempel statis ke gambar."""
    keyword = (text or "").strip()
    image = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    if keyword:
        draw = ImageDraw.Draw(image)
        lines, font = _fit_lines(draw, keyword, 150, 2)
        size = font.size
        for index, line in enumerate(lines):
            x = (1080 - draw.textlength(line, font=font)) / 2
            draw.text(
                (x, 90 + index * int(size * 1.12)),
                line,
                font=font,
                fill=(255, 255, 255, 255),
                stroke_width=max(6, size // 14),
                stroke_fill=(20, 18, 16, 255),
            )
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()
