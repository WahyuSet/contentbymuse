import io
import math
import wave
from pathlib import Path

import pytest

from app.services.media_probe import (
    MediaProbeError,
    detect_trim,
    probe_duration_s,
    sanitize_tts_text,
)


def _wav_bytes(segments: list[tuple[float, float]]) -> bytes:
    rate = 8000
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        frames = bytearray()
        for seconds, freq in segments:
            count = int(seconds * rate)
            for i in range(count):
                value = int(6000 * math.sin(2 * math.pi * freq * i / rate)) if freq else 0
                frames += value.to_bytes(2, "little", signed=True)
        wav.writeframes(bytes(frames))
    return buffer.getvalue()


def test_sanitize_replaces_typographic_characters():
    raw = "“Halo” — cicak ‘menempel’ – di   dinding\nsekarang"
    assert sanitize_tts_text(raw) == '"Halo" - cicak \'menempel\' - di dinding sekarang'


async def test_probe_duration(tmp_path: Path):
    path = tmp_path / "a.wav"
    path.write_bytes(_wav_bytes([(3.0, 220.0)]))
    duration = await probe_duration_s(path)
    assert duration == pytest.approx(3.0, abs=0.1)


async def test_probe_rejects_non_audio(tmp_path: Path):
    path = tmp_path / "b.bin"
    path.write_bytes(b"bukan audio sama sekali")
    with pytest.raises(MediaProbeError):
        await probe_duration_s(path)


async def test_detect_trim_edges(tmp_path: Path):
    path = tmp_path / "c.wav"
    path.write_bytes(_wav_bytes([(1.0, 0.0), (1.0, 220.0), (1.0, 0.0)]))
    trim = await detect_trim(path, 3.0)
    assert trim is not None
    assert trim["start_s"] == pytest.approx(0.95, abs=0.1)
    assert trim["end_s"] == pytest.approx(2.05, abs=0.1)


async def test_detect_trim_none_for_full_tone(tmp_path: Path):
    path = tmp_path / "d.wav"
    path.write_bytes(_wav_bytes([(2.0, 220.0)]))
    assert await detect_trim(path, 2.0) is None


async def test_detect_trim_none_for_all_silence(tmp_path: Path):
    path = tmp_path / "e.wav"
    path.write_bytes(_wav_bytes([(2.0, 0.0)]))
    assert await detect_trim(path, 2.0) is None
