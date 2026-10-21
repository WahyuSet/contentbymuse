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


def draw_title_text(image_bytes: bytes, title_text: str) -> bytes:
    """Komposit teks judul besar di sepertiga atas gambar (font subtitle yang
    sama, putih bergaris tepi hitam tebal). Generator gambar menolak menggambar
    teks tertentu, jadi teks selalu dirender lokal agar ejaannya persis."""
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    draw = ImageDraw.Draw(image)
    size = 170
    while size > 60:
        font = ImageFont.truetype(str(FONT_FILE), size)
        lines = _wrap(draw, title_text.upper(), font)
        if len(lines) <= MAX_LINES:
            break
        size -= 14
    line_height = int(size * 1.12)
    y = 110
    for line in lines:
        x = (image.width - draw.textlength(line, font=font)) / 2
        draw.text(
            (x, y),
            line,
            font=font,
            fill=(255, 255, 255),
            stroke_width=max(6, size // 14),
            stroke_fill=(20, 18, 16),
        )
        y += line_height
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()
