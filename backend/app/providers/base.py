from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel


@dataclass
class CallContext:
    job_id: str | None
    progress: Callable[[int, str], Awaitable[None]]
    cancelled: Callable[[], Awaitable[bool]]
    log: Callable[[str, str, dict | None], Awaitable[None]]


@dataclass
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    characters: int | None = None
    images: int | None = None
    seconds: float | None = None


@dataclass
class Message:
    role: str
    content: str


@dataclass
class TextRequest:
    messages: list[Message]
    model: str | None = None
    temperature: float = 0.8
    max_tokens: int = 4000
    response_schema: type[BaseModel] | None = None


@dataclass
class TextResult:
    text: str
    usage: Usage = field(default_factory=Usage)
    model: str = "fake"
    latency_ms: int = 0
    finish_reason: str | None = None


@dataclass
class VoiceRequest:
    text: str
    voice_id: str
    model: str | None = None
    language: str = "id-ID"
    previous_text: str | None = None
    next_text: str | None = None


@dataclass
class WordTiming:
    word: str
    start: float
    end: float


@dataclass
class VoiceResult:
    audio: bytes
    mime: str = "audio/wav"
    word_timings: list[WordTiming] | None = None
    usage: Usage = field(default_factory=Usage)


@dataclass
class ImageRequest:
    prompt: str
    negative_prompt: str | None = None
    aspect_ratio: str = "9:16"
    reference_images: list[bytes] = field(default_factory=list)
    seed: int | None = None
    model: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageResult:
    image: bytes
    mime: str = "image/png"
    width: int = 0
    height: int = 0
    revised_prompt: str | None = None
    usage: Usage = field(default_factory=Usage)


@dataclass
class VideoRequest:
    prompt: str
    aspect_ratio: str = "9:16"
    model: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class VideoResult:
    video: bytes
    mime: str = "video/mp4"
    width: int = 0
    height: int = 0
    usage: Usage = field(default_factory=Usage)


@dataclass
class LLMCaps:
    structured: str = "json_object"


@dataclass
class VoiceCaps:
    returns_timestamps: bool = True
    supports_context: bool = False


@dataclass
class ImageCaps:
    supports_reference_image: bool = False


@dataclass
class VideoCaps:
    pass


class LLMProvider(Protocol):
    caps: LLMCaps

    async def generate_text(self, req: TextRequest, ctx: CallContext | None) -> TextResult: ...


class VoiceProvider(Protocol):
    caps: VoiceCaps

    async def synthesize(self, req: VoiceRequest, ctx: CallContext | None) -> VoiceResult: ...


class ImageProvider(Protocol):
    caps: ImageCaps

    async def generate_image(self, req: ImageRequest, ctx: CallContext | None) -> ImageResult: ...


class VideoProvider(Protocol):
    caps: VideoCaps

    async def generate_video(self, req: VideoRequest, ctx: CallContext | None) -> VideoResult: ...
