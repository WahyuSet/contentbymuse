import io

from PIL import Image

TARGET = (1080, 1920)


class ImageNormalizeError(Exception):
    """Byte sumber bukan gambar yang bisa diverifikasi Pillow."""


def normalize_to_portrait(data: bytes) -> tuple[bytes, tuple[int, int]]:
    """Verifikasi + sesuaikan gambar ke 1080x1920 (Spec §4.8).

    Skala sampai menutupi bingkai (cover), lalu crop dengan titik pusat
    vertikal di 40% tinggi supaya subjek tengah-atas tetap utuh. Mengembalikan
    (byte PNG hasil, ukuran asal).
    """
    try:
        image = Image.open(io.BytesIO(data))
        image.verify()
        image = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as exc:
        raise ImageNormalizeError(
            "Hasil provider bukan gambar yang valid."
        ) from exc
    original = image.size
    target_w, target_h = TARGET
    scale = max(target_w / image.width, target_h / image.height)
    resized = image.resize(
        (round(image.width * scale), round(image.height * scale)),
        Image.LANCZOS,
    )
    left = (resized.width - target_w) // 2
    center_y = resized.height * 0.4
    top = min(max(round(center_y - target_h / 2), 0), resized.height - target_h)
    cropped = resized.crop((left, top, left + target_w, top + target_h))
    buffer = io.BytesIO()
    cropped.save(buffer, format="PNG")
    return buffer.getvalue(), original
