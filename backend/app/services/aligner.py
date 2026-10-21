import asyncio
import os
import string
from collections.abc import Callable
from dataclasses import dataclass, field
from difflib import SequenceMatcher

_PUNCT = string.punctuation + "“”‘’«»—–…"


def normalize_token(word: str) -> str:
    return word.strip().lower().strip(_PUNCT)


@dataclass
class AlignWord:
    word: str
    start: float
    end: float


@dataclass
class AlignResult:
    words: list[AlignWord] = field(default_factory=list)
    method: str = "proportional"
    match_ratio: float = 0.0


class ProportionalAligner:
    """Bagi rentang waktu menurut jumlah karakter tiap kata (Spec §4.7)."""

    def align(self, audio_path, text: str, ctx=None, bounds=(0.0, 0.0)) -> AlignResult:
        tokens = text.split()
        start_bound, end_bound = bounds
        total_chars = sum(len(t) for t in tokens) or 1
        span = max(end_bound - start_bound, 0.0)
        words: list[AlignWord] = []
        cursor = start_bound
        for token in tokens:
            length = span * (len(token) / total_chars)
            words.append(
                AlignWord(word=token, start=round(cursor, 3), end=round(cursor + length, 3))
            )
            cursor += length
        if words:
            words[-1].end = round(end_bound, 3)
        return AlignResult(words=words, method="proportional", match_ratio=0.0)


def _default_transcriber(model_name: str) -> Callable:
    def _transcribe(audio_path) -> list[AlignWord]:
        from faster_whisper import WhisperModel

        try:
            model = WhisperModel(model_name, device="cuda", compute_type="int8")
        except Exception:  # noqa: BLE001 - CUDA tak tersedia berarti ulang di CPU
            model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(
            str(audio_path), language="id", word_timestamps=True
        )
        words: list[AlignWord] = []
        for segment in segments:
            for word in segment.words or []:
                words.append(
                    AlignWord(
                        word=word.word.strip(),
                        start=float(word.start),
                        end=float(word.end),
                    )
                )
        return words

    return _transcribe


class WhisperAligner:
    """Alignment Whisper yang tidak pernah melempar: gagal berarti proporsional."""

    def __init__(self, model_name: str | None = None, transcriber: Callable | None = None):
        self._model_name = model_name or os.environ.get("WHISPER_MODEL", "small")
        self._transcriber = transcriber

    def align(self, audio_path, text: str, ctx=None, bounds=(0.0, 0.0)) -> AlignResult:
        tokens = text.split()
        try:
            transcriber = self._transcriber or _default_transcriber(self._model_name)
            heard = [w for w in transcriber(audio_path) if normalize_token(w.word)]
        except Exception:  # noqa: BLE001 - job align tidak pernah gagal karena Whisper
            return ProportionalAligner().align(audio_path, text, ctx, bounds)
        if not tokens or not heard:
            return ProportionalAligner().align(audio_path, text, ctx, bounds)

        script_norm = [normalize_token(t) for t in tokens]
        heard_norm = [normalize_token(w.word) for w in heard]
        matcher = SequenceMatcher(a=script_norm, b=heard_norm, autojunk=False)
        matched: dict[int, AlignWord] = {}
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for offset in range(i2 - i1):
                    heard_word = heard[j1 + offset]
                    matched[i1 + offset] = AlignWord(
                        word=tokens[i1 + offset],
                        start=heard_word.start,
                        end=heard_word.end,
                    )
        ratio = len(matched) / len(tokens)
        if ratio < 0.6:
            result = ProportionalAligner().align(audio_path, text, ctx, bounds)
            result.match_ratio = ratio
            if ctx is not None:
                ctx.log(
                    f"Rasio kecocokan Whisper rendah ({ratio:.2f}); "
                    "memakai alignment proporsional."
                )
            return result

        # Interpolasi kata yang tidak cocok di antara jangkar terdekat.
        anchors = sorted(matched)
        words: list[AlignWord] = []
        for index, token in enumerate(tokens):
            if index in matched:
                words.append(matched[index])
                continue
            before = max((a for a in anchors if a < index), default=None)
            after = min((a for a in anchors if a > index), default=None)
            if before is not None and after is not None:
                span_start = matched[before].end
                span_end = matched[after].start
                gap = after - before - 1
                slot = index - before
                step = (span_end - span_start) / (gap + 1)
                start = span_start + step * (slot - 1)
                words.append(
                    AlignWord(word=token, start=round(start, 3), end=round(start + step, 3))
                )
            elif after is not None:
                step = matched[after].end - matched[after].start
                words.append(
                    AlignWord(
                        word=token,
                        start=round(matched[after].start - step, 3),
                        end=round(matched[after].start, 3),
                    )
                )
            else:
                step = matched[before].end - matched[before].start
                words.append(
                    AlignWord(
                        word=token,
                        start=round(matched[before].end, 3),
                        end=round(matched[before].end + step, 3),
                    )
                )
        words.sort(key=lambda w: w.start)
        return AlignResult(
            words=words, method=f"whisper:{self._model_name}", match_ratio=ratio
        )


async def align_words(audio_path, text: str, *, bounds, ctx=None) -> AlignResult:
    """Jalur utama job align: Whisper di thread agar worker tidak terblokir."""
    aligner = WhisperAligner()
    return await asyncio.to_thread(aligner.align, audio_path, text, ctx, bounds)
