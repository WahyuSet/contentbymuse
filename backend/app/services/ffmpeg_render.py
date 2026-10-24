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
    """Kegagalan render dengan pesan yang aman ditampilkan ke pengguna.

    Render bersifat deterministik untuk masukan yang sama, jadi kegagalan
    tidak diulang otomatis oleh worker (rencana Fase 6 Task 4): ulangi manual
    lewat render paksa."""

    kind = "RenderError"
    retryable = False


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


def duration_warning(
    duration_s: float, target_min_s: int, target_max_s: int
) -> str | None:
    """Warning durasi hasil render terhadap rentang target PROYEK (Fase 11 T10).

    Semantik sama dengan run_checks naskah: pagar atas selalu berlaku; pagar
    bawah hanya bila proyek memasang target_min_s > 0. Dulu hardcoded 30-40
    sehingga video valid 20-29 dtk (sah di bawah aturan <45 dtk) kena warning
    palsu, dan proyek warisan dinilai terhadap rentang yang bukan miliknya.
    """
    if duration_s > target_max_s:
        if target_min_s > 0:
            return (
                f"Durasi video {duration_s:.1f} detik di luar rentang target "
                f"proyek {target_min_s}-{target_max_s} detik."
            )
        return (
            f"Durasi video {duration_s:.1f} detik di luar rentang target "
            f"proyek (maksimal {target_max_s} detik)."
        )
    if target_min_s > 0 and duration_s < target_min_s:
        return (
            f"Durasi video {duration_s:.1f} detik di luar rentang target "
            f"proyek {target_min_s}-{target_max_s} detik."
        )
    return None


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
    target_min_s: int = 0,
    target_max_s: int = 45,
) -> RenderResult:
    workdir.mkdir(parents=True, exist_ok=True)
    ass_path = workdir / "subtitles.ass"
    srt_path = workdir / "subtitles.srt"
    video_path = workdir / "video.mp4"
    ass_path.write_text(build_ass(plan.cues, plan.subtitle_style), encoding="utf-8")
    srt_path.write_text(build_srt(plan.cues), encoding="utf-8")

    # Fase 13: PNG keyword transparan per scene untuk overlay animasi.
    from app.services.thumbnail_text import draw_keyword_overlay

    keyword_paths: dict[int, str] = {}
    for i, scene in enumerate(plan.scenes):
        if scene.keyword_text:
            kw_path = workdir / f"keyword-{i}.png"
            kw_path.write_bytes(draw_keyword_overlay(scene.keyword_text))
            keyword_paths[i] = str(kw_path)

    timeout_s = max(600.0, plan.total_duration_s * 120)
    encoder_name, encoder_args = detect_encoder(ffmpeg)
    args = build_ffmpeg_command(
        plan,
        ass_path=str(ass_path),
        fonts_dir=str(FONTS_DIR),
        output_path=str(video_path),
        video_encoder_args=encoder_args,
        keyword_paths=keyword_paths,
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
                    try:
                        progress_cb(min(value / total_us, 1.0))
                    except Exception:  # noqa: BLE001, S110 - callback progres tak boleh membunuh render
                        pass

    async def _read_stderr():
        assert process.stderr is not None
        async for line in process.stderr:
            stderr_chunks.append(line)

    try:
        await asyncio.wait_for(
            asyncio.gather(_read_stdout(), _read_stderr()), timeout=timeout_s
        )
        returncode = await asyncio.wait_for(process.wait(), timeout=30)
    except TimeoutError:
        process.kill()
        raise RenderError(
            f"Render melewati batas waktu {int(timeout_s)} detik dan dihentikan."
        ) from None
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
    try:
        thumb_rc = await asyncio.wait_for(thumb_proc.wait(), timeout=60)
    except TimeoutError:
        thumb_proc.kill()
        thumb_rc = -1
    if thumb_rc != 0 or not thumb_path.exists():
        raise RenderError("Gagal mengambil bingkai thumbnail dari video.")
    warnings: list[str] = []
    warning = duration_warning(duration, target_min_s, target_max_s)
    if warning is not None:
        warnings.append(warning)
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
