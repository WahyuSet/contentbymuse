from app.providers.image.fake import FakeImage
from app.providers.llm.fake import FakeLLM
from app.providers.llm.openai_compatible import OpenAICompatibleLLM
from app.providers.video.fake import FakeVideo
from app.providers.voice.fake import FakeVoice
from app.providers.voice.muse_cli import MuseCliVoice

# Nama vendor hanya boleh muncul di folder providers/ dan tabel ini (Spec §1).
ADAPTERS: dict[tuple[str, str], type] = {
    ("llm", "fake"): FakeLLM,
    ("llm", "openai_compatible"): OpenAICompatibleLLM,
    ("voice", "fake"): FakeVoice,
    ("voice", "muse_cli"): MuseCliVoice,
    ("image", "fake"): FakeImage,
    ("video", "fake"): FakeVideo,
}
