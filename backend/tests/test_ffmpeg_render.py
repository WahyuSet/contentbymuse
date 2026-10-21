import subprocess
from pathlib import Path

from PIL import Image

from app.services.ffmpeg_render import detect_encoder, run_render
from app.services.media_probe import probe_duration_s
from app.services.render_plan import SceneInput, WordTiming, build_render_plan

STYLE = {
    "font": "Plus Jakarta Sans", "size": 78, "outline": 6, "margin_v": 580,
    "max_width_px": 940, "max_chars": 28, "emphasis_color": "#FFD84D",
}


def _make_assets(tmp_path: Path, pos: int) -> tuple[Path, Path]:
    image = tmp_path / f"img{pos}.png"
    Image.new("RGB", (1080, 1920), (30 * pos, 120, 60)).save(image)
    audio = tmp_path / f"aud{pos}.mp3"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=3", str(audio),
        ],
        capture_output=True,
        check=True,
    )
    return image, audio


async def test_detect_encoder_returns_known():
    name, args = detect_encoder()
    assert name in {"h264_nvenc", "libx264"}
    assert args[0] == "-c:v" and args[1] == name


async def test_run_render_produces_mp4(tmp_path):
    scenes = []
    for pos in (1, 2):
        image, audio = _make_assets(tmp_path, pos)
        scenes.append(
            SceneInput(
                id=f"scene-{pos}",
                position=pos,
                image_path=str(image),
                audio_path=str(audio),
                trim=(0.0, 3.0),
                clip_duration_s=3.0,
                words=[
                    WordTiming(word=w, start=i * 0.5, end=i * 0.5 + 0.5)
                    for i, w in enumerate(["cicak", "menempel", "dinding"])
                ],
                visual_type="character",
                voiceover="cicak menempel dinding",
            )
        )
    plan = build_render_plan(scenes=scenes, subtitle_style=STYLE)
    progress: list[float] = []
    result = await run_render(
        plan, workdir=tmp_path / "out", progress_cb=progress.append
    )
    assert result.video_path.exists()
    assert result.thumbnail_path.exists()
    assert result.srt_path.read_text(encoding="utf-8").count("-->") >= 1
    duration = await probe_duration_s(result.video_path)
    assert abs(duration - plan.total_duration_s) < 0.6
    assert progress and progress[-1] > 0
    info = _probe_stream(result.video_path)
    assert "1080" in info and "1920" in info and "h264" in info


def _probe_stream(path) -> str:
    return subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,codec_name",
            "-of", "csv=p=0", str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
