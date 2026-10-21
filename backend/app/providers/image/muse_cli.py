import asyncio
import json
import tempfile
from pathlib import Path

from PIL import Image

from app.providers.base import ImageCaps, ImageRequest, ImageResult, Usage
from app.providers.errors import ServerError


def _fail(message: str, detail: str | None = None) -> ServerError:
    # Kegagalan CLI lokal bersifat tetap di mesin ini; mengulang tidak membantu.
    error = ServerError(message, detail=detail)
    error.retryable = False
    return error


class MuseCliImage:
    """Gambar lewat CLI `media-generation` yang hanya ada di VM Muse.

    Invokasi terverifikasi lewat smoke test: prompt dan gambar referensi
    dikirim sebagai entri --conversation-json, orientasi vertical memberi
    9:16, dan path hasil dibaca dari media_paths[0] di stdout JSON — bukan
    dari tebakan nama file. CLI tidak punya flag negative prompt, jadi teks
    negatif digabung ke akhir prompt.
    """

    caps = ImageCaps(supports_reference_image=True)

    def __init__(self, quirks: dict | None = None):
        quirks = quirks or {}
        self._cli = quirks.get("cli_path", "media-generation")
        self._timeout_s = int(quirks.get("timeout_s", 600))

    async def generate_image(self, req: ImageRequest, ctx=None) -> ImageResult:
        prompt = req.prompt
        if req.negative_prompt:
            prompt = f"{prompt}\nAvoid: {req.negative_prompt}"
        with tempfile.TemporaryDirectory() as tmp:
            entries: list[dict] = []
            for index, reference in enumerate(req.reference_images):
                ref_path = Path(tmp) / f"reference-{index}.png"
                ref_path.write_bytes(reference)
                entries.append({"image": str(ref_path)})
            entries.append({"text": prompt})
            out_dir = Path(tmp) / "out"
            out_dir.mkdir()
            cmd = [
                self._cli,
                "--media-subagent-output-type", "image",
                "--orientation", "vertical",
                "--image-output-format", "jpg",
                "--output-dir", str(out_dir),
                "--timeout-secs", str(self._timeout_s),
                "--conversation-json", json.dumps(entries),
            ]
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as exc:
                raise _fail(
                    "CLI media-generation tidak ditemukan di mesin ini.",
                    detail=str(exc),
                ) from exc
            try:
                out, err = await asyncio.wait_for(
                    process.communicate(), timeout=self._timeout_s + 60
                )
            except TimeoutError as exc:
                process.kill()
                raise _fail("CLI media-generation melewati batas waktu.") from exc
            if process.returncode != 0:
                raise _fail(
                    "CLI media-generation gagal membuat gambar.",
                    detail=err.decode("utf-8", errors="replace")[:500],
                )
            try:
                payload = json.loads(out.decode("utf-8", errors="replace"))
                if payload.get("ok") is False:
                    raise _fail(
                        "CLI media-generation melaporkan kegagalan.",
                        detail=str(payload.get("error") or payload)[:500],
                    )
                media_path = Path(payload["media_paths"][0]).resolve()
                if not media_path.is_relative_to(out_dir.resolve()):
                    raise _fail(
                        "Path hasil CLI berada di luar direktori keluaran.",
                        detail=str(media_path),
                    )
                data = media_path.read_bytes()
                with Image.open(media_path) as image:
                    width, height = image.size
                    mime = Image.MIME.get(image.format, "image/jpeg")
            except Exception as exc:
                raise _fail(
                    "Keluaran CLI media-generation tidak bisa dibaca.",
                    detail=str(exc)[:500],
                ) from exc
            return ImageResult(
                image=data, mime=mime, width=width, height=height,
                usage=Usage(images=1),
            )
