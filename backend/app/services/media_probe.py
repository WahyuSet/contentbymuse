import asyncio
import json
import re


class MediaProbeError(Exception):
    pass


_REPLACEMENTS = {
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
}


def sanitize_tts_text(text: str) -> str:
    for source, target in _REPLACEMENTS.items():
        text = text.replace(source, target)
    return re.sub(r"\s+", " ", text).strip()


async def _run(args: list[str], stdin: bytes | None = None) -> tuple[int, bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await process.communicate(stdin)
    return process.returncode or 0, out, err


async def probe_duration_s(path) -> float:
    code, out, _err = await _run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "json", str(path),
        ]
    )
    if code != 0:
        raise MediaProbeError(f"ffprobe gagal membaca durasi: {path}")
    try:
        return float(json.loads(out)["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MediaProbeError(f"Durasi tidak terbaca dari file: {path}") from exc


_SILENCE_START = re.compile(r"silence_start: ([\d.]+)")
_SILENCE_END = re.compile(r"silence_end: ([\d.]+)")


async def detect_trim(path, duration_s: float) -> dict | None:
    _code, _out, err = await _run(
        [
            "ffmpeg", "-v", "info", "-i", str(path),
            "-af", "silencedetect=noise=-45dB:d=0.25", "-f", "null", "-",
        ]
    )
    text = err.decode("utf-8", errors="replace")
    starts = [float(m) for m in _SILENCE_START.findall(text)]
    ends = [float(m) for m in _SILENCE_END.findall(text)]
    if not starts or not ends:
        return None
    start_s = 0.0
    end_s = duration_s
    # Hening pembuka: pasangan start/end pertama yang mulai di 0.
    if starts[0] <= 0.05 and ends:
        start_s = max(ends[0] - 0.05, 0.0)
    # Hening penutup: silence_start terakhir yang end-nya mencapai akhir klip.
    if len(starts) >= 1 and ends and abs(ends[-1] - duration_s) <= 0.1:
        end_s = min(starts[-1] + 0.05, duration_s)
    if start_s == 0.0 and end_s == duration_s:
        return None
    if end_s - start_s < 0.3:
        return None
    return {"start_s": round(start_s, 3), "end_s": round(end_s, 3)}
