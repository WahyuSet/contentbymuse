"""QC deteksi bahasa klip suara (Fase 11 D.2).

Menangkap drift logat TTS: klip dinilai dari bahasa yang benar-benar
terdengar (faster-whisper, model yang sama dengan aligner), bukan dari
parameter bahasa yang diminta ke provider. Kejujuran teknis: Whisper sulit
membedakan id vs ms secara andal — QC ini menangkap drift kasar (Inggris)
dan memberi job voice kesempatan mengundi ulang sisanya; penilai akhir
tetap telinga pemilik.
"""

import os

PASS_THRESHOLD = 0.60
MAX_REGENERATIONS = 2


def evaluate_qc(language: str, probability: float) -> bool:
    """Klip lolos hanya bila terdeteksi Bahasa Indonesia cukup yakin."""
    return language == "id" and probability >= PASS_THRESHOLD


def rank_key(language: str, probability: float) -> tuple:
    """Kunci peringkat klip kandidat: lolos QC > bahasa id > probabilitas."""
    return (evaluate_qc(language, probability), language == "id", probability)


def qc_enabled() -> bool:
    """QC hanya berjalan bila WHISPER_MODEL terpasang (gerbang env, R6):
    worker produksi selalu memasangnya; lingkungan tanpa model (tes lama)
    melewati QC sepenuhnya."""
    return bool(os.environ.get("WHISPER_MODEL"))


def detect_language(audio_path) -> tuple[str, float]:
    """Deteksi bahasa satu klip memakai model aligner yang sama.

    transcribe dipanggil TANPA argumen language agar model bebas menebak;
    panggilan sinkron — job membungkusnya dengan asyncio.to_thread.
    """
    from app.services.aligner import _load_model

    model = _load_model(os.environ.get("WHISPER_MODEL", "small"))
    _segments, info = model.transcribe(str(audio_path))
    return info.language, info.language_probability
