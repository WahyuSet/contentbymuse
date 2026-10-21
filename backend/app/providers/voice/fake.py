import io
import math
import wave

from app.providers.base import Usage, VoiceCaps, VoiceRequest, VoiceResult, WordTiming

_SAMPLE_RATE = 8000
_WORDS_PER_SECOND = 2.5


class FakeVoice:
    caps = VoiceCaps(returns_timestamps=True)

    async def synthesize(self, req: VoiceRequest, ctx=None) -> VoiceResult:
        words = req.text.split()
        duration = max(len(words) / _WORDS_PER_SECOND, 0.2)
        frames = int(duration * _SAMPLE_RATE)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(_SAMPLE_RATE)
            samples = bytearray()
            for i in range(frames):
                value = int(6000 * math.sin(2 * math.pi * 220 * i / _SAMPLE_RATE))
                samples += value.to_bytes(2, "little", signed=True)
            wav.writeframes(bytes(samples))
        per_word = duration / max(len(words), 1)
        timings = [
            WordTiming(word=w, start=round(i * per_word, 3), end=round((i + 1) * per_word, 3))
            for i, w in enumerate(words)
        ]
        return VoiceResult(
            audio=buffer.getvalue(),
            word_timings=timings,
            usage=Usage(characters=len(req.text), seconds=duration),
        )
