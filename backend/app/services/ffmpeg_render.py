import asyncio
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.services.media_probe import probe_duration_s
from app.services.render_ffmpeg import build_ffmpeg_command
from app.services.render_plan import RenderPlan
from app.services.render_settings import FONTS_DIR
from app.services.subtitles import build_ass, build_srt

NVENC_ARGS = ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "21"]
X264_ARGS = ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]

_ENCODER_CACHE: dict[str, tuple[str, list[str]]] = {}


class RenderError(Exception):
    """Kegagalan render dengan pesan yang aman ditampilkan ke pengguna."""


def detect_encoder(ffmpeg: str = "ffmpeg") -> tuple[str, list[str]]:
    """Deteksi NVENC dengan menyandikan satu bingkai uji (Spec §8.7).

    Hasil di-cache per path ffmpeg untuk proses ini; tanpa GPU hasilnya
    libx264.
    """
    if ffmpeg in _ENCODER_CACHE:
        return _ENCODER_CACHE[ffmpeg]
    result = subprocess.run(
        [
            ffmpeg, "-y", "-f", "lavfi", "-i",
            "color=c=black:s=1080x1920:r=30", "-frames:v", "1",
            *NVENC_ARGS[2:], "-c:v", "h264_nvenc", "-f", "null", "-",
        ],
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode == 0:
        detected = ("h264_nvenc", list(NVENC_ARGS))
    else:
        detected = ("libx264", list(X264_ARGS))
    _ENCODER_CACHE[ffmpeg] = detected
    return detected


@dataclass
class RenderResult:
    video_path: Path
    srt_path: Path
    ass_path: Path
    thumbnail_path: Path
    duration_s: float
    encoder: str
    render_seconds: float
    warnings: list[str] = field(default_factory=list)


async def run_render(
    plan: RenderPlan,
    *,
    workdir: Path,
    ffmpeg: str = "ffmpeg",
    progress_cb=None,
) -> RenderResult:
    workdir.mkdir(parents=True, exist_ok=True)
    ass_path = workdir / "subtitles.ass"
    srt_path = workdir / "subtitles.srt"
    video_path = workdir / "video.mp4"
    ass_path.write_text(build_ass(plan.cues, plan.subtitle_style), encoding="utf-8")
    srt_path.write_text(build_srt(plan.cues), encoding="utf-8")

    encoder_name, encoder_args = detect_encoder(ffmpeg)
    args = build_ffmpeg_command(
        plan,
        ass_path=str(ass_path),
        fonts_dir=str(FONTS_DIR),
        output_path=str(video_path),
        video_encoder_args=encoder_args,
    )
    args[2:2] = ["-progress", "pipe:1", "-nostats"]
    started = time.monotonic()
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    total_us = max(plan.total_duration_s * 1_000_000, 1.0)
    stderr_chunks: list[bytes] = []

    async def _read_stdout():
        assert process.stdout is not None
        async for line in process.stdout:
            if line.startswith(b"out_time_ms="):
                try:
                    value = float(line.split(b"=", 1)[1])
                except ValueError:
                    continue
                if progress_cb is not None:
                    progress_cb(min(value / total_us, 1.0))

    async def _read_stderr():
        assert process.stderr is not None
        async for line in process.stderr:
            stderr_chunks.append(line)

    await asyncio.gather(_read_stdout(), _read_stderr())
    returncode = await process.wait()
    render_seconds = time.monotonic() - started
    if returncode != 0:
        tail = b"".join(stderr_chunks[-8:]).decode("utf-8", errors="replace")
        raise RenderError(f"FFmpeg gagal merender video. {tail[-400:]}")
    if not video_path.exists() or video_path.stat().st_size == 0:
        raise RenderError("FFmpeg tidak menghasilkan berkas video.")
    duration = await probe_duration_s(video_path)
    if duration < plan.total_duration_s - 0.5:
        raise RenderError(
            f"Durasi hasil render {duration:.2f} detik jauh lebih pendek "
            f"dari rencana {plan.total_duration_s:.2f} detik."
        )
    thumb_path = workdir / "thumbnail.jpg"
    thumb_proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-y", "-ss", "0.5", "-i", str(video_path),
        "-frames:v", "1", "-q:v", "2", str(thumb_path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    if await thumb_proc.wait() != 0 or not thumb_path.exists():
        raise RenderError("Gagal mengambil bingkai thumbnail dari video.")
    warnings: list[str] = []
    if duration < 30 or duration > 40:
        warnings.append(
            f"Durasi video {duration:.1f} detik di luar rentang target 30-40 detik."
        )
    return RenderResult(
        video_path=video_path,
        srt_path=srt_path,
        ass_path=ass_path,
        thumbnail_path=thumb_path,
        duration_s=duration,
        encoder=encoder_name,
        render_seconds=render_seconds,
        warnings=warnings,
    )
