"""Unduh font Plus Jakarta Sans (OFL) dan bekukan bobot ExtraBold 800.

Sumber: repo google/fonts (lisensi OFL-1.1). Idempoten: berhenti bila berkas
tujuan sudah ada dan berbobot 800. Jalankan dari folder backend:
    .venv/bin/python scripts/bundle_font.py
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

URL = "https://github.com/google/fonts/raw/main/ofl/plusjakartasans/PlusJakartaSans%5Bwght%5D.ttf"
TARGET = Path(__file__).resolve().parent.parent / "app" / "assets" / "fonts" / "PlusJakartaSans-ExtraBold.ttf"


def _weight(path: Path) -> int | None:
    from fontTools.ttLib import TTFont

    try:
        font = TTFont(path)
        return font["OS/2"].usWeightClass
    except Exception:  # noqa: BLE001 - berkas rusak berarti dianggap belum ada
        return None


def main() -> int:
    if TARGET.exists() and _weight(TARGET) == 800:
        print(f"sudah ada: {TARGET}")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    raw = Path("/tmp/PlusJakartaSans[wght].ttf")
    print(f"mengunduh {URL}")
    urllib.request.urlretrieve(URL, raw)
    print(f"unduhan sha256: {hashlib.sha256(raw.read_bytes()).hexdigest()}")
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont

    font = TTFont(raw)
    instantiateVariableFont(font, {"wght": 800}, inplace=True)
    font.save(TARGET)
    assert _weight(TARGET) == 800
    print(f"tersimpan: {TARGET} ({TARGET.stat().st_size} byte)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
