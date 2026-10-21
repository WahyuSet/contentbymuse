from pathlib import Path

SFX_DIR = Path(__file__).resolve().parent.parent / "assets" / "sfx"

# id -> (nama tampil Bahasa Indonesia, gain bawaan 0..1, durasi detik)
SFX_CATALOG: dict[str, dict] = {
    "ding": {"name": "Denting", "gain": 0.5, "duration_s": 0.5},
    "boom": {"name": "Dentuman", "gain": 0.7, "duration_s": 0.8},
    "whoosh": {"name": "Desis transisi", "gain": 0.35, "duration_s": 0.45},
    "pop": {"name": "Letupan", "gain": 0.5, "duration_s": 0.12},
    "cash": {"name": "Denting koin", "gain": 0.55, "duration_s": 0.35},
    "fall": {"name": "Meluncur turun", "gain": 0.55, "duration_s": 0.6},
    "drum": {"name": "Sting drum", "gain": 0.5, "duration_s": 0.3},
    "scratch": {"name": "Gesek piringan", "gain": 0.45, "duration_s": 0.4},
    "sparkle": {"name": "Kilau naik", "gain": 0.45, "duration_s": 0.5},
}

TRANSITION_SFX = "whoosh"
TRANSITION_GAIN = 0.3


def is_valid_sfx(sfx_id: str) -> bool:
    return sfx_id in SFX_CATALOG


def sfx_path(sfx_id: str) -> Path:
    return SFX_DIR / f"{sfx_id}.wav"


def default_gain(sfx_id: str) -> float:
    return float(SFX_CATALOG[sfx_id]["gain"])
