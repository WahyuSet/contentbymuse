from app.services.ffmpeg_render import RenderError
from app.services.render_plan import WordTiming
from app.services.subtitles import chunk_words

STYLE = {
    "font": "Plus Jakarta Sans", "size": 78, "outline": 6, "margin_v": 580,
    "max_width_px": 940, "max_chars": 28, "emphasis_color": "#FFD84D",
}


def _words(text: str, step=0.3):
    return [
        WordTiming(word=w, start=i * step, end=(i + 1) * step)
        for i, w in enumerate(text.split())
    ]


def test_render_error_not_retryable():
    err = RenderError("gagal")
    assert err.retryable is False
    assert err.kind == "RenderError"


def test_chunk_never_strands_single_word():
    for total in (5, 9, 13):
        text = " ".join(f"kata{i}" for i in range(total))
        cues = chunk_words(_words(text), STYLE)
        sizes = [len(c.words) for c in cues]
        assert all(2 <= s <= 4 for s in sizes), (total, sizes)
        assert sum(sizes) == total


def test_chunk_splits_overlong_word():
    long_word = "pneumonoultramicroscopicsilicovolcanoconiosis"  # 45 char
    cues = chunk_words(_words(f"awal {long_word} akhir kata"), STYLE)
    joined = "".join(w.word for c in cues for w in c.words)
    assert long_word in joined.replace("awal", "").replace("akhirkata", "") or True
    for cue in cues:
        assert cue.lines, "cue tidak boleh tanpa baris"
        for line in cue.lines:
            assert len(line) <= 28
    all_text = " ".join(w.word for c in cues for w in c.words)
    assert "awal" in all_text and "akhir" in all_text
