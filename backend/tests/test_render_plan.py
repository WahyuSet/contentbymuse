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
            # Fase 13: beat hook/twist/impact selalu punch_in, apa pun
            # visual_type-nya (termasuk diagram twist).
            _scene(5, visual_type="character", beat="hook"),
            _scene(6, visual_type="diagram", beat="twist"),
            _scene(7, visual_type="environment", beat="impact"),
        ],
        subtitle_style=STYLE,
    )
    motions = [s.motion for s in plan.scenes]
    assert motions[0] == "static"
    assert motions[1] == "punch_in"
    assert motions[2] in {"zoom_in", "zoom_out", "pan_left", "pan_right"}
    assert motions[3] != motions[2]  # anti-ulang tetangga
    assert motions[4] == "punch_in"
    assert motions[5] == "punch_in"
    assert motions[6] == "punch_in"
    assert [s.beat for s in plan.scenes[4:]] == ["hook", "twist", "impact"]
    again = build_render_plan(
        scenes=[
            _scene(1, visual_type="diagram"),
            _scene(2, visual_type="closeup"),
            _scene(3, visual_type="character"),
            _scene(4, visual_type="character"),
        ],
        subtitle_style=STYLE,
    )
    assert [s.motion for s in again.scenes] == motions[:4]  # deterministik


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
    # Fase 13 karaoke: tiap kata bertag \k<durasi_cs>; kata yang sudah
    # terucap digambar Primary (kuning), yang belum Secondary (putih).
    assert "{\\k30}cicak" in ass
    assert "{\\k30}hebat" in ass
    assert "&H0000FFFF,&H00FFFFFF," in ass
    # Tag emphasis emas lama tidak lagi dipakai di mode karaoke.
    assert "\\c&H" not in ass
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
            scene(1, "Indeks pasar anjlok tajam", [{"sfx": "whoosh", "word": "anjlok"}]),
            scene(2, "Semua orang terdiam sekarang", [{"sfx": "whoosh", "word": "hantu"}]),
        ],
        subtitle_style=STYLE,
    )
    kinds = [(e.kind, e.sfx_id) for e in plan.sfx_events]
    assert ("cue", "whoosh") in kinds
    assert ("transition", "whoosh") in kinds
    transisi = next(e for e in plan.sfx_events if e.kind == "transition")
    # Whoosh transisi harus menonjol (gain tinggi) dan terpusat di titik potong.
    from app.services import sfx_catalog

    half = sfx_catalog.SFX_CATALOG["whoosh"]["duration_s"] / 2
    assert transisi.gain == 0.85
    assert abs(transisi.at_s - (plan.scenes[1].start_s - half)) < 0.01
    cues = [e for e in plan.sfx_events if e.kind == "cue"]
    assert len(cues) == 2
    assert cues[1].at_s >= plan.scenes[1].start_s - 0.01  # kata tak ketemu -> awal scene
    assert 0.7 < cues[0].at_s < 0.9  # kata ke-3 pada 0.4 dtk/kata
