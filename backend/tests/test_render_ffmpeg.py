from app.services.render_ffmpeg import build_ffmpeg_command
from app.services.render_plan import SceneInput, WordTiming, build_render_plan

STYLE = {
    "font": "Plus Jakarta Sans", "size": 78, "outline": 6, "margin_v": 580,
    "max_width_px": 940, "max_chars": 28, "emphasis_color": "#FFD84D",
}
ENCODER = ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]


def _scene(pos, **overrides):
    base = {
        "id": f"scene-{pos}",
        "position": pos,
        "image_path": f"/img/{pos}.png",
        "audio_path": f"/aud/{pos}.mp3",
        "trim": (0.1, 3.1),
        "clip_duration_s": 3.2,
        "words": [
            WordTiming(word=w, start=0.1 + i * 0.5, end=0.6 + i * 0.5)
            for i, w in enumerate(["satu", "dua", "tiga"])
        ],
        "visual_type": "character",
        "transition": "cut",
        "subtitle_override": None,
        "voiceover": "satu dua tiga",
        "emphasis_words": [],
    }
    base.update(overrides)
    return SceneInput(**base)


def _cmd(plan):
    return build_ffmpeg_command(
        plan,
        ass_path="/kerja/subtitles.ass",
        fonts_dir="/app/assets/fonts",
        output_path="/kerja/video.mp4",
        video_encoder_args=ENCODER,
    )


def test_command_shape_cut():
    plan = build_render_plan(scenes=[_scene(1), _scene(2)], subtitle_style=STYLE)
    args = _cmd(plan)
    joined = " ".join(args)
    assert args[0] == "ffmpeg"
    assert "zoompan" in joined
    assert "scale=2160:3840" in joined
    assert "concat=n=2:v=1:a=0" in joined
    assert "loudnorm=I=-14:TP=-1.5:LRA=11" in joined
    assert "ass=filename='/kerja/subtitles.ass':fontsdir='/app/assets/fonts'" in joined
    assert args[-1] == "/kerja/video.mp4"
    assert "h264_nvenc" not in joined


def test_command_dips_narration_at_scene_cuts():
    plan = build_render_plan(scenes=[_scene(1), _scene(2)], subtitle_style=STYLE)
    joined = " ".join(_cmd(plan))
    cut = plan.scenes[1].start_s
    assert f"if(between(t,{cut - 0.05:.3f},{cut + 0.35:.3f}),0.45,1)" in joined
    assert ":eval=frame[adip]" in joined


def test_command_crossfade_uses_xfade_and_tpad():
    plan = build_render_plan(
        scenes=[_scene(1), _scene(2, transition="crossfade")],
        subtitle_style=STYLE,
    )
    assert plan.scenes[1].transition_in == "crossfade"
    joined = " ".join(_cmd(plan))
    assert "xfade=transition=fade:duration=0.2667" in joined
    assert "tpad=start_mode=clone" in joined
    assert "tpad=stop_mode=clone" in joined
