"""Tugas 10 Fase 11: warning durasi render memakai rentang target proyek,
bukan hardcoded 30-40. Di bawah aturan baru (<45 dtk), video valid 20-29 dtk
tidak boleh kena warning palsu; proyek warisan dengan target lama tetap
dinilai terhadap targetnya sendiri."""

import subprocess
from pathlib import Path

from PIL import Image

from app.services.ffmpeg_render import duration_warning, run_render
from app.services.render_plan import SceneInput, WordTiming, build_render_plan

STYLE = {
    "font": "Plus Jakarta Sans", "size": 78, "outline": 6, "margin_v": 400,
    "max_width_px": 940, "max_chars": 28, "emphasis_color": "#FFD84D",
}


def test_valid_short_video_no_warning_new_default():
    # (a) 25 dtk dengan target proyek 0/45 -> TANPA warning.
    assert duration_warning(25.0, 0, 45) is None
    assert duration_warning(44.9, 0, 45) is None
    assert duration_warning(20.0, 0, 45) is None


def test_over_max_warning_mentions_project_target():
    # (b) 46 dtk dengan target maks 45 -> warning menyebut rentang target proyek.
    warning = duration_warning(46.0, 0, 45)
    assert warning is not None
    assert "46" in warning and "45" in warning


def test_legacy_target_project_still_sensible():
    # (c) Proyek yang masih membawa target lama 30/40 dinilai terhadap 30/40.
    assert duration_warning(35.0, 30, 40) is None
    low = duration_warning(25.0, 30, 40)
    assert low is not None and "30" in low and "40" in low
    high = duration_warning(42.0, 30, 40)
    assert high is not None and "30" in high and "40" in high


def _tiny_plan(tmp_path: Path):
    scenes = []
    for pos in (1, 2):
        image = tmp_path / f"img{pos}.png"
        Image.new("RGB", (1080, 1920), (30 * pos, 120, 60)).save(image)
        audio = tmp_path / f"aud{pos}.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i",
             "sine=frequency=440:duration=3", str(audio)],
            capture_output=True, check=True,
        )
        scenes.append(
            SceneInput(
                id=f"scene-{pos}", position=pos,
                image_path=str(image), audio_path=str(audio),
                trim=(0.0, 3.0), clip_duration_s=3.0,
                words=[WordTiming(word="cicak", start=0.0, end=0.5)],
                visual_type="character", voiceover="cicak",
            )
        )
    return build_render_plan(scenes=scenes, subtitle_style=STYLE)


async def test_run_render_uses_project_targets(tmp_path):
    plan = _tiny_plan(tmp_path)  # total ~6 dtk
    # Bawaan baru 0/45: video pendek sah, tanpa warning durasi.
    result = await run_render(plan, workdir=tmp_path / "out_default")
    assert result.warnings == []
    # Target proyek dipasang maks 5: 6 dtk harus kena warning rentang proyek.
    result2 = await run_render(
        plan, workdir=tmp_path / "out_max5", target_min_s=0, target_max_s=5
    )
    assert len(result2.warnings) == 1
    assert "5" in result2.warnings[0]
