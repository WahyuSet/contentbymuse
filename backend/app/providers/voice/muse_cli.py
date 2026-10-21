import asyncio
import tempfile
from pathlib import Path
from typing import Any

from app.providers.base import Usage, VoiceCaps, VoiceInfo, VoiceRequest, VoiceResult
from app.providers.errors import ServerError

DEFAULT_VOICE = "avocado_v2:MAI_03"


def _fail(message: str, detail: str | None = None) -> ServerError:
    # Kegagalan CLI lokal bersifat tetap (biner hilang / format salah):
    # mengulanginya di mesin yang sama tidak akan mengubah hasil.
    error = ServerError(message, detail=detail)
    error.retryable = False
    return error


class MuseCliVoice:
    """TTS lewat CLI `tts` yang hanya ada di VM Muse (lihat ADJUSTMENTS.md)."""

    caps = VoiceCaps(returns_timestamps=False, supports_context=False)

    def __init__(self, quirks: dict[str, Any] | None = None):
        quirks = quirks or {}
        self._cli_path = quirks.get("cli_path") or "tts"
        self._timeout_s = float(quirks.get("timeout_s") or 300)

    async def list_voices(self) -> list[VoiceInfo]:
        return [VoiceInfo(id=DEFAULT_VOICE, name="Suara bawaan Muse TTS")]

    async def synthesize(self, req: VoiceRequest, ctx=None) -> VoiceResult:
        speed = int(req.voice_settings.get("speed") or 100)
        language = (req.language or "id-ID").split("-")[0]
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "clip.mp3"
            try:
                process = await asyncio.create_subprocess_exec(
                    self._cli_path,
                    "--text-stdin",
                    "--voice", req.voice_id,
                    "--language", language,
                    "--format", "mp3",
                    "--speed", str(speed),
                    "--output", str(out_path),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as exc:
                raise _fail(
                    "CLI tts tidak ditemukan di mesin ini.", detail=str(exc)
                ) from exc
            try:
                _out, err = await asyncio.wait_for(
                    process.communicate(req.text.encode("utf-8")),
                    timeout=self._timeout_s,
                )
            except TimeoutError as exc:
                process.kill()
                raise _fail("CLI tts melewati batas waktu.") from exc
            if process.returncode != 0 or not out_path.exists():
                raise _fail(
                    "CLI tts gagal membuat suara.",
                    detail=err.decode("utf-8", errors="replace")[:500],
                )
            audio = out_path.read_bytes()
        return VoiceResult(
            audio=audio,
            mime="audio/mpeg",
            word_timings=None,
            usage=Usage(characters=len(req.text)),
        )
