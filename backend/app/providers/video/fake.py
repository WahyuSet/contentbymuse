import asyncio
import tempfile
from pathlib import Path

from app.providers.base import Usage, VideoCaps, VideoRequest, VideoResult


class FakeVideo:
    caps = VideoCaps()

    async def generate_video(self, req: VideoRequest, ctx=None) -> VideoResult:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "clip.mp4"
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=1080x1920:d=2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(out),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            if proc.returncode != 0:
                raise RuntimeError("ffmpeg gagal membuat klip fake")
            data = out.read_bytes()
        return VideoResult(video=data, width=1080, height=1920, usage=Usage(seconds=2.0))
