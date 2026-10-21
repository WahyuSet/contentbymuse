import pytest

from app.storage.local import LocalStorage


async def test_put_open_roundtrip(tmp_path):
    storage = LocalStorage(tmp_path)
    stored = await storage.put("a/b.bin", b"halo", "application/octet-stream")
    assert stored.size_bytes == 4
    chunks = [chunk async for chunk in storage.open("a/b.bin")]
    assert b"".join(chunks) == b"halo"
    assert await storage.local_path("a/b.bin") == tmp_path / "a" / "b.bin"


async def test_traversal_key_rejected(tmp_path):
    storage = LocalStorage(tmp_path)
    with pytest.raises(ValueError):
        await storage.local_path("../kabur.bin")
    with pytest.raises(ValueError):
        await storage.put("../kabur.bin", b"x", "text/plain")
