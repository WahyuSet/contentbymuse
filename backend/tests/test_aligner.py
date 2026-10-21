from itertools import pairwise

from app.services.aligner import (
    AlignWord,
    ProportionalAligner,
    WhisperAligner,
    normalize_token,
)


def test_normalize_token():
    assert normalize_token("Cicak,") == "cicak"
    assert normalize_token("“Dinding!”") == "dinding"


def test_proportional_splits_by_characters():
    result = ProportionalAligner().align(
        None, "aaaa bb cc d", bounds=(0.0, 5.0)
    )
    assert result.method == "proportional"
    words = result.words
    assert [w.word for w in words] == ["aaaa", "bb", "cc", "d"]
    # Total karakter tanpa spasi 9: 4/9*5=2.22, 2/9*5=1.11, 1/9*5=0.56.
    assert words[0].start == 0.0
    assert abs(words[0].end - 2.222) < 0.01
    assert abs(words[-1].end - 5.0) < 0.01
    for prev, nxt in pairwise(words):
        assert nxt.start >= prev.end - 1e-9


def test_proportional_respects_bounds_offset():
    result = ProportionalAligner().align(None, "satu dua", bounds=(1.0, 3.0))
    assert result.words[0].start == 1.0
    assert abs(result.words[-1].end - 3.0) < 0.01


def _fake_transcriber(words):
    def _transcribe(_path):
        return [
            AlignWord(word=w, start=i * 0.5, end=(i + 1) * 0.5)
            for i, w in enumerate(words)
        ]

    return _transcribe


def test_whisper_exact_match():
    aligner = WhisperAligner(transcriber=_fake_transcriber(["satu", "dua", "tiga"]))
    result = aligner.align(None, "Satu, dua tiga!", bounds=(0.0, 1.5))
    assert result.method.startswith("whisper")
    assert result.match_ratio == 1.0
    assert [w.start for w in result.words] == [0.0, 0.5, 1.0]


def test_whisper_interpolates_missing_words():
    aligner = WhisperAligner(transcriber=_fake_transcriber(["satu", "tiga"]))
    result = aligner.align(None, "satu dua tiga", bounds=(0.0, 1.5))
    assert result.method.startswith("whisper")
    assert abs(result.match_ratio - 2 / 3) < 0.01
    middle = result.words[1]
    assert result.words[0].end <= middle.start <= middle.end <= result.words[2].start + 0.5
    starts = [w.start for w in result.words]
    assert starts == sorted(starts)


def test_whisper_failure_falls_back_to_proportional():
    def _boom(_path):
        raise RuntimeError("model tidak ada")

    result = WhisperAligner(transcriber=_boom).align(
        None, "satu dua", bounds=(0.0, 2.0)
    )
    assert result.method == "proportional"
    assert len(result.words) == 2


def test_whisper_low_match_ratio_uses_proportional():
    aligner = WhisperAligner(transcriber=_fake_transcriber(["xyz", "abc"]))
    result = aligner.align(None, "satu dua tiga empat", bounds=(0.0, 4.0))
    assert result.method == "proportional"
    assert result.match_ratio < 0.6
