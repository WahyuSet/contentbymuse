from app.services.render_plan import SceneInput, WordTiming, build_render_plan
from app.services.subtitles import build_ass, build_srt, chunk_words, measure_text_px

STYLE = {
    "font": "Plus Jakarta Sans",
    "size": 78,
    "outline": 6,
    "margin_v": 580,
    "max_width_px": 940,
    "max_chars": 28,
    "emphasis_color": "#FFD84D",
}


def _words(text: str, start=0.0, step=0.3):
    return [
        WordTiming(word=w, start=start + i * step, end=start + (i + 1) * step)
        for i, w in enumerate(text.split())
    ]


def _scene(pos, **overrides):
    base = {
        "id": f"scene-{pos}",
        "position": pos,
        "image_path": f"/img/{pos}.png",
        "audio_path": f"/aud/{pos}.mp3",
        "trim": (0.1, 3.1),
        "clip_duration_s": 3.2,
        "words": _words("cicak bisa menempel di dinding", start=0.1),
        "visual_type": "character",
        "transition": "cut",
        "subtitle_override": None,
        "voiceover": "cicak bisa menempel di dinding",
        "emphasis_words": [],
    }
    base.update(overrides)
    return SceneInput(**base)


def test_timeline_frame_rounded_and_last_scene_bonus():
    plan = build_render_plan(
        scenes=[_scene(1), _scene(2), _scene(3)], subtitle_style=STYLE
    )
    # per scene: trim span 3,0 + 0,08; terakhir + 0,4 -> 3,08/3,08/3,48 mentah
    durations = [s.duration_s for s in plan.scenes]
    assert abs(sum(durations) - plan.total_duration_s) < 1e-9
    assert abs(plan.total_duration_s - (3.08 + 3.08 + 3.48)) < 0.02
    for s in plan.scenes:
        frames = s.duration_s * 30
        assert abs(frames - round(frames)) < 1e-6  # batas utuh di bingkai


def test_words_shifted_to_global_minus_trim():
    plan = build_render_plan(scenes=[_scene(1), _scene(2)], subtitle_style=STYLE)
    second = plan.scenes[1]
    assert second.words[0].start >= second.start_s
    # kata pertama scene 2 mulai tepat di awal scene (0,1 - trim 0,1 = 0)
    assert abs(second.words[0].start - second.start_s) < 1e-6


def test_motion_rules():
    plan = build_render_plan(
        scenes=[
            _scene(1, visual_type="diagram"),
            _scene(2, visual_type="closeup"),
            _scene(3, visual_type="character"),
            _scene(4, visual_type="character"),
        ],
        subtitle_style=STYLE,
    )
    motions = [s.motion for s in plan.scenes]
    assert motions[0] == "static"
    assert motions[1] == "punch_in"
    assert motions[2] in {"zoom_in", "zoom_out", "pan_left", "pan_right"}
    assert motions[3] != motions[2]  # anti-ulang tetangga
    again = build_render_plan(
        scenes=[
            _scene(1, visual_type="diagram"),
            _scene(2, visual_type="closeup"),
            _scene(3, visual_type="character"),
            _scene(4, visual_type="character"),
        ],
        subtitle_style=STYLE,
    )
    assert [s.motion for s in again.scenes] == motions  # deterministik


def test_chunk_words_rules():
    words = _words("Satu dua, tiga empat lima enam tujuh delapan.", step=0.25)
    cues = chunk_words(words, style=STYLE)
    assert all(2 <= len(c.words) <= 4 for c in cues)
    # potong awal sesudah koma: cue pertama berakhir di "dua,"
    assert cues[0].words[-1].word == "dua,"
    text = " ".join(w.word for c in cues for w in c.words)
    assert text == "Satu dua, tiga empat lima enam tujuh delapan."


def test_ass_and_srt_output():
    words = _words("cicak hebat sekali", step=0.3)
    cues = chunk_words(words, style=STYLE, emphasis={"hebat"})
    ass = build_ass(cues, STYLE)
    assert "PlayResX: 1080" in ass
    assert "MarginV: 580" in ass or ",580," in ass
    assert "{\\c&H4DD8FF&\\fscx110\\fscy110}hebat{\\r}" in ass
    srt = build_srt(cues)
    assert "00:00:00,000 -->" in srt
    assert "cicak" in srt


def test_measure_and_long_line_split():
    assert measure_text_px("cicak", 78) > 0
    long_words = _words(" ".join(["kata"] * 20), step=0.2)
    cues = chunk_words(long_words, style=STYLE)
    for cue in cues:
        for line in cue.lines:
            assert len(line) <= 28


def test_plan_sfx_events_from_cues_and_transitions():
    from app.services.render_plan import SceneInput, build_render_plan

    def scene(pos, vo, cues):
        words = [
            WordTiming(word=w, start=i * 0.4, end=i * 0.4 + 0.3)
            for i, w in enumerate(vo.split())
        ]
        return SceneInput(
            id=f"s{pos}", position=pos, image_path="/i.png",
            audio_path="/a.mp3", trim=(0.0, 3.0), clip_duration_s=3.0,
            words=words, visual_type="character", voiceover=vo, sfx_cues=cues,
        )

    plan = build_render_plan(
        scenes=[
            scene(1, "Indeks pasar anjlok tajam", [{"sfx": "fall", "word": "anjlok"}]),
            scene(2, "Semua orang terdiam sekarang", [{"sfx": "ding", "word": "hantu"}]),
        ],
        subtitle_style=STYLE,
    )
    kinds = [(e.kind, e.sfx_id) for e in plan.sfx_events]
    assert ("cue", "fall") in kinds
    assert ("transition", "whoosh") in kinds
    ding = next(e for e in plan.sfx_events if e.sfx_id == "ding")
    assert ding.at_s >= plan.scenes[1].start_s - 0.01  # kata tak ketemu -> awal scene
    fall = next(e for e in plan.sfx_events if e.sfx_id == "fall")
    assert 0.7 < fall.at_s < 0.9  # kata ke-3 pada 0.4 dtk/kata
