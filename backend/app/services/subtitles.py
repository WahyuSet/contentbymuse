from dataclasses import dataclass, field
from functools import lru_cache

from PIL import ImageFont

from app.services.render_settings import FONT_FILE

_PUNCT_END = (".", ",", "!", "?", ";")


@dataclass
class CueWord:
    word: str
    start: float
    end: float
    emphasis: bool = False


@dataclass
class Cue:
    words: list[CueWord] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end


@lru_cache(maxsize=8)
def _font(size: int):
    return ImageFont.truetype(str(FONT_FILE), size)


def measure_text_px(text: str, size: int) -> float:
    return _font(size).getlength(text)


def _wrap(words: list[CueWord], style: dict) -> list[str] | None:
    """Susun kata menjadi <=2 baris yang lolos batas char dan piksel."""
    max_chars = int(style["max_chars"])
    max_px = float(style["max_width_px"])
    size = int(style["size"])
    lines: list[str] = []
    current = ""
    for item in words:
        candidate = f"{current} {item.word}".strip()
        if len(candidate) <= max_chars and measure_text_px(candidate, size) <= max_px:
            current = candidate
            continue
        if not current:
            return None  # satu kata saja sudah melanggar batas
        lines.append(current)
        current = item.word
        if len(lines) > 1:
            return None
    if current:
        lines.append(current)
    return lines if 1 <= len(lines) <= 2 else None


def chunk_words(words, style: dict, emphasis: set[str] | None = None) -> list[Cue]:
    """Potong kata menjadi cue 2-4 kata (Spec §8.5): potong lebih awal pada
    tanda baca akhir kata; setiap cue harus terbungkus <=2 baris sah."""
    emphasis = {e.lower() for e in (emphasis or set())}
    items = [
        CueWord(
            word=w.word,
            start=w.start,
            end=w.end,
            emphasis=w.word.strip(".,!?;:\"'").lower() in emphasis,
        )
        for w in words
    ]
    cues: list[Cue] = []

    def flush(group: list[CueWord]) -> None:
        if group:
            cues.append(Cue(words=group, lines=_wrap(group, style) or []))

    current: list[CueWord] = []
    for item in items:
        trial = current + [item]
        if len(trial) > 4 or _wrap(trial, style) is None:
            flush(current)
            current = [item]
            continue
        current = trial
        if len(current) == 4 or (
            item.word.endswith(_PUNCT_END) and len(current) >= 2
        ):
            flush(current)
            current = []
    if current:
        # Sisa 1 kata digabung ke cue terakhir bila masih sah, agar tidak ada
        # cue satu kata yang melanggar aturan 2-4 kata.
        if len(current) == 1 and cues:
            merged = cues[-1].words + current
            wrapped = _wrap(merged, style)
            if wrapped is not None and len(merged) <= 4:
                cues[-1] = Cue(words=merged, lines=wrapped)
            else:
                cues.append(Cue(words=current, lines=_wrap(current, style) or []))
        else:
            cues.append(Cue(words=current, lines=_wrap(current, style) or []))
    return cues


def proportional_words(text: str, start: float, end: float) -> list:
    """Kata dari teks override dengan waktu proporsional menurut panjang."""
    from app.services.render_plan import WordTiming

    tokens = text.split()
    if not tokens:
        return []
    weights = [len(t) + 1 for t in tokens]
    total = sum(weights)
    span = max(end - start, 0.0)
    out = []
    cursor = start
    for token, weight in zip(tokens, weights, strict=True):
        dur = span * weight / total
        out.append(WordTiming(word=token, start=cursor, end=cursor + dur))
        cursor += dur
    return out


def _ass_time(seconds: float) -> str:
    cs = round(seconds * 100)
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _srt_time(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ass_escape(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\n", " ")


def _emphasis_tags(style: dict) -> tuple[str, str]:
    hex_color = style["emphasis_color"].lstrip("#")  # RRGGBB
    rr, gg, bb = hex_color[0:2], hex_color[2:4], hex_color[4:6]
    return f"{{\\c&H{bb}{gg}{rr}&\\fscx110\\fscy110}}", "{\\r}"


def build_ass(cues: list[Cue], style: dict) -> str:
    size = int(style["size"])
    outline = int(style["outline"])
    margin_v = int(style["margin_v"])
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
        "WrapStyle: 2\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{style['font']},{size},&H00FFFFFF,&H000000FF,"
        f"&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,{outline},0,2,10,10,"
        f"{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )
    open_tag, close_tag = _emphasis_tags(style)
    lines = [header]
    for cue in cues:
        # Susun ulang teks dari kata agar tag emphasis menempel per kata,
        # mengikuti jeda baris hasil wrap.
        rendered_lines: list[str] = []
        index = 0
        for line in cue.lines:
            parts = []
            for _ in line.split():
                item = cue.words[index]
                index += 1
                text = _ass_escape(item.word)
                parts.append(f"{open_tag}{text}{close_tag}" if item.emphasis else text)
            rendered_lines.append(" ".join(parts))
        text = "\\N".join(rendered_lines)
        lines.append(
            f"Dialogue: 0,{_ass_time(cue.start)},{_ass_time(cue.end)},"
            f"Default,,0,0,0,,{text}"
        )
    return "\n".join(lines) + "\n"


def build_srt(cues: list[Cue]) -> str:
    blocks = []
    for i, cue in enumerate(cues, start=1):
        text = "\n".join(cue.lines)
        blocks.append(
            f"{i}\n{_srt_time(cue.start)} --> {_srt_time(cue.end)}\n{text}"
        )
    return "\n\n".join(blocks) + "\n"

