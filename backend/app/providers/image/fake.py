import hashlib
import io

from PIL import Image, ImageDraw

from app.providers.base import ImageCaps, ImageRequest, ImageResult, Usage


class FakeImage:
    caps = ImageCaps(supports_reference_image=False)

    async def generate_image(self, req: ImageRequest, ctx=None) -> ImageResult:
        digest = hashlib.sha256(req.prompt.encode("utf-8")).digest()
        color = (digest[0], digest[1], digest[2])
        img = Image.new("RGB", (1080, 1920), color)
        label = req.extra.get("label") or req.prompt[:24]
        ImageDraw.Draw(img).text((40, 900), str(label), fill=(255, 255, 255))
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return ImageResult(
            image=buffer.getvalue(), width=1080, height=1920, usage=Usage(images=1)
        )
