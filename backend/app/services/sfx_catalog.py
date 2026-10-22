import math
from pathlib import Path

SFX_DIR = Path(__file__).resolve().parent.parent / "assets" / "sfx"

# id -> (nama tampil Bahasa Indonesia, gain bawaan 0..1, durasi detik)
# SFX EVENT (ding/boom/pop/cash/fall/drum/scratch/sparkle) DIHAPUS pada
# 2026-10-23 atas perintah pemilik — berkas WAV-nya dibuang dan entri
# katalognya dicabut; pemilik akan mengirim berkas event baru, daftarkan
# kembali di sini saat berkasnya tiba. Yang tersisa hanya whoosh transisi.
SFX_CATALOG: dict[str, dict] = {
    # whoosh.wav = berkas kiriman pemilik (2026-10-23), sudah dipangkas dari
    # mp3 0,98 dtk (isi suara efektif ~0,23 dtk) menjadi WAV 0,28 dtk.
    # Jangan timpa lewat scripts/build_sfx_library.py — resep sintesisnya
    # hanya cadangan.
    "whoosh": {"name": "Desis transisi", "gain": 0.35, "duration_s": 0.28},
}

TRANSITION_SFX = "whoosh"
# 0.85 (naik dari 0.3 pada 2026-10-23): pada gain lama whoosh tertutup narasi
# yang mengalir tanpa jeda sehingga transisi praktis tak terdengar (temuan
# pemilik); kini dipadukan peredaman narasi sesaat di titik potong.
TRANSITION_GAIN = 0.85


def is_valid_sfx(sfx_id: str) -> bool:
    return sfx_id in SFX_CATALOG


def sfx_path(sfx_id: str) -> Path:
    return SFX_DIR / f"{sfx_id}.wav"


def default_gain(sfx_id: str) -> float:
    return float(SFX_CATALOG[sfx_id]["gain"])


def sanitize_sfx_cues(cues, voiceover: str) -> list[dict]:
    """Saring cue dari LLM/pemilik: id sah, kata pemicu benar-benar ada di
    narasi, gain terikat 0.05-1.0, maksimal 2 cue per scene."""
    tokens = {t.strip(".,!?;:\"'").lower() for t in voiceover.split()}
    cleaned: list[dict] = []
    for cue in cues or []:
        if not isinstance(cue, dict):
            continue
        sfx_id = str(cue.get("sfx", ""))
        word = str(cue.get("word", "")).strip()
        if not is_valid_sfx(sfx_id) or word.lower() not in tokens:
            continue
        gain = cue.get("gain")
        entry: dict = {"sfx": sfx_id, "word": word}
        if gain is not None:
            try:
                value = float(gain)
            except (TypeError, ValueError):
                continue  # gain cacat: cue dibuang (API mengubahnya jadi 422)
            if not math.isfinite(value):
                continue
            entry["gain"] = min(1.0, max(0.05, value))
        cleaned.append(entry)
        if len(cleaned) >= 2:
            break
    return cleaned
