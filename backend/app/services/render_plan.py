import hashlib
from dataclasses import dataclass, field

FPS = 30
PAUSE_S = 0.08
LAST_SCENE_BONUS_S = 0.4
MOTIONS = ("zoom_in", "zoom_out", "pan_left", "pan_right")


@dataclass
class WordTiming:
    word: str
    start: float
    end: float


@dataclass
class SceneInput:
    id: str
    position: int
    image_path: str
    audio_path: str
    trim: tuple[float, float] | None
    clip_duration_s: float
    words: list[WordTiming]
    visual_type: str
    transition: str = "cut"
    subtitle_override: str | None = None
    voiceover: str = ""
    emphasis_words: list[str] = field(default_factory=list)
    sfx_cues: list[dict] = field(default_factory=list)


@dataclass
class RenderScene:
    position: int
    image_path: str
    audio_path: str
    audio_trim: tuple[float, float]
    start_s: float
    duration_s: float
    motion: str
    transition_in: str
    words: list[WordTiming]


@dataclass
class SfxEvent:
    at_s: float
    sfx_id: str
    gain: float
    kind: str  # "cue" | "transition"


@dataclass
class RenderPlan:
    width: int = 1080
    height: int = 1920
    fps: int = FPS
    scenes: list[RenderScene] = field(default_factory=list)
    cues: list = field(default_factory=list)
    sfx_events: list[SfxEvent] = field(default_factory=list)
    subtitle_style: dict = field(default_factory=dict)

    @property
    def total_duration_s(self) -> float:
        if not self.scenes:
            return 0.0
        last = self.scenes[-1]
        return last.start_s + last.duration_s


def _frame_round(t: float) -> float:
    return int(t * FPS + 0.5) / FPS


def _pick_motion(scene: SceneInput, previous: str | None) -> str:
    if scene.visual_type == "diagram":
        return "static"
    if scene.visual_type == "closeup":
        return "punch_in"
    digest = hashlib.sha256(scene.id.encode("utf-8")).digest()
    start = digest[0] % len(MOTIONS)
    for offset in range(len(MOTIONS)):
        candidate = MOTIONS[(start + offset) % len(MOTIONS)]
        if candidate != previous:
            return candidate
    return MOTIONS[start]


def build_render_plan(*, scenes: list[SceneInput], subtitle_style: dict) -> RenderPlan:
    """Rencana render murni (Spec §8.1-8.5): timeline berbingkai utuh, kata
    digeser ke waktu global, motion deterministik, cue subtitle global."""
    from app.services import sfx_catalog
    from app.services.subtitles import chunk_words, proportional_words

    plan = RenderPlan(subtitle_style=dict(subtitle_style))
    ordered = sorted(scenes, key=lambda s: s.position)
    cumulative = 0.0
    boundaries: list[float] = [0.0]
    for index, scene in enumerate(ordered):
        trim = scene.trim or (0.0, scene.clip_duration_s)
        span = max(trim[1] - trim[0], 0.0)
        raw = span + PAUSE_S + (LAST_SCENE_BONUS_S if index == len(ordered) - 1 else 0.0)
        cumulative += raw
        boundaries.append(_frame_round(cumulative))
    previous_motion: str | None = None
    all_cues = []
    for index, scene in enumerate(ordered):
        start_s = boundaries[index]
        duration_s = boundaries[index + 1] - boundaries[index]
        trim = scene.trim or (0.0, scene.clip_duration_s)
        span = max(trim[1] - trim[0], 0.0)
        global_words = [
            WordTiming(
                word=w.word,
                start=start_s + max(w.start - trim[0], 0.0),
                end=start_s + max(w.end - trim[0], 0.0),
            )
            for w in scene.words
        ]
        motion = _pick_motion(scene, previous_motion)
        previous_motion = motion
        transition = scene.transition or "cut"
        previous_duration = (
            boundaries[index] - boundaries[index - 1] if index > 0 else 0.0
        )
        if index == 0 or duration_s < 0.5 or previous_duration < 0.5:
            transition = "cut"
        plan.scenes.append(
            RenderScene(
                position=scene.position,
                image_path=scene.image_path,
                audio_path=scene.audio_path,
                audio_trim=(trim[0], trim[1]),
                start_s=start_s,
                duration_s=duration_s,
                motion=motion,
                transition_in=transition,
                words=global_words,
            )
        )
        for cue in scene.sfx_cues or []:
            sfx_id = str(cue.get("sfx", ""))
            if not sfx_catalog.is_valid_sfx(sfx_id):
                continue
            word = str(cue.get("word", "")).strip().lower()
            at_s = start_s
            for gw in global_words:
                if gw.word.strip(".,!?;:\"'").lower() == word:
                    at_s = gw.start
                    break
            gain = cue.get("gain")
            plan.sfx_events.append(
                SfxEvent(
                    at_s=round(at_s, 3),
                    sfx_id=sfx_id,
                    gain=float(gain) if gain is not None else sfx_catalog.default_gain(sfx_id),
                    kind="cue",
                )
            )
        if index > 0:
            plan.sfx_events.append(
                SfxEvent(
                    at_s=round(max(start_s - 0.15, 0.0), 3),
                    sfx_id=sfx_catalog.TRANSITION_SFX,
                    gain=sfx_catalog.TRANSITION_GAIN,
                    kind="transition",
                )
            )
        if scene.subtitle_override:
            cue_words_in = proportional_words(
                scene.subtitle_override, start_s, start_s + span
            )
            scene_cues = chunk_words(
                cue_words_in,
                subtitle_style,
                emphasis={e.lower() for e in scene.emphasis_words},
            )
        else:
            scene_cues = chunk_words(
                global_words,
                subtitle_style,
                emphasis={e.lower() for e in scene.emphasis_words},
            )
        all_cues.extend(scene_cues)
    plan.cues = all_cues
    return plan
